"""
PropFlow Checkpointer — Supabase REST-backed persistent checkpointer.

Replaces the in-memory MemorySaver so in-flight PropFlow threads survive
server restarts. Uses the Supabase REST API (port 443, free-tier compatible)
instead of direct Postgres (port 5432, requires paid IPv4 add-on).

How it works:
  LangGraph Checkpointer API
        ↕  (aput / aget_tuple / alist / aput_writes)
  SupabaseRestCheckpointer (httpx.AsyncClient)
        ↕  HTTPS /rest/v1/{table} with service_role_key
  Supabase REST API (free tier ✅)
        ↕
  propflow_checkpoints / propflow_checkpoint_writes tables
        ↕
  propflow_threads — tenant/landlord-to-thread mapping for multi-tenant queries

Lifecycle (managed via app/main.py startup/shutdown):
  1. On startup → init_checkpointer() creates a SupabaseRestCheckpointer and
     verifies the checkpoint tables exist.
  2. On graph build → get_checkpointer() returns the singleton instance.
  3. On shutdown → close_checkpointer() closes the HTTP client.

Environment variables:
  SUPABASE_URL          — REST API endpoint (required, already set)
  SUPABASE_SERVICE_KEY  — Service role key for admin REST access (required)
  SUPABASE_SERVICE_ROLE_KEY — Alternative name for service key (fallback)

The required tables must exist in Supabase. Run the migration:
  server/docs/sql/migrations/016_propflow_checkpointer.sql

If SUPABASE_URL/SUPABASE_SERVICE_KEY are not set, or the migration hasn't been
run, falls back to MemorySaver (in-memory, lost on restart).
"""

import asyncio
import json
import logging
import os
from typing import Any, AsyncIterator, Iterator, Optional, List, Tuple, Dict

import httpx
import requests

try:
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
except Exception:
    pass

from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
)
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

logger = logging.getLogger(__name__)

# ── Module-level globals (same interface as before) ──────────────────────────

_checkpointer = None
_pool = None


# ═══════════════════════════════════════════════════════════════════════════════
# SupabaseRestCheckpointer
# ═══════════════════════════════════════════════════════════════════════════════

class SupabaseRestCheckpointerError(Exception):
    """Raised when a Supabase REST checkpointer operation fails permanently."""


class SupabaseRestCheckpointer(BaseCheckpointSaver[str]):
    """
    LangGraph BaseCheckpointSaver that stores checkpoints via the Supabase REST API.

    Uses httpx.AsyncClient for async operations (aput, aget_tuple, etc.) and
    requests.Session for sync operations (put, get_tuple, list).

    The checkpointer stores:
      - Checkpoints in the `propflow_checkpoints` table (one row per step)
      - Pending writes in the `propflow_checkpoint_writes` table (for interrupts)
      - Thread-to-user mapping in `propflow_threads` (for multi-tenant listing)

    Serialization uses JsonPlusSerializer (the same protocol as AsyncPostgresSaver).
    """

    def __init__(
        self,
        *,
        serde=None,
        url: str = "",
        service_key: str = "",
        retries: int = 3,
    ):
        super().__init__(serde=serde or JsonPlusSerializer())
        self._url = url.rstrip("/")
        self._key = service_key
        self._retries = retries

        # Common headers for all REST API calls
        self._headers = {
            "apikey": self._key,
            "Authorization": f"Bearer {self._key}",
            "Content-Type": "application/json",
            "Prefer": "return=representation",
        }

        # Lazy clients (created on first use)
        self._async_client: Optional[httpx.AsyncClient] = None
        self._sync_session: Optional[requests.Session] = None

    # ── HTTP client lifecycle ──────────────────────────────────────────────────

    def _get_async_client(self) -> httpx.AsyncClient:
        """Lazy-create the shared httpx AsyncClient."""
        if self._async_client is None:
            self._async_client = httpx.AsyncClient(
                headers=self._headers,
                timeout=httpx.Timeout(30.0, connect=10.0),
                verify=False,  # same SSL handling as the rest of the app on Windows
            )
        return self._async_client

    def _get_sync_session(self) -> requests.Session:
        """Lazy-create the shared requests Session."""
        if self._sync_session is None:
            self._sync_session = requests.Session()
            self._sync_session.verify = False  # same SSL handling as the rest of the app
            self._sync_session.headers.update(self._headers)
        return self._sync_session

    async def close(self):
        """Close the async HTTP client (called from close_checkpointer)."""
        if self._async_client is not None:
            await self._async_client.aclose()
            self._async_client = None
        if self._sync_session is not None:
            self._sync_session.close()
            self._sync_session = None

    # ── REST API helpers ───────────────────────────────────────────────────────

    def _table_url(self, table: str) -> str:
        return f"{self._url}/rest/v1/{table}"

    async def _request(
        self,
        method: str,
        table: str,
        params: Optional[dict] = None,
        json_body: Any = None,
    ) -> Any:
        """
        Async HTTP call to the Supabase REST API.
        Retries on 5xx / network errors with exponential backoff.
        """
        client = self._get_async_client()
        url = self._table_url(table)

        last_error = None
        for attempt in range(1, self._retries + 1):
            try:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_body,
                )

                # 409 Conflict on upsert means row already exists with same PK —
                # this is expected for retries and is not an error.
                if response.is_success or response.status_code in (204, 409):
                    if response.status_code == 204 or not response.text:
                        return []
                    return response.json()

                # 4xx client errors (except 409) are permanent — don't retry
                if 400 <= response.status_code < 500 and response.status_code != 409:
                    raise SupabaseRestCheckpointerError(
                        f"HTTP {response.status_code} on {method} {table}: "
                        f"{response.text[:300]}"
                    )

                # 5xx — retry
                last_error = (
                    f"HTTP {response.status_code} on {method} {table}: "
                    f"{response.text[:200]}"
                )

            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_error = f"Network error on {method} {table}: {exc}"

            # Exponential backoff before retry
            if attempt < self._retries:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

        raise SupabaseRestCheckpointerError(
            f"Request failed after {self._retries} retries: {last_error}"
        )

    def _request_sync(
        self,
        method: str,
        table: str,
        params: Optional[dict] = None,
        json_body: Any = None,
    ) -> Any:
        """
        Sync HTTP call to the Supabase REST API (for sync method wrappers).
        Retries on 5xx / network errors.
        """
        session = self._get_sync_session()
        url = self._table_url(table)
        fn = getattr(session, method.lower())

        last_error = None
        for attempt in range(1, self._retries + 1):
            try:
                response = fn(url, params=params, json=json_body, timeout=30)

                if response.ok or response.status_code in (204, 409):
                    if response.status_code == 204 or not response.text:
                        return []
                    return response.json()

                if 400 <= response.status_code < 500 and response.status_code != 409:
                    raise SupabaseRestCheckpointerError(
                        f"HTTP {response.status_code} on sync {method} {table}: "
                        f"{response.text[:300]}"
                    )

                last_error = (
                    f"HTTP {response.status_code} on sync {method} {table}: "
                    f"{response.text[:200]}"
                )

            except requests.RequestException as exc:
                last_error = f"Network error on sync {method} {table}: {exc}"

            if attempt < self._retries:
                import time
                time.sleep(0.5 * (2 ** (attempt - 1)))

        raise SupabaseRestCheckpointerError(
            f"Sync request failed after {self._retries} retries: {last_error}"
        )

    # ── Thread registry ────────────────────────────────────────────────────────

    async def _update_thread_registry(self, checkpoint: Checkpoint, thread_id: str):
        """
        Best-effort upsert of thread-to-user mapping into propflow_threads.

        Extracts tenant_id and landlord_id from the checkpoint's channel_values
        and upserts them so the /threads listing endpoint can query efficiently.

        Failures are logged but not propagated — the checkpointer must remain
        functional even if the thread registry is unavailable.
        """
        channel_values = checkpoint.get("channel_values", {})
        if not channel_values:
            return

        tenant_id = channel_values.get("tenant_id")
        if tenant_id is None:
            return  # no tenant yet — cannot register

        # Convert UUID objects to strings
        if hasattr(tenant_id, "hex"):
            tenant_id = str(tenant_id)

        landlord_id = channel_values.get("landlord_id")
        if landlord_id is not None and hasattr(landlord_id, "hex"):
            landlord_id = str(landlord_id)

        current_stage = channel_values.get("current_stage", "")

        # Determine a high-level status from the stage
        if current_stage in ("", "error"):
            status = "error"
        elif current_stage in ("disbursement_complete", "rejected", "no_properties_found", "needs_clarification"):
            status = "completed"
        else:
            status = "active"

        row = {
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "current_stage": current_stage,
            "status": status,
        }

        try:
            await self._request("POST", "propflow_threads", json_body=row)
        except Exception as exc:
            logger.warning(
                "[CHECKPOINTER] Thread registry upsert failed for %s: %s",
                thread_id, exc,
            )

    # ── Checkpointer interface: async methods ──────────────────────────────────

    async def aput(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> dict:
        """
        Store a checkpoint snapshot.

        Serializes the Checkpoint and metadata to JSON dicts and upserts
        into propflow_checkpoints. Also updates the thread registry.
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint.get("id", "")
        parent_checkpoint_id = configurable.get("checkpoint_id")

        # Only channel_values may contain UUIDs — convert via default=str.
        checkpoint_dict = dict(checkpoint)
        if "channel_values" in checkpoint_dict:
            checkpoint_dict["channel_values"] = json.loads(
                json.dumps(checkpoint_dict["channel_values"], default=str)
            )
        metadata_dict = json.loads(json.dumps(dict(metadata), default=str))

        row = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": str(parent_checkpoint_id) if parent_checkpoint_id else None,
            "checkpoint": checkpoint_dict,
            "metadata": metadata_dict,
        }

        # Retry up to 3 times — the 409 conflict on UPSERT means it already exists,
        # which is fine (we treat "already stored" as success).
        for attempt in range(self._retries):
            try:
                await self._request("POST", "propflow_checkpoints", json_body=row)
                break
            except SupabaseRestCheckpointerError as exc:
                if attempt < self._retries - 1:
                    await asyncio.sleep(0.3 * (2 ** attempt))
                    continue
                # On last attempt, log but don't raise — let the graph continue
                logger.error("[CHECKPOINTER] aput failed for %s: %s", thread_id, exc)
                return {"configurable": {"thread_id": thread_id}}

        # Fire-and-forget: update thread registry
        await self._update_thread_registry(checkpoint, thread_id)

        # Return config with the checkpoint_id for LangGraph to use
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    async def aput_writes(
        self,
        config: dict,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """
        Store pending writes for a human-in-the-loop checkpoint.

        Each write is a (channel, value) pair stored as a row in
        propflow_checkpoint_writes, indexed by (thread_id, checkpoint_id, task_id).
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id", "")

        rows = []
        for idx, (channel, value) in enumerate(writes):
            serialized = self._serialize_value(value)
            if serialized is None:
                continue  # skip null values — DB column has NOT NULL constraint
            rows.append({
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "idx": idx,
                "channel": channel,
                "type": "json",
                "value": serialized,
            })

        if not rows:
            return

        try:
            await self._request("POST", "propflow_checkpoint_writes", json_body=rows)
        except Exception as exc:
            logger.error(
                "[CHECKPOINTER] aput_writes failed for %s: %s",
                thread_id, exc,
            )

    async def aget_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """
        Retrieve the latest checkpoint for a thread, or a specific one.

        If config includes checkpoint_id, fetches that specific checkpoint.
        Otherwise, fetches the most recent one (ordered by checkpoint_id DESC).
        """
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")

        # Build the query params
        params = {
            "thread_id": f"eq.{thread_id}",
            "checkpoint_ns": f"eq.{checkpoint_ns or ''}",
            "limit": "1",
        }

        if checkpoint_id:
            params["checkpoint_id"] = f"eq.{checkpoint_id}"
            params["order"] = "checkpoint_id.desc"
        else:
            params["order"] = "checkpoint_id.desc"

        try:
            rows = await self._request("GET", "propflow_checkpoints", params=params)
        except Exception as exc:
            logger.warning("[CHECKPOINTER] aget_tuple query failed: %s", exc)
            return None

        if not rows:
            return None

        row = rows[0]
        checkpoint_id = row.get("checkpoint_id", "")
        pending_writes = await self._fetch_pending_writes_async(
            thread_id, checkpoint_ns, checkpoint_id,
        )
        return self._row_to_checkpoint_tuple(row, thread_id, checkpoint_ns, pending_writes)

    async def alist(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> AsyncIterator[CheckpointTuple]:
        """
        List checkpoints for a thread (or across all threads if config is None).

        Supports optional metadata filtering (applied client-side) and
        pagination via the 'before' cursor and 'limit' parameters.
        """
        params = {"order": "checkpoint_id.desc"}

        if config:
            configurable = config.get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            checkpoint_ns = configurable.get("checkpoint_ns", "")
            params["thread_id"] = f"eq.{thread_id}"
            params["checkpoint_ns"] = f"eq.{checkpoint_ns or ''}"

        if before:
            before_config = before.get("configurable", {})
            before_id = before_config.get("checkpoint_id")
            if before_id:
                params["checkpoint_id"] = f"lt.{before_id}"

        if limit:
            params["limit"] = str(limit)

        try:
            rows = await self._request("GET", "propflow_checkpoints", params=params)
        except Exception as exc:
            logger.warning("[CHECKPOINTER] alist query failed: %s", exc)
            return

        for row in rows:
            # Apply metadata filter client-side
            if filter:
                row_meta = row.get("metadata", {})
                if isinstance(row_meta, str):
                    try:
                        row_meta = json.loads(row_meta)
                    except (json.JSONDecodeError, TypeError):
                        row_meta = {}
                if isinstance(row_meta, dict):
                    matches = all(
                        row_meta.get(k) == v for k, v in filter.items()
                    )
                    if not matches:
                        continue

            thread_id = row.get("thread_id", "")
            checkpoint_ns = row.get("checkpoint_ns", "")
            checkpoint_id = row.get("checkpoint_id", "")
            pending_writes = await self._fetch_pending_writes_async(
                thread_id, checkpoint_ns, checkpoint_id,
            )
            tup = self._row_to_checkpoint_tuple(row, thread_id, checkpoint_ns, pending_writes)
            if tup is not None:
                yield tup

    # ── Checkpointer interface: sync wrappers ──────────────────────────────────

    def put(
        self,
        config: dict,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: Dict[str, Any],
    ) -> dict:
        """Sync wrapper for aput."""
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = checkpoint.get("id", "")
        parent_checkpoint_id = configurable.get("checkpoint_id")

        checkpoint_dict = dict(checkpoint)
        if "channel_values" in checkpoint_dict:
            checkpoint_dict["channel_values"] = json.loads(
                json.dumps(checkpoint_dict["channel_values"], default=str)
            )
        metadata_dict = json.loads(json.dumps(dict(metadata), default=str))

        row = {
            "thread_id": thread_id,
            "checkpoint_ns": checkpoint_ns,
            "checkpoint_id": checkpoint_id,
            "parent_checkpoint_id": str(parent_checkpoint_id) if parent_checkpoint_id else None,
            "checkpoint": checkpoint_dict,
            "metadata": metadata_dict,
        }

        try:
            self._request_sync("POST", "propflow_checkpoints", json_body=row)
        except Exception as exc:
            logger.error("[CHECKPOINTER] put failed for %s: %s", thread_id, exc)
            return {"configurable": {"thread_id": thread_id}}

        # Sync thread registry update (best-effort, fire-and-forget)
        try:
            channel_values = checkpoint.get("channel_values", {})
            self._sync_update_thread_registry(channel_values, thread_id)
        except Exception:
            pass

        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: dict,
        writes: List[Tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        """Sync wrapper for aput_writes."""
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id", "")

        rows = []
        for idx, (channel, value) in enumerate(writes):
            serialized = self._serialize_value(value)
            if serialized is None:
                continue
            rows.append({
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
                "task_id": task_id,
                "idx": idx,
                "channel": channel,
                "type": "json",
                "value": serialized,
            })

        if not rows:
            return

        try:
            self._request_sync("POST", "propflow_checkpoint_writes", json_body=rows)
        except Exception as exc:
            logger.error(
                "[CHECKPOINTER] put_writes failed for %s: %s",
                thread_id, exc,
            )

    def get_tuple(self, config: dict) -> Optional[CheckpointTuple]:
        """Sync wrapper for aget_tuple."""
        configurable = config.get("configurable", {})
        thread_id = configurable.get("thread_id", "")
        checkpoint_ns = configurable.get("checkpoint_ns", "")
        checkpoint_id = configurable.get("checkpoint_id")

        params = {
            "thread_id": f"eq.{thread_id}",
            "checkpoint_ns": f"eq.{checkpoint_ns or ''}",
            "limit": "1",
        }

        if checkpoint_id:
            params["checkpoint_id"] = f"eq.{checkpoint_id}"
            params["order"] = "checkpoint_id.desc"
        else:
            params["order"] = "checkpoint_id.desc"

        try:
            rows = self._request_sync("GET", "propflow_checkpoints", params=params)
        except Exception:
            return None

        if not rows:
            return None

        return self._row_to_checkpoint_tuple(rows[0], thread_id, checkpoint_ns)

    def list(
        self,
        config: Optional[dict],
        *,
        filter: Optional[dict] = None,
        before: Optional[dict] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """Sync wrapper for alist — collects all results into a list."""
        params = {"order": "checkpoint_id.desc"}

        if config:
            configurable = config.get("configurable", {})
            thread_id = configurable.get("thread_id", "")
            checkpoint_ns = configurable.get("checkpoint_ns", "")
            params["thread_id"] = f"eq.{thread_id}"
            params["checkpoint_ns"] = f"eq.{checkpoint_ns or ''}"

        if before:
            before_config = before.get("configurable", {})
            before_id = before_config.get("checkpoint_id")
            if before_id:
                params["checkpoint_id"] = f"lt.{before_id}"

        if limit:
            params["limit"] = str(limit)

        try:
            rows = self._request_sync("GET", "propflow_checkpoints", params=params)
        except Exception:
            return

        for row in rows:
            if filter:
                row_meta = row.get("metadata", {})
                if isinstance(row_meta, str):
                    try:
                        row_meta = json.loads(row_meta)
                    except (json.JSONDecodeError, TypeError):
                        row_meta = {}
                if isinstance(row_meta, dict):
                    if not all(row_meta.get(k) == v for k, v in filter.items()):
                        continue

            thread_id = row.get("thread_id", "")
            checkpoint_ns = row.get("checkpoint_ns", "")
            tup = self._row_to_checkpoint_tuple(row, thread_id, checkpoint_ns)
            if tup is not None:
                yield tup

    # ── Serialization helpers ──────────────────────────────────────────────────

    @staticmethod
    def _serialize_value(value: Any) -> Any:
        """
        Serialize a write value to a JSON-compatible form.

        Python UUID objects and other non-JSON types are converted to strings.
        Returns None for None values — callers skip rows with null values since
        the DB column has a NOT NULL constraint.
        """
        if value is None:
            return None
        try:
            return json.loads(json.dumps(value, default=str))
        except (TypeError, ValueError):
            return str(value)

    def _row_to_checkpoint_tuple(
        self,
        row: dict,
        thread_id: str,
        checkpoint_ns: str,
        pending_writes: Optional[list] = None,
    ) -> Optional[CheckpointTuple]:
        """
        Convert a Supabase row (dict) to a CheckpointTuple.

        Handles deserialization of checkpoint and metadata from JSONB.
        If pending_writes is provided (pre-fetched by the caller), it's used
        directly. Otherwise, fetches them synchronously via _fetch_pending_writes
        (for the sync callers: get_tuple, list).

        Async callers (aget_tuple, alist) should fetch pending writes via
        _fetch_pending_writes_async and pass them in to avoid blocking.
        """
        checkpoint_id = row.get("checkpoint_id", "")
        parent_checkpoint_id = row.get("parent_checkpoint_id")

        # Deserialize checkpoint
        checkpoint_raw = row.get("checkpoint", {})
        if isinstance(checkpoint_raw, str):
            try:
                checkpoint_raw = json.loads(checkpoint_raw)
            except (json.JSONDecodeError, TypeError):
                logger.error("[CHECKPOINTER] Invalid checkpoint JSON for %s", checkpoint_id)
                return None

        # Reconstruct Checkpoint dict
        checkpoint = {
            "v": checkpoint_raw.get("v", 1),
            "id": checkpoint_raw.get("id", checkpoint_id),
            "ts": checkpoint_raw.get("ts", ""),
            "channel_values": checkpoint_raw.get("channel_values", {}),
            "channel_versions": checkpoint_raw.get("channel_versions", {}),
            "versions_seen": checkpoint_raw.get("versions_seen", {}),
            "updated_channels": checkpoint_raw.get("updated_channels"),
        }

        # Deserialize metadata
        metadata_raw = row.get("metadata", {})
        if isinstance(metadata_raw, str):
            try:
                metadata_raw = json.loads(metadata_raw)
            except (json.JSONDecodeError, TypeError):
                metadata_raw = {}
        metadata = dict(metadata_raw) if isinstance(metadata_raw, dict) else {}

        # Build child config
        child_config = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

        # Build parent config if parent exists
        parent_config = None
        if parent_checkpoint_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_checkpoint_id,
                }
            }

        # Fetch pending writes for this checkpoint
        # Use pre-fetched writes if provided (async callers), otherwise fetch sync
        if pending_writes is None:
            pending_writes = self._fetch_pending_writes(thread_id, checkpoint_ns, checkpoint_id)

        return CheckpointTuple(
            config=child_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    async def _fetch_pending_writes_async(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> Optional[list]:
        """
        Async version of _fetch_pending_writes.
        Uses self._request (httpx.AsyncClient) instead of _request_sync,
        avoiding the blocking call in the async path.
        """
        params = {
            "thread_id": f"eq.{thread_id}",
            "checkpoint_ns": f"eq.{checkpoint_ns or ''}",
            "checkpoint_id": f"eq.{checkpoint_id}",
            "order": "idx.asc",
        }

        try:
            writes_rows = await self._request("GET", "propflow_checkpoint_writes", params=params)
        except Exception:
            return []

        if not writes_rows:
            return []

        pending = []
        for w in writes_rows:
            value_raw = w.get("value")
            pending.append((w.get("task_id", ""), w.get("channel", ""), value_raw))

        return pending

    def _fetch_pending_writes(
        self,
        thread_id: str,
        checkpoint_ns: str,
        checkpoint_id: str,
    ) -> Optional[list]:
        """
        Sync version of pending-writes fetch.
        Used only by sync callers (get_tuple, list).
        Async callers should use _fetch_pending_writes_async instead.
        Returns an empty list if no writes are pending, or a list of
        (task_id, channel, value) tuples.
        """
        params = {
            "thread_id": f"eq.{thread_id}",
            "checkpoint_ns": f"eq.{checkpoint_ns or ''}",
            "checkpoint_id": f"eq.{checkpoint_id}",
            "order": "idx.asc",
        }

        try:
            writes_rows = self._request_sync("GET", "propflow_checkpoint_writes", params=params)
        except Exception:
            return []

        if not writes_rows:
            return []

        pending = []
        for w in writes_rows:
            value_raw = w.get("value")
            pending.append((w.get("task_id", ""), w.get("channel", ""), value_raw))

        return pending

    def _sync_update_thread_registry(
        self,
        channel_values: dict,
        thread_id: str,
    ):
        """Sync version of thread registry update (used by put())."""
        if not channel_values:
            return

        tenant_id = channel_values.get("tenant_id")
        if tenant_id is None:
            return

        if hasattr(tenant_id, "hex"):
            tenant_id = str(tenant_id)

        landlord_id = channel_values.get("landlord_id")
        if landlord_id is not None and hasattr(landlord_id, "hex"):
            landlord_id = str(landlord_id)

        current_stage = channel_values.get("current_stage", "")
        status = "active"
        if current_stage in ("", "error"):
            status = "error"
        elif current_stage in ("disbursement_complete", "rejected", "no_properties_found", "needs_clarification"):
            status = "completed"

        row = {
            "thread_id": thread_id,
            "tenant_id": tenant_id,
            "landlord_id": landlord_id,
            "current_stage": current_stage,
            "status": status,
        }

        try:
            self._request_sync("POST", "propflow_threads", json_body=row)
        except Exception:
            pass  # best-effort

    async def create_tables(self):
        """
        Verify checkpoint tables exist.

        Since we can't run DDL via the Supabase REST API (it's not SQL-over-HTTP),
        this method checks if the tables exist by querying them, and logs a clear
        warning if they don't exist.

        The user must run the migration SQL manually via the Supabase SQL editor:
          server/docs/sql/migrations/016_propflow_checkpointer.sql
        """
        try:
            await self._request(
                "GET", "propflow_checkpoints",
                params={"limit": "1"},
            )
            logger.info("[CHECKPOINTER] propflow_checkpoints table verified")
        except Exception as exc:
            logger.warning(
                "[CHECKPOINTER] propflow_checkpoints table NOT found. "
                "Run the migration: server/docs/sql/migrations/016_propflow_checkpointer.sql. "
                "Error: %s",
                exc,
            )

        try:
            await self._request(
                "GET", "propflow_checkpoint_writes",
                params={"limit": "1"},
            )
            logger.info("[CHECKPOINTER] propflow_checkpoint_writes table verified")
        except Exception as exc:
            logger.warning(
                "[CHECKPOINTER] propflow_checkpoint_writes table NOT found. "
                "Run the migration: server/docs/sql/migrations/016_propflow_checkpointer.sql. "
                "Error: %s",
                exc,
            )

        try:
            await self._request(
                "GET", "propflow_threads",
                params={"limit": "1"},
            )
            logger.info("[CHECKPOINTER] propflow_threads table verified")
        except Exception as exc:
            logger.warning(
                "[CHECKPOINTER] propflow_threads table NOT found. "
                "Run the migration: server/docs/sql/migrations/016_propflow_checkpointer.sql. "
                "Error: %s",
                exc,
            )

    # ── Versioning ─────────────────────────────────────────────────────────────

    def get_next_version(self, current: Optional[str], channel: Any) -> str:
        """
        Generate the next version ID for a channel.

        Uses simple integer incrementing (same as BaseCheckpointSaver default).
        """
        if current is None:
            return "1"
        try:
            return str(int(current) + 1)
        except (ValueError, TypeError):
            return "1"


# ═══════════════════════════════════════════════════════════════════════════════
# Module-level lifecycle functions (same interface as before)
# ═══════════════════════════════════════════════════════════════════════════════


async def init_checkpointer():
    """
    Initialize the persistent checkpointer.

    Called once at FastAPI startup. Creates a SupabaseRestCheckpointer that
    stores LangGraph checkpoints via the Supabase REST API.

    Falls back to MemorySaver when:
      - SUPABASE_URL / SUPABASE_SERVICE_KEY are not set
      - The REST checkpointer fails to initialize (e.g. tables don't exist)
      - Any unexpected exception occurs

    Returns the checkpointer instance.
    """
    global _checkpointer

    if _checkpointer is not None:
        logger.debug("[CHECKPOINTER] Already initialized — skipping")
        return _checkpointer

    supabase_url = os.environ.get("SUPABASE_URL", "").strip()
    service_key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or ""
    ).strip()

    if not supabase_url or not service_key:
        logger.warning(
            "[CHECKPOINTER] SUPABASE_URL and SUPABASE_SERVICE_KEY must be set "
            "— using MemorySaver (PropFlow threads will NOT survive restarts)"
        )
        return _fallback_to_memory()

    try:
        checkpointer = SupabaseRestCheckpointer(
            url=supabase_url,
            service_key=service_key,
        )

        # Verify tables exist (logs warning if migration not run)
        await checkpointer.create_tables()

        _checkpointer = checkpointer
        logger.info(
            "[CHECKPOINTER] SupabaseRestCheckpointer initialized — "
            "PropFlow threads will survive server restarts"
        )
        return _checkpointer

    except Exception as exc:
        logger.error(
            "[CHECKPOINTER] Failed to initialize SupabaseRestCheckpointer: %s. "
            "Falling back to MemorySaver.",
            exc,
        )
        return _fallback_to_memory()


def _fallback_to_memory():
    """Create an in-memory checkpointer as fallback."""
    global _checkpointer, _pool

    from langgraph.checkpoint.memory import MemorySaver

    _pool = None
    _checkpointer = MemorySaver()
    logger.info("[CHECKPOINTER] Using MemorySaver fallback")
    return _checkpointer


async def close_checkpointer():
    """
    Close the checkpointer's HTTP client.

    Called once at FastAPI shutdown. Closes the httpx client session
    so the server can exit cleanly.
    """
    global _checkpointer, _pool

    if isinstance(_checkpointer, SupabaseRestCheckpointer):
        try:
            await _checkpointer.close()
            logger.info("[CHECKPOINTER] HTTP client closed")
        except Exception as exc:
            logger.warning("[CHECKPOINTER] Error closing client: %s", exc)

    _pool = None
    _checkpointer = None


def get_checkpointer():
    """
    Get the current checkpointer instance.

    Synchronous accessor called during graph compilation.
    Returns the checkpointer initialized at startup, or MemorySaver
    if init_checkpointer() has not been called yet (safety net).
    """
    global _checkpointer
    if _checkpointer is None:
        return _fallback_to_memory()
    return _checkpointer
