"""
Landing Subscribers Route
--------------------------
Handles email + intent capture from the landing-page welcome modal.
No authentication required — these are pre-registration leads.

Endpoints
---------
POST /api/v1/subscribers/landing   — subscribe with intent
GET  /api/v1/subscribers/stats     — admin-only aggregate counts
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr, field_validator
from typing import Literal, Optional
from datetime import datetime

from app.middleware.auth import get_current_user
from ..database import supabase_admin

router = APIRouter(prefix="/subscribers", tags=["Landing Subscribers"])


# ── Schemas ──────────────────────────────────────────────────────────────────

class LandingSubscribeRequest(BaseModel):
    email: EmailStr
    intent: Literal["renting", "landlord", "investing"]
    source: Optional[str] = "landing_modal"

    @field_validator("source")
    @classmethod
    def sanitise_source(cls, v: str) -> str:
        # Guard against excessively long or injected source strings
        return (v or "landing_modal")[:64]


class LandingSubscribeResponse(BaseModel):
    success: bool
    message: str
    already_subscribed: bool = False


# ── POST /subscribers/landing ─────────────────────────────────────────────────

@router.post("/landing", response_model=LandingSubscribeResponse)
async def subscribe_landing(payload: LandingSubscribeRequest):
    """
    Capture a visitor's email + intent from the landing-page welcome modal.

    - No auth required (open to anon visitors).
    - Duplicate (email + source) is silently treated as success so the
      frontend never shows an error to the visitor.
    - Returns 200 in all non-error cases so the modal can always close
      gracefully.
    """
    email = payload.email.lower().strip()
    intent = payload.intent
    source = payload.source or "landing_modal"

    try:
        # Check for existing subscription (email + source combo)
        existing = (
            supabase_admin
            .table("landing_subscribers")
            .select("id, intent")
            .eq("email", email)
            .eq("source", source)
            .maybe_single()
            .execute()
        )

        if existing.data:
            # Visitor already subscribed — update intent if it changed,
            # then return a soft success so the modal closes cleanly.
            existing_id = existing.data["id"]
            if existing.data.get("intent") != intent:
                supabase_admin.table("landing_subscribers").update(
                    {"intent": intent, "updated_at": datetime.utcnow().isoformat()}
                ).eq("id", existing_id).execute()

            print(f"[SUBSCRIBERS] Returning visitor re-subscribed: {email} intent={intent}")
            return LandingSubscribeResponse(
                success=True,
                message="You're already subscribed! We've updated your preferences.",
                already_subscribed=True,
            )

        # New subscription — insert row
        supabase_admin.table("landing_subscribers").insert({
            "email": email,
            "intent": intent,
            "source": source,
        }).execute()

        print(f"[SUBSCRIBERS] New subscriber: {email} intent={intent} source={source}")

        intent_labels = {
            "renting": "rental listings & tips",
            "landlord": "property management insights",
            "investing": "NEST investment updates",
        }
        topic = intent_labels.get(intent, "NuloAfrica updates")

        return LandingSubscribeResponse(
            success=True,
            message=f"Welcome! You'll now receive {topic} straight to your inbox.",
        )

    except Exception as exc:
        # Log the real error server-side but return a user-friendly message
        print(f"[SUBSCRIBERS] ❌ Error saving subscriber {email}: {exc}")
        raise HTTPException(
            status_code=500,
            detail="We couldn't save your subscription right now. Please try again shortly.",
        )


# ── GET /subscribers/stats  (admin only) ─────────────────────────────────────

@router.get("/stats")
async def get_subscriber_stats(current_user: dict = Depends(get_current_user)):
    """
    Return aggregate counts of landing subscribers grouped by intent.
    Admin access only.
    """
    if current_user.get("user_type") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")

    try:
        rows = (
            supabase_admin
            .table("landing_subscribers")
            .select("intent, source, created_at")
            .execute()
        )

        data = rows.data or []
        total = len(data)

        by_intent: dict = {"renting": 0, "landlord": 0, "investing": 0}
        by_source: dict = {}

        for row in data:
            intent_val = row.get("intent", "unknown")
            source_val = row.get("source", "unknown")
            by_intent[intent_val] = by_intent.get(intent_val, 0) + 1
            by_source[source_val] = by_source.get(source_val, 0) + 1

        return {
            "total_subscribers": total,
            "by_intent": by_intent,
            "by_source": by_source,
            "generated_at": datetime.utcnow().isoformat(),
        }

    except Exception as exc:
        print(f"[SUBSCRIBERS] ❌ Error fetching stats: {exc}")
        raise HTTPException(status_code=500, detail="Failed to retrieve subscriber stats.")
