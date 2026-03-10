"""
Messages routes -- NuloAfrica
ASCII only (Architecture Rule 17).
All Supabase calls in run_in_executor (Architecture Rule 6).
Named routes declared BEFORE wildcard /{id} routes (Architecture Rule 7).
Always supabase_admin -- never anon key (Architecture Rule 18).
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
    initial_message: str


class MessageCreate(BaseModel):
    """Body for sending a single message inside an existing conversation."""
    content: str


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

    Fixes vs original:
    - Batch fetches properties and partners (was N+1 per conversation).
    - UTC timestamps.
    - conversations.updated_at touched on message send (separate endpoint).
    """
    try:
        user_id = current_user["id"]

        # Fetch both sides in parallel to avoid sequential round-trips
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

        # Batch fetch all properties and partners in 2 queries (not N+1)
        property_ids = list({c["property_id"] for c in all_convs if c.get("property_id")})
        partner_ids = list(
            {
                c["landlord_id"] if c.get("tenant_id") == user_id else c.get("tenant_id")
                for c in all_convs
            } - {None, user_id}
        )

        prop_map: dict = {}
        partner_map: dict = {}

        fetches = []
        if property_ids:
            fetches.append(
                _db(lambda: supabase_admin.table("properties")
                    .select("id, title, price, images, location")
                    .in_("id", property_ids)
                    .execute())
            )
        else:
            fetches.append(asyncio.coroutine(lambda: None)())  # placeholder

        if partner_ids:
            fetches.append(
                _db(lambda: supabase_admin.table("users")
                    .select("id, full_name, first_name, avatar_url, verification_status, user_type")
                    .in_("id", partner_ids)
                    .execute())
            )
        else:
            fetches.append(asyncio.coroutine(lambda: None)())

        results = await asyncio.gather(*fetches, return_exceptions=True)

        if property_ids and not isinstance(results[0], Exception) and results[0]:
            prop_map = {p["id"]: p for p in (results[0].data or [])}
        if partner_ids and not isinstance(results[1], Exception) and results[1]:
            partner_map = {u["id"]: u for u in (results[1].data or [])}

        # Build response -- unread count still requires one query per conversation;
        # this is acceptable for typical conversation counts (<50).
        # For scale: replace with a single GROUP BY RPC.
        conversations = []
        for conv in all_convs:
            try:
                partner_id = (
                    conv["landlord_id"]
                    if conv.get("tenant_id") == user_id
                    else conv.get("tenant_id")
                )
                partner = partner_map.get(partner_id) if partner_id else None

                cid = conv["id"]
                unread_resp = await _db(
                    lambda c=cid: supabase_admin.table("messages")
                    .select("id", count="exact")
                    .eq("conversation_id", c)
                    .eq("recipient_id", user_id)
                    .eq("read", False)
                    .execute()
                )
                unread = (
                    (unread_resp.count or 0)
                    if hasattr(unread_resp, "count")
                    else 0
                )

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
                    },
                    "last_message": conv.get("last_message"),
                    "last_message_at": conv.get("last_message_at") or conv.get("created_at"),
                    "unread_count": unread,
                    "status": conv.get("status", "active"),
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
    Find-or-create a conversation between the current tenant and a landlord
    for a given property, then send the opening message.

    Idempotent: calling twice for the same (tenant, landlord, property) triplet
    returns the existing conversation rather than creating a duplicate, thanks to
    the UNIQUE(tenant_id, landlord_id, property_id) DB constraint.
    """
    try:
        tenant_id = current_user["id"]

        # Check for existing conversation
        existing = await _db(
            lambda: supabase_admin.table("conversations")
            .select("id")
            .eq("tenant_id", tenant_id)
            .eq("landlord_id", data.landlord_id)
            .eq("property_id", data.property_id)
            .execute()
        )

        if existing.data:
            conversation_id = existing.data[0]["id"]
        else:
            conv_resp = await _db(
                lambda: supabase_admin.table("conversations").insert({
                    "tenant_id": tenant_id,
                    "landlord_id": data.landlord_id,
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

        # Send the opening message
        now = _utcnow()
        msg_resp = await _db(
            lambda: supabase_admin.table("messages").insert({
                "conversation_id": conversation_id,
                "sender_id": tenant_id,
                "recipient_id": data.landlord_id,
                "content": data.initial_message,
                "property_id": data.property_id,
                "message_type": "text",
                "read": False,
            }).execute()
        )

        # Keep conversation metadata in sync
        await _db(
            lambda: supabase_admin.table("conversations").update({
                "last_message": data.initial_message,
                "last_message_at": now,
                "updated_at": now,
            }).eq("id", conversation_id).execute()
        )

        # Notify the landlord -- non-fatal
        try:
            from app.services.notification_service import notify_new_message
            await notify_new_message(
                recipient_id=data.landlord_id,
                sender_id=tenant_id,
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
    """
    try:
        user_id = current_user["id"]

        # Current user might be either tenant or landlord side
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
        return {"success": True, "conversation": found[0] if found else None}

    except Exception as e:
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
    Soft-archive a conversation. Either participant may archive.
    The conversation record is kept; it just moves out of the active inbox.
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
    """
    try:
        user_id = current_user["id"]

        # Verify participation
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
        if conv.get("tenant_id") != user_id and conv.get("landlord_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Not a participant in this conversation",
            )

        # Fetch messages (paginated, oldest first for chronological display)
        msgs_resp = await _db(
            lambda: supabase_admin.table("messages")
            .select("*")
            .eq("conversation_id", conversation_id)
            .order("timestamp", desc=False)
            .range(offset, offset + limit - 1)
            .execute()
        )
        messages_raw = msgs_resp.data or []

        # Batch-fetch sender profiles
        sender_ids = list({m["sender_id"] for m in messages_raw if m.get("sender_id")})
        sender_map: dict = {}
        if sender_ids:
            senders_resp = await _db(
                lambda: supabase_admin.table("users")
                .select("id, full_name, first_name, avatar_url")
                .in_("id", sender_ids)
                .execute()
            )
            sender_map = {u["id"]: u for u in (senders_resp.data or [])}

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
            },
        }

    except HTTPException:
        raise
    except Exception as e:
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
    """
    try:
        sender_id = current_user["id"]

        # Verify conversation and participation
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

        # Keep conversation summary in sync (both timestamp fields)
        await _db(
            lambda: supabase_admin.table("conversations").update({
                "last_message": message_data.content,
                "last_message_at": now,
                "updated_at": now,
            }).eq("id", conversation_id).execute()
        )

        # Notify recipient -- non-fatal, wrapped in its own try/except
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