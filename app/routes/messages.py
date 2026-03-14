"""
Messages routes -- NuloAfrica
ASCII only (Architecture Rule 17).
All Supabase calls in run_in_executor (Architecture Rule 6).
Named routes declared BEFORE wildcard /{id} routes (Architecture Rule 7).
Always supabase_admin -- never anon key (Architecture Rule 18).

Session 2026-03-12 fixes applied:
  FIX-1  asyncio.coroutine removed in Python 3.11 -- replaced with asyncio.sleep(0)
  FIX-2  N+1 unread count loop -- replaced with single batch query
  FIX-3  Wrong notification recipient in create_conversation (landlord self-notified)
  FIX-4  .single() data access bug in unarchive + delete (conv["data"] broken)
  FIX-5  All [DEBUG] print statements stripped from production code
  FIX-6  Role detection simplified -- single users table lookup, not 2 profile queries
  FIX-7  trust_score + phone_number added to partner SELECT in get_conversations
  FIX-8  pagination.total added to get_conversation_messages response
  FIX-9  last_message_sender_id kept in sync on send_message + create_conversation
         (requires migration 0001_messages_improvements.sql to be run first)
"""
import asyncio
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel

from app.database import supabase_admin
from app.middleware.auth import get_current_user

router = APIRouter(prefix="/messages")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _utcnow() -> str:
    """Current UTC time as ISO-8601 string for Supabase timestamptz columns."""
    return datetime.now(timezone.utc).isoformat()


async def _db(fn):
    """
    Run a synchronous Supabase call in the default executor so it does not
    block the async event loop (Architecture Rule 6).

    Usage:
        result = await _db(lambda: supabase_admin.table(...).execute())
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, fn)


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class ConversationCreate(BaseModel):
    """Start a new conversation -- or re-open an existing one -- for a property."""
    property_id: str
    landlord_id: str
    tenant_id: Optional[str] = None  # Required when landlord initiates
    initial_message: str


class MessageCreate(BaseModel):
    """Body for sending a single message inside an existing conversation."""
    content: str


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

async def _resolve_user_role(current_user: dict) -> str:
    """
    Resolve the caller's role as cheaply as possible.

    Priority:
      1. JWT claims already enriched by auth middleware (zero extra queries)
      2. Single SELECT on public.users which has an index on user_type

    FIX-6: replaced the original 2-sequential-query cascade that checked
    landlord_profiles then tenant_profiles (2 round-trips on every conversation
    create). public.users.user_type has idx_users_user_type and idx_users_type.
    """
    # Try what the middleware may have already put on the token
    role = (
        current_user.get("user_type")
        or current_user.get("role")
        or current_user.get("type")
    )
    if role:
        return role

    # One DB query -- indexed lookup
    try:
        resp = await _db(
            lambda: supabase_admin.table("users")
            .select("user_type")
            .eq("id", current_user["id"])
            .single()
            .execute()
        )
        if resp.data and resp.data.get("user_type"):
            return resp.data["user_type"]
    except Exception as e:
        print(f"[MESSAGES] _resolve_user_role failed: {e}")

    return "tenant"  # safe fallback -- tenant has fewer privileges


# ---------------------------------------------------------------------------
# Routes  (named / specific routes FIRST -- Rule 7)
# ---------------------------------------------------------------------------

@router.get("/unread-count")
async def get_unread_count(current_user: dict = Depends(get_current_user)):
    """
    Lightweight endpoint for the notification badge.
    Returns the total number of unread messages for the current user.
    Non-fatal: returns 0 on any error so the UI badge never breaks.
    """
    try:
        user_id = current_user["id"]
        result = await _db(
            lambda: supabase_admin.table("messages")
            .select("id", count="exact")
            .eq("recipient_id", user_id)
            .eq("read", False)
            .execute()
        )
        count = (result.count or 0) if hasattr(result, "count") else 0
        return {"success": True, "unread_count": count}
    except Exception as e:
        print(f"[MESSAGES] get_unread_count error: {e}")
        return {"success": True, "unread_count": 0}


@router.get("/conversations")
async def get_conversations(current_user: dict = Depends(get_current_user)):
    """
    Return all conversations for the current user, ordered by most recent message.

    Performance:
    - Fetches both sides (as tenant / as landlord) in parallel.
    - Batch-fetches all properties and partners in 2 queries.
    - FIX-2: Single batch unread query replaces N per-conversation COUNT queries.
    - FIX-7: trust_score + phone_number included in partner payload.
    """
    try:
        user_id = current_user["id"]

        # Fetch both sides in parallel
        tenant_resp, landlord_resp = await asyncio.gather(
            _db(lambda: supabase_admin.table("conversations")
                .select("*")
                .eq("tenant_id", user_id)
                .order("last_message_at", desc=True)
                .execute()),
            _db(lambda: supabase_admin.table("conversations")
                .select("*")
                .eq("landlord_id", user_id)
                .order("last_message_at", desc=True)
                .execute()),
        )

        # Deduplicate and sort
        seen: set = set()
        all_convs = []
        for conv in (tenant_resp.data or []) + (landlord_resp.data or []):
            if conv["id"] not in seen:
                all_convs.append(conv)
                seen.add(conv["id"])
        all_convs.sort(
            key=lambda x: x.get("last_message_at") or x.get("created_at") or "",
            reverse=True,
        )

        if not all_convs:
            return {"success": True, "conversations": []}

        # ── Batch fetch properties and partners ──────────────────────────
        property_ids = list({c["property_id"] for c in all_convs if c.get("property_id")})
        partner_ids = list(
            {
                c["landlord_id"] if c.get("tenant_id") == user_id else c.get("tenant_id")
                for c in all_convs
            } - {None, user_id}
        )

        # FIX-1: asyncio.coroutine was removed in Python 3.11.
        # Use asyncio.sleep(0) as a no-op awaitable placeholder when a batch
        # has nothing to fetch, so asyncio.gather always receives a coroutine.
        prop_fetch = (
            _db(lambda: supabase_admin.table("properties")
                .select("id, title, price, images, location")
                .in_("id", property_ids)
                .execute())
            if property_ids
            else asyncio.sleep(0)
        )

        # FIX-7: added trust_score, phone_number to the SELECT
        partner_fetch = (
            _db(lambda: supabase_admin.table("users")
                .select("id, full_name, first_name, avatar_url, verification_status, user_type, trust_score, phone_number")
                .in_("id", partner_ids)
                .execute())
            if partner_ids
            else asyncio.sleep(0)
        )

        prop_result, partner_result = await asyncio.gather(
            prop_fetch, partner_fetch, return_exceptions=True
        )

        prop_map: dict = {}
        partner_map: dict = {}

        if property_ids and not isinstance(prop_result, Exception) and prop_result:
            prop_map = {p["id"]: p for p in (prop_result.data or [])}
        if partner_ids and not isinstance(partner_result, Exception) and partner_result:
            partner_map = {u["id"]: u for u in (partner_result.data or [])}

        # ── FIX-2: Single batch unread count query ────────────────────────
        # Original code fired one COUNT(*) per conversation (N round-trips).
        # Now: fetch all unread message rows for this user across all
        # conversations in one query, then tally per-conversation in Python.
        conv_ids = [c["id"] for c in all_convs]
        unread_map: dict = {}
        try:
            unread_resp = await _db(
                lambda: supabase_admin.table("messages")
                .select("conversation_id")
                .eq("recipient_id", user_id)
                .eq("read", False)
                .in_("conversation_id", conv_ids)
                .execute()
            )
            for row in (unread_resp.data or []):
                cid = row["conversation_id"]
                unread_map[cid] = unread_map.get(cid, 0) + 1
        except Exception as unread_err:
            print(f"[MESSAGES] batch unread fetch failed, defaulting to 0: {unread_err}")

        # ── Build response ────────────────────────────────────────────────
        conversations = []
        for conv in all_convs:
            try:
                partner_id = (
                    conv["landlord_id"]
                    if conv.get("tenant_id") == user_id
                    else conv.get("tenant_id")
                )
                partner = partner_map.get(partner_id) if partner_id else None

                conversations.append({
                    "id": conv["id"],
                    "property": prop_map.get(conv.get("property_id")),
                    "partner": {
                        "id": partner["id"] if partner else partner_id,
                        "name": (
                            partner.get("full_name")
                            or partner.get("first_name")
                            or "User"
                        ) if partner else "User",
                        "avatar_url": partner.get("avatar_url") if partner else None,
                        "verified": (
                            partner.get("verification_status") == "approved"
                        ) if partner else False,
                        "user_type": partner.get("user_type") if partner else None,
                        # FIX-7: now available in the response
                        "trust_score": partner.get("trust_score") if partner else None,
                        "phone_number": partner.get("phone_number") if partner else None,
                    },
                    "last_message": conv.get("last_message"),
                    # FIX-9: expose last_message_sender_id (NULL until migration runs,
                    # then populated by send_message / create_conversation)
                    "last_message_sender_id": conv.get("last_message_sender_id"),
                    "last_message_at": conv.get("last_message_at") or conv.get("created_at"),
                    "unread_count": unread_map.get(conv["id"], 0),
                    "status": conv.get("status", "active"),
                    # Per-user archive flags (populated after migration runs)
                    "archived_by_landlord": conv.get("archived_by_landlord", False),
                    "archived_by_tenant": conv.get("archived_by_tenant", False),
                })
            except Exception as conv_err:
                print(f"[MESSAGES] Error processing conv {conv.get('id')}: {conv_err}")
                continue

        return {"success": True, "conversations": conversations}

    except Exception as e:
        import traceback
        print(f"[MESSAGES] get_conversations error: {e}\n{traceback.format_exc()}")
        return {"success": True, "conversations": [], "error": str(e)}


@router.post("/conversations")
async def create_conversation(
    data: ConversationCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    Find-or-create a conversation between tenant and landlord for a given property,
    then send the opening message. Works for both tenant and landlord initiators.

    Idempotent: calling twice for the same (tenant, landlord, property) triplet
    returns the existing conversation rather than creating a duplicate, thanks to
    the UNIQUE(tenant_id, landlord_id, property_id) DB constraint.

    FIX-5: All [DEBUG] prints removed.
    FIX-6: Role resolved via _resolve_user_role() -- single indexed users query.
    FIX-3: Notification now uses the correctly computed recipient_id, not
           data.landlord_id (which was the landlord's own ID when they initiate).
    FIX-9: last_message_sender_id kept in sync on conversation update.
    """
    try:
        current_user_id = current_user["id"]

        # FIX-6: one indexed query instead of 2 profile-table queries
        user_role = await _resolve_user_role(current_user)

        # Determine roles -- landlord initiates when they pass tenant_id
        if user_role == "landlord" and data.tenant_id:
            tenant_id = data.tenant_id
            landlord_id = current_user_id
            sender_id = landlord_id
            recipient_id = tenant_id
        elif user_role != "landlord" and not data.tenant_id:
            # Tenant initiates (original path)
            tenant_id = current_user_id
            landlord_id = data.landlord_id
            sender_id = tenant_id
            recipient_id = landlord_id
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "Invalid conversation creation request. "
                    "Landlords must provide tenant_id; tenants must not."
                ),
            )

        # Find-or-create conversation
        existing = await _db(
            lambda: supabase_admin.table("conversations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("landlord_id", landlord_id)
            .eq("property_id", data.property_id)
            .execute()
        )

        if existing.data:
            conversation_id = existing.data[0]["id"]
        else:
            conv_resp = await _db(
                lambda: supabase_admin.table("conversations").insert({
                    "tenant_id": tenant_id,
                    "landlord_id": landlord_id,
                    "property_id": data.property_id,
                    "status": "active",
                }).execute()
            )
            if not conv_resp.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Failed to create conversation",
                )
            conversation_id = conv_resp.data[0]["id"]

        # Send opening message
        now = _utcnow()
        msg_resp = await _db(
            lambda: supabase_admin.table("messages").insert({
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "content": data.initial_message,
                "property_id": data.property_id,
                "message_type": "text",
                "read": False,
            }).execute()
        )

        # Keep conversation summary in sync
        # FIX-9: also write last_message_sender_id (no-op until migration runs)
        await _db(
            lambda: supabase_admin.table("conversations").update({
                "last_message": data.initial_message,
                "last_message_sender_id": sender_id,
                "last_message_at": now,
                "updated_at": now,
            }).eq("id", conversation_id).execute()
        )

        # Notify recipient -- non-fatal
        # FIX-3: was data.landlord_id (landlord's own ID when they initiate)
        #        corrected to recipient_id (always the OTHER party)
        try:
            from app.services.notification_service import notify_new_message
            await notify_new_message(
                recipient_id=recipient_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                property_id=data.property_id,
                message_preview=data.initial_message[:100],
            )
        except Exception as notif_err:
            print(f"[MESSAGES] notify_new_message failed: {notif_err}")

        return {
            "success": True,
            "conversation_id": conversation_id,
            "message": msg_resp.data[0] if msg_resp.data else None,
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        print(f"[MESSAGES] create_conversation error: {e}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to create conversation: {e}",
        )


@router.get("/conversations/find")
async def find_conversation(
    property_id: str = Query(..., description="Property UUID"),
    partner_id: str = Query(..., description="The other participant's UUID"),
    current_user: dict = Depends(get_current_user),
):
    """
    Look up a conversation by property + partner without creating one.

    Used by 'Message about this application' and 'Message this tenant' CTAs so
    the frontend can deep-link directly to an existing thread instead of always
    calling POST /conversations and risk creating a duplicate.

    Returns { conversation: { id, status, last_message_at } } or { conversation: null }.

    FIX-5: [DEBUG] prints removed.
    """
    try:
        user_id = current_user["id"]

        as_tenant, as_landlord = await asyncio.gather(
            _db(lambda: supabase_admin.table("conversations")
                .select("id, status, last_message_at")
                .eq("tenant_id", user_id)
                .eq("landlord_id", partner_id)
                .eq("property_id", property_id)
                .execute()),
            _db(lambda: supabase_admin.table("conversations")
                .select("id, status, last_message_at")
                .eq("landlord_id", user_id)
                .eq("tenant_id", partner_id)
                .eq("property_id", property_id)
                .execute()),
        )

        found = (as_tenant.data or []) + (as_landlord.data or [])
        return {"conversation": found[0] if found else None}

    except Exception as e:
        print(f"[MESSAGES] find_conversation error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to find conversation: {e}",
        )


# Named archive sub-route declared BEFORE the wildcard /{conversation_id} read/send
# routes so FastAPI does not accidentally match 'archive' as a conversation_id.

@router.patch("/conversation/{conversation_id}/archive")
async def archive_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Soft-archive a conversation.

    Uses the shared status field for now.
    After migration 0001 runs, this will be upgraded to set per-user
    archived_by_landlord / archived_by_tenant flags instead (see HANDOFF.md).
    """
    try:
        user_id = current_user["id"]

        conv_resp = await _db(
            lambda: supabase_admin.table("conversations")
            .select("tenant_id, landlord_id")
            .eq("id", conversation_id)
            .execute()
        )
        if not conv_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        conv = conv_resp.data[0]
        if conv.get("tenant_id") != user_id and conv.get("landlord_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )

        await _db(
            lambda: supabase_admin.table("conversations").update({
                "status": "archived",
                "updated_at": _utcnow(),
            }).eq("id", conversation_id).execute()
        )
        return {"success": True, "message": "Conversation archived"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to archive conversation: {e}",
        )


@router.patch("/conversation/{conversation_id}/unarchive")
async def unarchive_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Unarchive a conversation.

    FIX-4: Original code used .single().execute() then accessed conv["data"]
    which is wrong -- .single() returns the row in .data directly on the
    APIResponse object, not wrapped in {"data": ...}. If no row is found,
    .single() raises rather than returning None. Fixed to use .execute()
    (returns a list) and check .data[0], matching archive_conversation style.
    """
    try:
        user_id = current_user["id"]

        conv_resp = await _db(
            lambda: supabase_admin.table("conversations")
            .select("tenant_id, landlord_id")
            .eq("id", conversation_id)
            .execute()
        )
        if not conv_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        conv = conv_resp.data[0]
        if conv.get("tenant_id") != user_id and conv.get("landlord_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )

        await _db(
            lambda: supabase_admin.table("conversations").update({
                "status": "active",
                "updated_at": _utcnow(),
            }).eq("id", conversation_id).execute()
        )
        return {"success": True, "message": "Conversation unarchived"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to unarchive conversation: {e}",
        )


@router.delete("/conversation/{conversation_id}")
async def delete_conversation(
    conversation_id: str,
    current_user: dict = Depends(get_current_user),
):
    """
    Delete a conversation permanently. Either participant may delete.
    Cascades to messages via FK constraint.

    FIX-4: Same .single() / conv["data"] bug fixed as in unarchive_conversation.
    """
    try:
        user_id = current_user["id"]

        conv_resp = await _db(
            lambda: supabase_admin.table("conversations")
            .select("tenant_id, landlord_id")
            .eq("id", conversation_id)
            .execute()
        )
        if not conv_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )

        conv = conv_resp.data[0]
        if conv.get("tenant_id") != user_id and conv.get("landlord_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )

        await _db(
            lambda: supabase_admin.table("conversations")
            .delete()
            .eq("id", conversation_id)
            .execute()
        )
        return {"success": True, "message": "Conversation deleted"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to delete conversation: {e}",
        )


# ---------------------------------------------------------------------------
# Wildcard routes last (Rule 7)
# ---------------------------------------------------------------------------

@router.get("/conversation/{conversation_id}")
async def get_conversation_messages(
    conversation_id: str,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    current_user: dict = Depends(get_current_user),
):
    """
    Fetch messages in a conversation with pagination.
    Batch-fetches all unique senders in a single query (was N+1).
    Marks all messages sent to the current user as read.
    Returns the conversation metadata alongside the messages.

    FIX-8: pagination now includes 'total' (exact count of messages in the
    conversation). Frontend no longer needs to guess whether more pages exist
    based on returned === limit (breaks when count is an exact multiple of limit).
    """
    try:
        user_id = current_user["id"]

        # Verify participation (15s cap -- Rule 16: all network calls must have timeout)
        conv_resp = await asyncio.wait_for(
            _db(
                lambda: supabase_admin.table("conversations")
                .select("*")
                .eq("id", conversation_id)
                .execute()
            ),
            timeout=15.0,
        )
        if not conv_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        conv = conv_resp.data[0]
        if conv.get("tenant_id") != user_id and conv.get("landlord_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )

        # FIX-8: fetch total count alongside the paginated messages in parallel
        msgs_fetch = _db(
            lambda: supabase_admin.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("timestamp", desc=False)
            .range(offset, offset + limit - 1)
            .execute()
        )
        count_fetch = _db(
            lambda: supabase_admin.table("messages")
            .select("id", count="exact")
            .eq("conversation_id", conversation_id)
            .execute()
        )

        msgs_resp, count_resp = await asyncio.gather(
            msgs_fetch, count_fetch, return_exceptions=True
        )

        messages_raw = msgs_resp.data if not isinstance(msgs_resp, Exception) else []
        total = (
            (count_resp.count or 0)
            if not isinstance(count_resp, Exception) and hasattr(count_resp, "count")
            else len(messages_raw)
        )

        # Batch-fetch sender profiles
        sender_ids = list({m["sender_id"] for m in messages_raw if m.get("sender_id")})
        sender_map: dict = {}
        if sender_ids:
            try:
                senders_resp = await asyncio.wait_for(
                    _db(
                        lambda: supabase_admin.table("users")
                        .select("id, full_name, first_name, avatar_url")
                        .in_("id", sender_ids)
                        .execute()
                    ),
                    timeout=15.0,
                )
                sender_map = {u["id"]: u for u in (senders_resp.data or [])}
            except Exception as sender_err:
                print(f"[MESSAGES] Failed to fetch sender profiles (non-fatal): {sender_err}")
                # sender_map stays empty -- messages still return, just without sender names

        messages = [
            {**m, "sender": sender_map.get(m.get("sender_id"))}
            for m in messages_raw
        ]

        # Mark incoming unread messages as read (non-fatal)
        try:
            now = _utcnow()
            await _db(
                lambda: supabase_admin.table("messages")
                .update({"read": True, "read_at": now})
                .eq("conversation_id", conversation_id)
                .eq("recipient_id", user_id)
                .eq("read", False)
                .execute()
            )
        except Exception as mark_err:
            print(f"[MESSAGES] Failed to mark messages read: {mark_err}")

        return {
            "success": True,
            "conversation": conv,
            "messages": messages,
            "pagination": {
                "limit": limit,
                "offset": offset,
                "returned": len(messages),
                "total": total,        # FIX-8: added
            },
        }

    except HTTPException:
        raise
    except Exception as e:
        print(f"[MESSAGES] get_conversation_messages error: {type(e).__name__}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch messages: {e}",
        )


@router.post("/conversation/{conversation_id}")
async def send_message(
    conversation_id: str,
    message_data: MessageCreate,
    current_user: dict = Depends(get_current_user),
):
    """
    Send a message in a conversation.
    Updates conversation last_message + updated_at.
    Fires a new_message in-app notification to the recipient (non-fatal).

    FIX-9: also keeps last_message_sender_id in sync.
    (Column is nullable -- write is a no-op if migration has not run yet,
    Supabase will silently ignore unknown columns only if using .update();
    the column MUST exist before this is deployed to production.)
    """
    try:
        sender_id = current_user["id"]

        conv_resp = await _db(
            lambda: supabase_admin.table("conversations")
            .select("*")
            .eq("id", conversation_id)
            .execute()
        )
        if not conv_resp.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conversation not found",
            )
        conv = conv_resp.data[0]
        if conv.get("tenant_id") != sender_id and conv.get("landlord_id") != sender_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )
        if conv.get("status") == "archived":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Cannot send messages in an archived conversation",
            )

        recipient_id = (
            conv["landlord_id"]
            if conv["tenant_id"] == sender_id
            else conv["tenant_id"]
        )
        now = _utcnow()

        # Insert message
        msg_resp = await _db(
            lambda: supabase_admin.table("messages").insert({
                "conversation_id": conversation_id,
                "sender_id": sender_id,
                "recipient_id": recipient_id,
                "content": message_data.content,
                "property_id": conv.get("property_id"),
                "message_type": "text",
                "read": False,
            }).execute()
        )
        if not msg_resp.data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to send message",
            )

        # Keep conversation summary in sync
        # FIX-9: also write last_message_sender_id
        await _db(
            lambda: supabase_admin.table("conversations").update({
                "last_message": message_data.content,
                "last_message_sender_id": sender_id,
                "last_message_at": now,
                "updated_at": now,
            }).eq("id", conversation_id).execute()
        )

        # Notify recipient -- non-fatal
        try:
            from app.services.notification_service import notify_new_message
            await notify_new_message(
                recipient_id=recipient_id,
                sender_id=sender_id,
                conversation_id=conversation_id,
                property_id=conv.get("property_id"),
                message_preview=message_data.content[:100],
            )
        except Exception as notif_err:
            print(f"[MESSAGES] notify_new_message failed: {notif_err}")

        return {"success": True, "message": msg_resp.data[0]}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to send message: {e}",
        )



