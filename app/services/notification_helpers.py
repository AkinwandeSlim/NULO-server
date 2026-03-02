"""
notification_helpers.py
========================
A single reusable helper for inserting in-app notifications.
Import this wherever you need to create a notification instead of
copy-pasting the try/except/retry block everywhere.

Usage:
    from app.services.notification_helpers import create_notification

    create_notification(
        user_id="abc-123",
        notif_type="visit",          # must match your DB check constraint
        title="Viewing Confirmed! ✓",
        message="Your viewing for ...",
        link="/tenant/viewings/xyz",
        data={"viewing_id": "xyz"},
    )
"""

import logging
import time
from datetime import datetime, timezone
from typing import Optional, Literal

from app.database import supabase_admin  # adjust import path if needed

logger = logging.getLogger(__name__)

# ── Valid types matching your DB check constraint ──────────────────────────────

NotifType = Literal[
    'signup',
    'email_verified',
    'phone_verified',
    'onboarding_submitted',
    'landlord_onboarding',        
    'verification_approved',
    'verification_rejected',
    'verification_needs_correction',
    'new_message',
    'message_read',
    'property_listed',
    'property_approved',
    'property_rejected',
    'viewing_requested',
    'viewing_approved',
    'viewing_rejected',
    'viewing_cancelled',
    'application_submitted',
    'application_approved',
    'application_rejected',
    'general',
    'admin_alert',
    'system',
    'visit',
    'message',
    'onboarding_approved',
    'onboarding_rejected',
    'onboarding_needs_correction'
]


def create_notification(
    *,
    user_id: str,
    notif_type: str,
    title: str,
    message: str,
    link: Optional[str] = None,
    data: Optional[dict] = None,
) -> bool:
    """
    Insert a single in-app notification row.

    Returns True on success, False on failure (never raises — so a broken
    notification never crashes the parent request).

    Retries once on any transient error (SSL timeout, connection reset, etc.)
    and also falls back to a payload without the metadata column if that
    column doesn't exist in the schema yet.
    """
    now = datetime.now(timezone.utc).isoformat()

    base_payload = {
        "user_id": user_id,
        "type": notif_type,
        "title": title,
        "message": message,
        "read": False,
        "link": link,
        "data": data or {},
        "created_at": now,
        "updated_at": now,
    }

    def _insert(payload: dict) -> bool:
        result = supabase_admin.table("notifications").insert(payload).execute()
        if result.data:
            logger.info(f"📲 [NOTIF] Created '{notif_type}' notification for user {user_id}")
            return True
        logger.warning(f"📲 [NOTIF] Insert returned no data for user {user_id}")
        return False

    # First attempt — with metadata column
    try:
        return _insert({**base_payload, "metadata": {"source": "system"}})

    except Exception as first_err:
        err_str = str(first_err)

        # If it's a missing-column error, retry without metadata (no delay needed)
        if "metadata" in err_str or "Could not find the 'metadata' column" in err_str:
            logger.warning("📲 [NOTIF] metadata column missing — retrying without it")
            try:
                return _insert(base_payload)
            except Exception as second_err:
                logger.error(f"📲 [NOTIF] Failed to create notification: {second_err}")
                return False

        # For transient errors (SSL timeout, connection reset, etc.) — wait briefly and retry once
        transient_keywords = ("ssl", "handshake", "timed out", "connection", "reset", "timeout", "eof")
        is_transient = any(kw in err_str.lower() for kw in transient_keywords)

        if is_transient:
            logger.warning(f"📲 [NOTIF] Transient error ({err_str[:80]}) — retrying in 1s")
            time.sleep(1)
            try:
                return _insert(base_payload)  # retry without metadata to keep it simple
            except Exception as retry_err:
                logger.error(f"📲 [NOTIF] Retry failed: {retry_err}")
                return False

        # Any other error — log and give up
        logger.error(f"📲 [NOTIF] Failed to create notification: {err_str}")
        return False