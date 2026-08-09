"""
Best-effort PropFlow graph synchronization.

The frontend drives the rental flow through REST endpoints (sign, simulate
payment, release) that are otherwise graph-agnostic. This module keeps the
LangGraph thread checkpoint in sync with those actions so that:

  - after both parties sign, the graph advances past INTERRUPT#3 and
    ``provision_nomba_dva`` actually runs (real or mock VA) — the agreement
    gets a ``virtual_account_number`` / ``expected_payment_amount`` from the
    provisioning path instead of the simulate-payment backfill;
  - a simulated payment flips the thread to ``payment_confirmed`` /
    ``FULL_PAYMENT``;
  - a completed release flips the thread to ``disbursement_complete``.

This keeps the chat stage mapping and any graph resume working against a
correct thread. Every function here is best-effort: failures are logged and
swallowed so the primary REST action is never broken by a graph hiccup.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)


def _thread_config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


async def resolve_thread_id(agreement_id: str, supabase_admin) -> str | None:
    """Find the PropFlow thread id for an agreement.

    1) ``agreements.propflow_thread_id`` (written by provision_nomba_dva)
    2) fallback: the linked application's ``propflow_thread_id``
    """
    try:
        result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin.table("agreements")
            .select("propflow_thread_id, application_id")
            .eq("id", str(agreement_id))
            .maybe_single()
            .execute(),
        )
        agreement = result.data if result else None
    except Exception as exc:
        logger.warning("[GRAPH SYNC] resolve thread failed for %s: %s", agreement_id, exc)
        return None

    if not agreement:
        return None
    if agreement.get("propflow_thread_id"):
        return agreement["propflow_thread_id"]

    app_id = agreement.get("application_id")
    if not app_id:
        return None
    try:
        app_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin.table("applications")
            .select("propflow_thread_id")
            .eq("id", str(app_id))
            .maybe_single()
            .execute(),
        )
        app_row = app_result.data if app_result else None
        return app_row.get("propflow_thread_id") if app_row else None
    except Exception as exc:
        logger.warning(
            "[GRAPH SYNC] resolve thread via application failed for %s: %s",
            agreement_id, exc,
        )
        return None


async def _read_thread(thread_id: str):
    """Return (graph, current_stage) for a thread, or (None, None)."""
    try:
        from app.propflow.graph import propflow_graph
        graph = propflow_graph()
        saved = await graph.checkpointer.aget_tuple(_thread_config(thread_id))
        if not saved:
            return None, None
        channel_values = saved.checkpoint.get("channel_values", {}) or {}
        return graph, channel_values.get("current_stage", "")
    except Exception as exc:
        logger.warning("[GRAPH SYNC] read stage failed for %s: %s", thread_id, exc)
        return None, None


async def advance_after_sign(agreement_id: str, supabase_admin) -> None:
    """After both parties have signed, resume the thread past the signing gate
    so ``provision_nomba_dva`` runs (mock NUBAN in demo mode). Best-effort.

    Only acts when the thread is actually paused at the signing gate, so a
    late/re-signed agreement never re-runs arbitrary graph nodes.
    """
    thread_id = await resolve_thread_id(agreement_id, supabase_admin)
    if not thread_id:
        return

    graph, stage = await _read_thread(thread_id)
    if graph is None:
        return

    if stage not in ("agreement_drafted", "awaiting_landlord_signature"):
        logger.info(
            "[GRAPH SYNC] sign advance skipped (stage=%r not a signing gate) for %s",
            stage, agreement_id,
        )
        return

    try:
        config = _thread_config(thread_id)
        await graph.aupdate_state(config, {"agreement_status": "SIGNED"})
        result = await graph.ainvoke(None, config=config)
        logger.info(
            "[GRAPH SYNC] advanced %s after sign → stage=%s",
            thread_id, result.get("current_stage", "?"),
        )
    except Exception as exc:
        logger.warning("[GRAPH SYNC] advance_after_sign failed for %s: %s", agreement_id, exc)


async def sync_after_payment(agreement_id: str, amount, supabase_admin) -> None:
    """Mark the thread as payment received (FULL_PAYMENT / payment_confirmed).

    Best-effort: the DB transfer row is the source of truth; this only keeps
    the thread's channel values consistent so a later resume/confirm works.
    """
    thread_id = await resolve_thread_id(agreement_id, supabase_admin)
    if not thread_id:
        return
    try:
        from app.propflow.graph import propflow_graph
        graph = propflow_graph()
        await graph.aupdate_state(_thread_config(thread_id), {
            "reconciliation_status": "FULL_PAYMENT",
            "total_received_amount": float(amount or 0),
            "current_stage": "payment_confirmed",
        })
        logger.info("[GRAPH SYNC] payment synced for %s → payment_confirmed", thread_id)
    except Exception as exc:
        logger.warning("[GRAPH SYNC] sync_after_payment failed for %s: %s", agreement_id, exc)


async def sync_after_release(agreement_id: str, supabase_admin) -> None:
    """Mark the thread disbursement_complete after a successful release.

    Best-effort: the transactions row is the source of truth.
    """
    thread_id = await resolve_thread_id(agreement_id, supabase_admin)
    if not thread_id:
        return
    try:
        from app.propflow.graph import propflow_graph
        graph = propflow_graph()
        await graph.aupdate_state(_thread_config(thread_id), {
            "current_stage": "disbursement_complete",
            "disbursement_status": "released",
        })
        logger.info("[GRAPH SYNC] release synced for %s → disbursement_complete", thread_id)
    except Exception as exc:
        logger.warning("[GRAPH SYNC] sync_after_release failed for %s: %s", agreement_id, exc)
