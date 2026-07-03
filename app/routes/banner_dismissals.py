"""
Banner Dismissals API
====================

Persistent server-side tracking of which dashboard banners a user has
dismissed. Replaces the old localStorage-based approach, which was per-device
and didn't survive across sessions or devices.

The frontend hits these endpoints:
    GET  /api/v1/banner-dismissals            → list all current dismissals
    POST /api/v1/banner-dismissals            → dismiss a banner (idempotent)
    POST /api/v1/banner-dismissals/check      → bulk check which banners are NOT dismissed
    DELETE /api/v1/banner-dismissals/{key}    → undismiss (used by QA / tests / re-engage flows)

Edge-case handling
------------------
Banners that depend on a rapidly-changing state (e.g. "Agreement Signed —
pay now!") can change their underlying data while the user is signed out.
To handle this, every dismissal carries a `status_hash` (SHA-256 of the
relevant state). When the frontend checks dismissals, it also sends the
current state hash for each candidate banner. If the hash mismatches the
stored one, the banner is treated as "not dismissed" again so the user
sees the new information.

That's what the `check` endpoint is for: it takes the current set of
candidate banners + their hashes and returns only the ones that should
actually be displayed.
"""

import hashlib
import logging
from datetime import datetime, timezone
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.database import supabase_admin
from app.middleware.auth import get_current_user

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/banner-dismissals", tags=["banner-dismissals"])


# ─── Pydantic models ───────────────────────────────────────────────────────────

class BannerDismissalCreate(BaseModel):
    banner_key:  str = Field(..., min_length=1, max_length=200)
    banner_type: str = Field(..., min_length=1, max_length=100)
    status_hash: str = Field(..., min_length=1, max_length=200)
    # If set, the dismissal auto-expires after this many seconds. Useful for
    # banners that should re-surface periodically (e.g. "viewing in 2 hours"
    # shouldn't be dismissed forever — it should come back next viewing).
    expires_in_seconds: Optional[int] = Field(None, ge=60, le=60 * 60 * 24 * 365)


class BannerDismissalItem(BaseModel):
    banner_key:  str
    banner_type: str
    status_hash: str
    dismissed_at: str
    expires_at:   Optional[str] = None


class BannerDismissalListResponse(BaseModel):
    dismissals: List[BannerDismissalItem]
    count:       int


class BannerCheckCandidate(BaseModel):
    banner_key:  str
    banner_type: str
    status_hash: str


class BannerCheckRequest(BaseModel):
    candidates: List[BannerCheckCandidate]


class BannerCheckResponse(BaseModel):
    # Banners from the candidate list that the user has NOT dismissed
    # (either never dismissed, or the stored status_hash no longer matches
    # the current one — meaning the banner state changed).
    visible: List[BannerCheckCandidate]
    # Banners the user has dismissed and the dismissal is still valid
    dismissed: List[BannerCheckCandidate]


class BannerDismissResponse(BaseModel):
    success: bool
    banner_key: str
    dismissed_at: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _supabase():
    """Get the service-role Supabase client. We use service-role here so the
    backend can read/upsert rows on behalf of the authenticated user without
    needing to impersonate them via JWT.
    """
    if supabase_admin is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    return supabase_admin


def _hash_status(payload: str) -> str:
    """Stable SHA-256 hex of a status payload. Frontend and backend must
    agree on exactly what gets fed in for the edge-case detection to work.
    """
    return hashlib.sha256(payload.strip().lower().encode("utf-8")).hexdigest()


# ─── Endpoints ────────────────────────────────────────────────────────────────

@router.get("", response_model=BannerDismissalListResponse)
async def list_dismissals(current_user: dict = Depends(get_current_user)):
    """Return every active dismissal for the current user.

    The frontend uses this on initial dashboard mount to filter out banners
    the user has previously dismissed. Expired dismissals are pruned
    opportunistically here so we don't return stale rows.
    """
    user = current_user
    sb = _supabase()

    try:
        # Opportunistic cleanup of expired dismissals for this user.
        sb.rpc("banner_dismissals_cleanup_expired").execute()

        result = (
            sb.table("banner_dismissals")
            .select("banner_key, banner_type, status_hash, dismissed_at, expires_at")
            .eq("user_id", user["id"])
            .execute()
        )

        items: List[BannerDismissalItem] = []
        for row in (result.data or []):
            items.append(
                BannerDismissalItem(
                    banner_key=row["banner_key"],
                    banner_type=row["banner_type"],
                    status_hash=row["status_hash"],
                    dismissed_at=row["dismissed_at"],
                    expires_at=row.get("expires_at"),
                )
            )

        return BannerDismissalListResponse(dismissals=items, count=len(items))

    except Exception as e:
        logger.exception("Failed to list banner dismissals: %s", e)
        raise HTTPException(status_code=500, detail="Failed to load dismissals")


@router.post("", response_model=BannerDismissResponse, status_code=201)
async def dismiss_banner(payload: BannerDismissalCreate, current_user: dict = Depends(get_current_user)):
    """Persist a dismissal. Idempotent — re-dismissing an already-dismissed
    banner updates the row instead of erroring.
    """
    user = current_user
    sb = _supabase()

    expires_at = None
    if payload.expires_in_seconds:
        from datetime import timedelta
        expires_at = (
            datetime.now(timezone.utc) + timedelta(seconds=payload.expires_in_seconds)
        ).isoformat()

    try:
        # Upsert — ON CONFLICT (user_id, banner_key) DO UPDATE
        sb.table("banner_dismissals").upsert(
            {
                "user_id":      user["id"],
                "banner_key":   payload.banner_key,
                "banner_type":  payload.banner_type,
                "status_hash":  payload.status_hash,
                "dismissed_at": datetime.now(timezone.utc).isoformat(),
                "expires_at":   expires_at,
            },
            on_conflict="user_id,banner_key",
        ).execute()

        return BannerDismissResponse(
            success=True,
            banner_key=payload.banner_key,
            dismissed_at=datetime.now(timezone.utc).isoformat(),
        )

    except Exception as e:
        logger.exception("Failed to dismiss banner: %s", e)
        raise HTTPException(status_code=500, detail="Failed to dismiss banner")


@router.post("/check", response_model=BannerCheckResponse)
async def check_dismissals(payload: BannerCheckRequest, current_user: dict = Depends(get_current_user)):
    """Bulk check: given a list of candidate banners (with current state
    hashes), return which ones the user has NOT dismissed AND which they
    HAVE dismissed. This is the main endpoint the dashboard hits on load.

    A banner is considered "dismissed" if:
      - A row exists for (user, banner_key), AND
      - The stored status_hash equals the current status_hash, AND
      - The dismissal has not expired.

    Otherwise it goes into "visible" — the user will see it again.
    """
    user = current_user
    sb = _supabase()

    if not payload.candidates:
        return BannerCheckResponse(visible=[], dismissed=[])

    candidate_keys = [c.banner_key for c in payload.candidates]
    candidates_by_key = {c.banner_key: c for c in payload.candidates}

    try:
        result = (
            sb.table("banner_dismissals")
            .select("banner_key, status_hash, expires_at")
            .eq("user_id", user["id"])
            .in_("banner_key", candidate_keys)
            .execute()
        )

        now = datetime.now(timezone.utc)
        visible:   List[BannerCheckCandidate] = []
        dismissed: List[BannerCheckCandidate] = []

        for row in (result.data or []):
            cand = candidates_by_key.get(row["banner_key"])
            if not cand:
                continue

            # Skip expired dismissals (they re-surface automatically)
            if row.get("expires_at"):
                try:
                    expires_at = datetime.fromisoformat(
                        row["expires_at"].replace("Z", "+00:00")
                    )
                    if expires_at < now:
                        visible.append(cand)
                        continue
                except ValueError:
                    pass

            # Status-hash mismatch means the banner state changed —
            # re-surface so the user sees the new information.
            if row["status_hash"] != cand.status_hash:
                visible.append(cand)
                continue

            dismissed.append(cand)

        # Anything not in the DB at all is, of course, visible
        seen_keys = {row["banner_key"] for row in (result.data or [])}
        for cand in payload.candidates:
            if cand.banner_key not in seen_keys:
                visible.append(cand)

        return BannerCheckResponse(visible=visible, dismissed=dismissed)

    except Exception as e:
        logger.exception("Failed to check banner dismissals: %s", e)
        # Fail open — if the DB call breaks, return all candidates as visible
        # so the user doesn't lose important notifications like a failed payment.
        return BannerCheckResponse(
            visible=payload.candidates,
            dismissed=[],
        )


@router.delete("/{banner_key}", status_code=204)
async def undismiss_banner(banner_key: str, current_user: dict = Depends(get_current_user)):
    """Remove a dismissal so the banner shows again. Useful for QA, for the
    're-engage me with these' settings option, or when a banner's underlying
    state changes and we want to clear stale dismissals en-masse.
    """
    user = current_user
    sb = _supabase()

    try:
        sb.table("banner_dismissals").delete().eq(
            "user_id", user["id"]
        ).eq("banner_key", banner_key).execute()
        return None
    except Exception as e:
        logger.exception("Failed to undismiss banner: %s", e)
        raise HTTPException(status_code=500, detail="Failed to undismiss banner")
