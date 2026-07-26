"""
PropFlow Mem0 Service
Persistent cross-session memory for the PropFlow agent.

Architecture decision (hackathon):
  MEM0_MODE=local  -> in-process vector store, zero infra, works immediately
  MEM0_MODE=cloud  -> mem0.ai cloud, requires MEM0_API_KEY, better for prod

Memory namespaces used by PropFlow:
  user_id = str(tenant_id)    -> tenant preferences, past inquiries, outcomes
  user_id = "landlord_" + str(landlord_id)  -> landlord preferences, past approvals

What gets stored:
  - Tenant's preferred locations, property type, budget range (after extract_intent)
  - Screening outcome per tenant (after enrich_and_qualify)
  - Landlord approval patterns, preferred tenant profiles (after landlord approval)
  - Payment anomalies per tenant (after Nomba webhook)
"""

import logging
from typing import Any
from app.propflow.config import propflow_settings

logger = logging.getLogger(__name__)


def _build_mem0_client():
    """
    Build the Mem0 client based on MEM0_MODE config.
    Returns None if mem0ai is not installed (graceful degradation).
    """
    try:
        from mem0 import Memory, MemoryClient
    except ImportError:
        logger.warning(
            "mem0ai not installed. Run: pip install mem0ai>=0.1.0. "
            "PropFlow will run without persistent memory."
        )
        return None

    if not propflow_settings.ENABLE_MEM0_MEMORY:
        logger.info("Mem0 disabled via ENABLE_MEM0_MEMORY=False")
        return None

    if propflow_settings.MEM0_MODE == "cloud":
        if not propflow_settings.MEM0_API_KEY:
            logger.warning("MEM0_MODE=cloud but MEM0_API_KEY not set. Falling back to local.")
        else:
            logger.info("Mem0 initialised in CLOUD mode")
            return MemoryClient(api_key=propflow_settings.MEM0_API_KEY)

    # Default: local in-process memory
    logger.info("Mem0 initialised in LOCAL mode")
    config = {
        "vector_store": {
            "provider": "chroma",
            "config": {
                "collection_name": "propflow_memories",
                "path": propflow_settings.MEM0_LOCAL_PATH,
            },
        },
        "llm": {
            "provider": "openai",
            "config": {
                "api_key": propflow_settings.QWEN_API_KEY or "placeholder",
                "model": propflow_settings.QWEN_MODEL,
                "openai_base_url": propflow_settings.QWEN_API_URL,
            },
        },
        "embedder": {
            "provider": "openai",
            "config": {
                "api_key": propflow_settings.QWEN_API_KEY or "placeholder",
                "model": "text-embedding-v1",
                "openai_base_url": propflow_settings.QWEN_API_URL,
            },
        },
    }
    return Memory.from_config(config)


class Mem0Service:
    """
    Thin wrapper around Mem0 that adds:
    - Graceful degradation when mem0ai is not installed
    - Consistent user_id namespacing for tenants vs landlords
    - Structured logging on every read/write
    """

    def __init__(self):
        try:
            self._client = _build_mem0_client()
        except Exception as e:
            logger.warning(f"Mem0 client init failed: {e}")
            self._client = None
        self._available = self._client is not None

    @property
    def available(self) -> bool:
        return self._available

    # ── Tenant Memory ─────────────────────────────────────────────────────────

    def search_tenant_memories(self, tenant_id: str, query: str, limit: int = 5) -> list:
        """
        Retrieve relevant memories for a tenant before processing their inquiry.
        Called at the START of extract_intent to check if this is a returning tenant.

        Returns [] if Mem0 unavailable or no relevant memories exist.
        """
        if not self._available:
            return []
        try:
            results = self._client.search(
                query=query,
                user_id=str(tenant_id),
                limit=limit,
            )
            memories = results if isinstance(results, list) else results.get("results", [])
            logger.info(
                f"Mem0 tenant search: tenant={tenant_id[:8]}... "
                f"query='{query[:50]}' found={len(memories)}"
            )
            return memories
        except Exception as exc:
            logger.warning(f"Mem0 tenant search failed (non-fatal): {exc}")
            return []

    def add_tenant_memory(self, tenant_id: str, content: str, metadata: dict | None = None) -> bool:
        """
        Store a confirmed fact about a tenant after a node completes.
        Called AFTER extract_intent and AFTER enrich_and_qualify.

        Examples:
          - "Tenant prefers self-contain in VI, budget 500k/yr"
          - "Tenant passed screening on 2026-07-15, application approved"
          - "Tenant has history of quarterly payment preference"
        """
        if not self._available:
            return False
        try:
            self._client.add(
                content,
                user_id=str(tenant_id),
                metadata=metadata or {},
            )
            logger.info(f"Mem0 tenant memory stored: tenant={tenant_id[:8]}... '{content[:80]}'")
            return True
        except Exception as exc:
            logger.warning(f"Mem0 tenant add failed (non-fatal): {exc}")
            return False

    # ── Landlord Memory ───────────────────────────────────────────────────────

    def search_landlord_memories(self, landlord_id: str, query: str, limit: int = 5) -> list:
        """
        Retrieve landlord preferences before generating their briefing.
        Called at the START of enrich_and_qualify.

        Examples of stored landlord preferences:
          - "Landlord prefers tenants with formal employment"
          - "Landlord rejected 2 applications for late-income-proof submissions"
          - "Landlord approved quarterly payment tenants 3 times"
        """
        if not self._available:
            return []
        try:
            results = self._client.search(
                query=query,
                user_id=f"landlord_{landlord_id}",
                limit=limit,
            )
            memories = results if isinstance(results, list) else results.get("results", [])
            logger.info(
                f"Mem0 landlord search: landlord={landlord_id[:8]}... "
                f"found={len(memories)}"
            )
            return memories
        except Exception as exc:
            logger.warning(f"Mem0 landlord search failed (non-fatal): {exc}")
            return []

    def add_landlord_memory(self, landlord_id: str, content: str, metadata: dict | None = None) -> bool:
        """
        Store a confirmed fact about a landlord's behaviour.
        Called AFTER landlord approval decision is recorded.

        Examples:
          - "Landlord approved application from software engineer, Lagos, quarterly pay"
          - "Landlord rejected application citing insufficient proof of income"
        """
        if not self._available:
            return False
        try:
            self._client.add(
                content,
                user_id=f"landlord_{landlord_id}",
                metadata=metadata or {},
            )
            logger.info(f"Mem0 landlord memory stored: landlord={landlord_id[:8]}... '{content[:80]}'")
            return True
        except Exception as exc:
            logger.warning(f"Mem0 landlord add failed (non-fatal): {exc}")
            return False

    # ── Formatting helper ─────────────────────────────────────────────────────

    @staticmethod
    def format_memories_for_prompt(memories: list) -> str:
        """
        Convert a list of Mem0 memory objects into a plain-text block
        that can be injected into a Qwen system/user prompt.

        Returns empty string if no memories — callers don't need to branch.
        """
        if not memories:
            return ""
        lines = []
        for m in memories:
            # Mem0 returns either {"memory": "..."} or just a string
            text = m.get("memory", m) if isinstance(m, dict) else str(m)
            lines.append(f"- {text}")
        return "\n".join(lines)


# Singleton
mem0_service = Mem0Service()
