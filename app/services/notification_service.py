"""
Notification Service
====================
Central orchestrator for ALL notification channels.

WHAT IT DOES
------------
Each public method handles one lifecycle event and fires every
relevant channel in a single call:
  - Email  → delegates to email_service (existing, unchanged)
  - SMS    → delegates to sms_service   (existing, unchanged)
  - In-app → delegates to notification_helpers.create_notification

WHAT IT DOES NOT DO
-------------------
It does NOT own its own SMTP connection. email_service already
handles that properly (with Message-ID tracking, timeouts, etc.).
Duplicating SMTP here would mean two separate connections and two
different configs to maintain.

HOW TO USE IN A ROUTE
---------------------
    from app.services.notification_service import notification_service

    await notification_service.notify_viewing_created(
        viewing_id=viewing_id,
        property_title=property_title,
        date=request_data.preferred_date,
        time_slot=request_data.time_slot,
        tenant_id=tenant_data["id"],
        tenant_name=tenant_name,
        tenant_email=tenant_data.get("email"),
        tenant_phone=request_data.contact_number,
        landlord_id=landlord_data["id"],
        landlord_name=landlord_name,
        landlord_email=landlord_data.get("email"),
        landlord_phone=landlord_data.get("phone_number"),
    )

All methods are:
  - async (sync service calls wrapped in run_in_executor so
    they don't block FastAPI's event loop)
  - non-fatal (a failed email/SMS/DB write is logged, never raised)
"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

# ── Existing services — we delegate to these, never duplicate them ────────────
from app.services.email_service import email_service
from app.services.sms_service import sms_service

# ── In-app DB helper ──────────────────────────────────────────────────────────
from app.services.notification_helpers import create_notification

# ── DB client for admin user_id lookup ───────────────────────────────────────
from app.database import supabase_admin

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Internal helper: run a sync function without blocking the event loop
# ─────────────────────────────────────────────────────────────────────────────

async def _run(func, *args, **kwargs):
    """
    Run a synchronous function (email_service._send_email, sms_service.send_sms,
    etc.) in a thread pool so FastAPI's async event loop stays free.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, lambda: func(*args, **kwargs))



def _get_admin_user_id(admin_email: str) -> Optional[str]:
    """
    Look up the admin's user_id so we can create an in-app notification for them.

    WHY NOT get_current_admin?
    get_current_admin is a FastAPI Depends() — it works by reading a Bearer token
    from an incoming HTTP request. There is no request context here; this function
    is called from inside the notification service, which runs after the landlord's
    route has already done its work. Depends() simply cannot be called here.

    LOOKUP STRATEGY:
    auth.py shows there is both a `users` table (with user_type='admin') and a
    separate `admins` table. We use a two-step approach:
      1. Find the admin's id in the `users` table by email (most reliable — email
         is unique and always present).
      2. Confirm that id exists in the `admins` table (same check get_current_admin
         does), so we never send an in-app notif to a non-admin with that email.

    Returns None without raising if not found — a missing admin row must never
    crash a landlord's submission.
    """
    try:
        # Step 1: get user id by email
        user_result = supabase_admin.table("users").select("id").eq(
            "email", admin_email
        ).single().execute()

        if not user_result.data:
            logger.warning(f"⚠️ [NOTIF] No users row found for admin email {admin_email}")
            return None

        user_id = user_result.data["id"]

        # Step 2: confirm they're actually in the admins table
        admin_result = supabase_admin.table("admins").select("id").eq(
            "id", user_id
        ).execute()

        if not admin_result.data:
            logger.warning(
                f"⚠️ [NOTIF] User {admin_email} found in users table but not in admins table — "
                f"skipping in-app notification"
            )
            return None

        return user_id

    except Exception as e:
        logger.warning(f"⚠️ [NOTIF] Could not look up admin user_id: {e}")
        return None




# ─────────────────────────────────────────────────────────────────────────────
# NotificationService
# ─────────────────────────────────────────────────────────────────────────────

class NotificationService:

    def __init__(self) -> None:
        self.support_email = "nuloafrica26@outlook.com"

    @property
    def base_url(self) -> str:
        """
        Read BASE_URL fresh on every use instead of caching it at startup.

        FIX: The old code cached os.getenv("BASE_URL") in __init__, which meant
        the value was locked in at import time. If .env was updated and the
        server restarted, the new value was picked up — but the wrong DEFAULT
        "https://nulo-africa.vercel.app" was used when BASE_URL was missing.

        Now: reads live from env each time, falls back to localhost for local dev.
        In production, set BASE_URL=https://nulo-africa.vercel.app in your env.
        """
        return os.getenv("BASE_URL", "http://localhost:3000")

    @property
    def admin_email(self) -> str:
        """Read ADMIN_EMAIL fresh each time — same reason as base_url above."""
        return os.getenv("ADMIN_EMAIL", "nuloafrica26@outlook.com")

    # =========================================================================
    # VIEWING NOTIFICATIONS
    # =========================================================================

    async def notify_viewing_created(
        self,
        *,
        viewing_id: str,
        property_title: str,
        date: str,
        time_slot: str,
        # Tenant
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        # Landlord
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        landlord_phone: Optional[str],
    ) -> None:
        """
        Fire when a tenant submits a new viewing request.

        Channels fired:
          - Email to tenant   (send_viewing_confirmation_email)
          - Email to landlord (send_landlord_viewing_notification_email)
          - SMS  to tenant    (get_viewing_confirmation_message)
          - SMS  to landlord  (get_landlord_notification_message)
          - In-app for tenant  → "Viewing Request Sent"
          - In-app for landlord → "New Viewing Request"
        """
        if tenant_email:
            await _run(
                email_service.send_viewing_confirmation_email,
                tenant_email=tenant_email,
                tenant_name=tenant_name,
                property_title=property_title,
                date=date,
                time=time_slot,
                viewing_id=viewing_id,
            )

        if landlord_email:
            await _run(
                email_service.send_landlord_viewing_notification_email,
                landlord_email=landlord_email,
                landlord_name=landlord_name,
                tenant_name=tenant_name,
                property_title=property_title,
                date=date,
                time=time_slot,
                viewing_id=viewing_id,
            )

        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                sms_service.get_viewing_confirmation_message(
                    tenant_name=tenant_name,
                    property_title=property_title,
                    date_str=date,
                    time_slot=time_slot,
                ),
            )

        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                sms_service.get_landlord_notification_message(
                    landlord_name=landlord_name,
                    property_title=property_title,
                    tenant_name=tenant_name,
                    date_str=date,
                    time_slot=time_slot,
                ),
            )

        create_notification(
            user_id=tenant_id,
            notif_type="visit",
            title="Viewing Request Sent! ✓",
            message=(
                f"Your viewing request for {property_title} on {date} at {time_slot} "
                f"has been sent to the landlord. You'll be notified once they respond."
            ),
            link=f"/tenant/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "date": date, "time": time_slot},
        )

        create_notification(
            user_id=landlord_id,
            notif_type="visit",
            title="🔔 New Viewing Request",
            message=(
                f"{tenant_name} wants to view {property_title} on {date} at {time_slot}. "
                f"Tap to accept or decline."
            ),
            link=f"/landlord/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "tenant_name": tenant_name,
                  "date": date, "time": time_slot},
        )

        logger.info(f"✅ [NOTIF] notify_viewing_created done for {viewing_id}")

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_viewing_confirmed(
        self,
        *,
        viewing_id: str,
        property_title: str,
        date: str,
        time_slot: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        landlord_phone: Optional[str],
    ) -> None:
        """Fire when a landlord confirms a viewing."""
        if tenant_email:
            await _run(
                email_service.send_viewing_confirmation_email,
                tenant_email=tenant_email,
                tenant_name=tenant_name,
                property_title=property_title,
                date=date,
                time=time_slot,
                viewing_id=viewing_id,
            )

        if landlord_email:
            await _run(
                email_service.send_landlord_viewing_notification_email,
                landlord_email=landlord_email,
                landlord_name=landlord_name,
                tenant_name=tenant_name,
                property_title=property_title,
                date=date,
                time=time_slot,
                viewing_id=viewing_id,
            )

        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                sms_service.get_viewing_confirmation_message(
                    tenant_name=tenant_name,
                    property_title=property_title,
                    date_str=date,
                    time_slot=time_slot,
                ),
            )

        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                sms_service.get_landlord_notification_message(
                    landlord_name=landlord_name,
                    property_title=property_title,
                    tenant_name=tenant_name,
                    date_str=date,
                    time_slot=time_slot,
                ),
            )

        create_notification(
            user_id=tenant_id,
            notif_type="visit",
            title="Viewing Confirmed! ✓",
            message=(
                f"Your viewing for {property_title} on {date} at {time_slot} "
                f"has been confirmed. Please arrive on time."
            ),
            link=f"/tenant/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "date": date, "time": time_slot},
        )

        create_notification(
            user_id=landlord_id,
            notif_type="visit",
            title="Viewing Scheduled",
            message=(
                f"{tenant_name} has a confirmed viewing for {property_title} "
                f"on {date} at {time_slot}."
            ),
            link=f"/landlord/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "tenant_name": tenant_name,
                  "date": date, "time": time_slot},
        )

        logger.info(f"✅ [NOTIF] notify_viewing_confirmed done for {viewing_id}")

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_viewing_reminder(
        self,
        *,
        viewing_id: str,
        property_title: str,
        date: str,
        time_slot: str,
        hours: int,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
    ) -> None:
        """Fire 24h and 1h reminders to the tenant only."""
        if tenant_email:
            await _run(
                email_service.send_viewing_reminder_email,
                tenant_email=tenant_email,
                tenant_name=tenant_name,
                property_title=property_title,
                date=date,
                time=time_slot,
                hours_until=hours,
                viewing_id=viewing_id,
            )

        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                sms_service.get_reminder_message(
                    tenant_name=tenant_name,
                    property_title=property_title,
                    hours_before=hours,
                ),
            )

        create_notification(
            user_id=tenant_id,
            notif_type="visit",
            title=f"⏰ Viewing Reminder — {'1 hour' if hours == 1 else '24 hours'}",
            message=(
                f"Your viewing for {property_title} is in "
                f"{'1 hour' if hours == 1 else '24 hours'}. "
                f"Date: {date} at {time_slot}."
            ),
            link=f"/tenant/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "hours_until": hours},
        )

        logger.info(f"✅ [NOTIF] notify_viewing_reminder ({hours}h) done for {viewing_id}")

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_viewing_interest(
        self,
        *,
        viewing_id: str,
        property_title: str,
        tenant_name: str,
        landlord_id: str,
        landlord_name: str,
        landlord_phone: Optional[str],
    ) -> None:
        """Fire when a tenant expresses interest. SMS + in-app to landlord only."""
        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                sms_service.get_interest_notification_message(
                    landlord_name=landlord_name,
                    tenant_name=tenant_name,
                    property_title=property_title,
                ),
            )

        create_notification(
            user_id=landlord_id,
            notif_type="visit",
            title="🔥 New Tenant Interest",
            message=(
                f"{tenant_name} is interested in {property_title}. "
                f"Review their profile and respond."
            ),
            link=f"/landlord/viewings/{viewing_id}",
            data={"viewing_id": viewing_id, "tenant_name": tenant_name},
        )

        logger.info(f"✅ [NOTIF] notify_viewing_interest done for {viewing_id}")

    # =========================================================================
    # SIGNUP NOTIFICATIONS
    # =========================================================================

    async def notify_signup(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        user_type: str = "tenant",
    ) -> None:
        """
        Fire immediately after account creation (email or OAuth).

        Called from:
          - route.ts  → Google OAuth new users (both landlord + tenant)
          - AuthContext.signUpTenant / signUpLandlord → manual email signup

        Channels:
          - Welcome email (tenant-specific or landlord-specific copy)
          - In-app notification (type: "system")
        """
        is_landlord = user_type == "landlord"

        subject = (
            "Welcome to NuloAfrica — Start Your Landlord Journey"
            if is_landlord
            else "Welcome to NuloAfrica — Find Your Perfect Home"
        )
        next_step = (
            "Complete your 5-step onboarding to get verified and start listing properties."
            if is_landlord
            else "Complete your profile to start browsing verified properties."
        )
        next_url = (
            f"{self.base_url}/onboarding/landlord/step-1"
            if is_landlord
            else f"{self.base_url}/onboarding/tenant/step-1"
        )
        next_link = (
            "/onboarding/landlord/step-1"
            if is_landlord
            else "/onboarding/tenant/step-1"
        )

        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                subject,
                _html_welcome(user_name, next_step, next_url, self.support_email, is_landlord),
                f"Welcome to NuloAfrica, {user_name}! {next_step}",
            )

        create_notification(
            user_id=user_id,
            notif_type="system",
            title="👋 Welcome to NuloAfrica!",
            message=(
                f"Welcome, {user_name}! "
                + (
                    "Your landlord account is ready. Complete your onboarding to get verified."
                    if is_landlord
                    else "Your account is ready. Complete your profile to start browsing properties."
                )
            ),
            link=next_link,
        )

        logger.info(f"✅ [NOTIF] notify_signup done for {user_type} user {user_id}")

    # =========================================================================
    # ONBOARDING / VERIFICATION NOTIFICATIONS
    # =========================================================================

    async def notify_onboarding_submitted(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        onboarding_id: str,
    ) -> None:
        """Fire when a landlord submits all steps for admin review."""
        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                "Verification Submitted — We'll Review Your Documents",
                _html_onboarding_submitted(user_name, self.base_url, self.support_email),
                f"Hi {user_name}, your verification has been submitted. Expected review: 24–48 hours.",
            )

        create_notification(
            user_id=user_id,
            notif_type="onboarding_submitted",
            title="Account Verification Submitted! ⏳",
            message=(
                "Your landlord account verification  has been submitted. "
                "Our team will review it within 24–48 hours. "
                "You'll be notified once a decision is made."
            ),
            link="/landlord/overview",
        )

        logger.info(f"✅ [NOTIF] notify_onboarding_submitted done for user {user_id}")

    async def notify_admin_new_submission(
        self,
        *,
        admin_email: str,
        landlord_name: str,
        landlord_email: str,
        onboarding_id: str,
    ) -> None:
        """
        Alert admin when a landlord submits for review.
        Fires: email to admin + in-app notification for admin.

        FIX: Previously only sent email. Added in-app notification.
        The admin in-app notification requires a user_id (UUID), so we
        look up the admin's user_id from the users table by their email.
        """
        if admin_email:
            submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            await _run(
                email_service._send_email,
                admin_email,
                f"🔔 New Landlord Verification: {landlord_name}",
                _html_admin_new_submission(
                    landlord_name, landlord_email, onboarding_id,
                    submitted_at, self.base_url
                ),
                f"New landlord submission: {landlord_name} ({landlord_email}). "
                f"Review at {self.base_url}/admin/onboarding/queue",
            )

        # ── In-app notification for admin ─────────────────────────────────────
        # Look up admin's user_id by their email so create_notification can
        # insert the row correctly. If not found, skip silently — never crash.
        admin_user_id = _get_admin_user_id(admin_email)
        if admin_user_id:
            create_notification(
                user_id=admin_user_id,
                notif_type="system",
                title="🔔 New Landlord Submission",
                message=(
                    f"{landlord_name} ({landlord_email}) has submitted their landlord "
                    f"verification application and is awaiting your review."
                ),
                link=f"/admin/onboarding/details/{onboarding_id}",
                data={
                    "onboarding_id": onboarding_id,
                    "landlord_name": landlord_name,
                    "landlord_email": landlord_email,
                },
            )
        else:
            logger.warning(
                f"⚠️ [NOTIF] Skipped admin in-app notification — no user row found "
                f"for {admin_email}. Make sure the admin has a row in the users table."
            )

        logger.info(f"✅ [NOTIF] notify_admin_new_submission done for {landlord_name}")

    async def notify_verification_approved(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        trust_score: int = 100,
    ) -> None:
        """Fire when admin approves a landlord."""
        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                f"🎉 Verification Approved! Your Trust Score is {trust_score}%",
                _html_verification_approved(user_name, trust_score, self.base_url, self.support_email),
                f"Congratulations {user_name}! Your verification has been approved. Trust score: {trust_score}%",
            )

        create_notification(
            user_id=user_id,
            notif_type="onboarding_approved",
            title="🎉 You're Verified!",
            message=(
                "Congratulations! Your landlord account has been verified. "
                "You can now list properties and start receiving tenant inquiries."
            ),
            link="/landlord/overview",
        )

        logger.info(f"✅ [NOTIF] notify_verification_approved done for user {user_id}")

    async def notify_verification_rejected(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        rejection_reason: str,
        onboarding_id: str,
    ) -> None:
        """Fire when admin rejects a landlord."""
        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                "Verification Update — Action Required",
                _html_verification_rejected(user_name, rejection_reason, self.base_url, self.support_email),
                f"Hi {user_name}, your verification was not successful. Reason: {rejection_reason}",
            )

        create_notification(
            user_id=user_id,
            notif_type="onboarding_rejected",
            title="Verification Unsuccessful",
            message=(
                f"Unfortunately your verification was not successful. "
                f"Reason: {rejection_reason} Contact support if you need help."
            ),
            link="/onboarding/landlord/step-1",
        )

        logger.info(f"✅ [NOTIF] notify_verification_rejected done for user {user_id}")

    async def notify_verification_needs_correction(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        admin_feedback: str,
        onboarding_id: str,
    ) -> None:
        """Fire when admin requests corrections."""
        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                "Action Required — Update Your Verification Application",
                _html_needs_correction(user_name, admin_feedback, self.base_url, self.support_email),
                f"Hi {user_name}, your application needs corrections. Admin note: {admin_feedback}",
            )

        create_notification(
            user_id=user_id,
            notif_type="onboarding_needs_correction",
            title="Action Required: Update Your Application",
            message=(
                f"Your application needs corrections before it can be approved. "
                f"Admin note: {admin_feedback} Please log in and update the information."
            ),
            link="/onboarding/landlord/step-1",
        )

        logger.info(f"✅ [NOTIF] notify_verification_needs_correction done for user {user_id}")

    async def notify_email_verified(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        user_type: str = "landlord",
    ) -> None:
        """Fire after a user clicks the email verification link."""
        link = (
            "/onboarding/landlord/step-1"
            if user_type == "landlord"
            else "/onboarding/tenant/step-1"
        )
        next_label = (
            "Complete your 5-step onboarding to get verified and start listing properties."
            if user_type == "landlord"
            else "Complete your profile to start browsing verified properties."
        )

        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                "✅ Email Verified — Next Steps",
                _html_email_verified(user_name, next_label, f"{self.base_url}{link}", self.support_email),
                f"Hi {user_name}, your email has been verified. {next_label}",
            )

        create_notification(
            user_id=user_id,
            notif_type="email_verified",
            title="🎉 Email Verified!",
            message=f"Your email has been confirmed. {next_label}",
            link=link,
        )

        logger.info(f"✅ [NOTIF] notify_email_verified done for user {user_id}")

    async def notify_document_processing_failed(
        self,
        *,
        user_id: str,
        user_email: str,
        user_name: str,
        document_type: str,
        error_message: str,
    ) -> None:
        """Fire when an uploaded document fails processing."""
        if user_email:
            await _run(
                email_service._send_email,
                user_email,
                f"Document Processing Issue — {document_type}",
                _html_document_failed(user_name, document_type, error_message, self.base_url, self.support_email),
                f"Hi {user_name}, there was a problem processing your {document_type}. Error: {error_message}",
            )

        create_notification(
            user_id=user_id,
            notif_type="system",
            title="⚠️ Document Issue",
            message=(
                f"There was a problem processing your {document_type}. "
                f"Please re-upload it. If the problem persists, contact support."
            ),
            link="/onboarding/landlord/step-1",
        )

        logger.info(f"✅ [NOTIF] notify_document_processing_failed done for user {user_id}")

    # =========================================================================
    # PROPERTY NOTIFICATIONS
    # =========================================================================

    async def notify_property_listed(
        self,
        *,
        property_id: str,
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        property_title: str,
    ) -> None:
        """
        Fire when a landlord submits a new property listing.

        Channels fired:
          - Email to landlord  → "Property under review, expect 24h"
          - In-app for landlord → type=property_listed
          - Email to admin     → "New listing needs review"
          - In-app for admin   → type=property_listed
        """
        # ── Email + in-app → landlord ─────────────────────────────────────────
        if landlord_email:
            await _run(
                email_service._send_email,
                landlord_email,
                "Property Submitted — Under Review",
                _html_property_listed(landlord_name, property_title, self.base_url, self.support_email),
                (
                    f"Hi {landlord_name}, your property '{property_title}' has been submitted "
                    f"and is now under review. Expected decision: 24 hours."
                ),
            )

        create_notification(
            user_id=landlord_id,
            notif_type="property_listed",
            title="🏠 Property Submitted for Review",
            message=(
                f"Your property '{property_title}' has been submitted and is under review. "
                f"Our team will assess it within 24 hours. You'll be notified once approved."
            ),
            link=f"/landlord/properties/{property_id}",
            data={"property_id": property_id, "property_title": property_title},
        )

        # ── Email + in-app → admin ────────────────────────────────────────────
        admin_email = self.admin_email
        submitted_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

        if admin_email:
            await _run(
                email_service._send_email,
                admin_email,
                f"🔔 New Property Listing: {property_title}",
                _html_admin_property_listed(
                    landlord_name, landlord_email or "", property_title,
                    property_id, submitted_at, self.base_url,
                ),
                (
                    f"New property listing from {landlord_name}: '{property_title}'. "
                    f"Review at {self.base_url}/admin/property-verification"
                ),
            )

        admin_user_id = _get_admin_user_id(admin_email)
        if admin_user_id:
            create_notification(
                user_id=admin_user_id,
                notif_type="property_listed",
                title="🔔 New Property Listing Submitted",
                message=(
                    f"{landlord_name} has submitted a new property listing: '{property_title}'. "
                    f"It is awaiting your review."
                ),
                link=f"/admin/property-verification",
                data={
                    "property_id": property_id,
                    "property_title": property_title,
                    "landlord_name": landlord_name,
                    "landlord_email": landlord_email or "",
                },
            )
        else:
            logger.warning(
                f"⚠️ [NOTIF] Skipped admin in-app notification for property_listed — "
                f"no user row found for {admin_email}."
            )

        logger.info(f"✅ [NOTIF] notify_property_listed done for property {property_id}")

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_property_reviewed(
        self,
        *,
        property_id: str,
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        property_title: str,
        action: str,
        rejection_reason: Optional[str] = None,
    ) -> None:
        """
        Fire when admin approves or rejects a property listing.

        action must be one of: 'approved', 'rejected'

        Channels fired:
          - Email to landlord  → approval or rejection copy
          - In-app for landlord → type=property_approved OR property_rejected
        """
        is_approved = action == "approved"
        notif_type = "property_approved" if is_approved else "property_rejected"

        if landlord_email:
            if is_approved:
                await _run(
                    email_service._send_email,
                    landlord_email,
                    f"🎉 Property Approved — '{property_title}' is Now Live",
                    _html_property_approved(
                        landlord_name, property_title, property_id,
                        self.base_url, self.support_email,
                    ),
                    (
                        f"Congratulations {landlord_name}! Your property '{property_title}' "
                        f"has been approved and is now visible on the marketplace."
                    ),
                )
            else:
                reason = rejection_reason or "Please contact support for details."
                await _run(
                    email_service._send_email,
                    landlord_email,
                    f"Property Listing Update — '{property_title}'",
                    _html_property_rejected(
                        landlord_name, property_title, reason,
                        self.base_url, self.support_email,
                    ),
                    (
                        f"Hi {landlord_name}, your property '{property_title}' was not approved. "
                        f"Reason: {reason}"
                    ),
                )

        if is_approved:
            create_notification(
                user_id=landlord_id,
                notif_type="property_approved",
                title="🎉 Property Approved!",
                message=(
                    f"Your property '{property_title}' has been approved and is now live "
                    f"on the marketplace. Tenants can now find and apply for it."
                ),
                link=f"/landlord/properties/{property_id}",
                data={"property_id": property_id, "property_title": property_title},
            )
        else:
            reason = rejection_reason or "Please contact support for details."
            create_notification(
                user_id=landlord_id,
                notif_type="property_rejected",
                title="Property Listing Not Approved",
                message=(
                    f"Your property '{property_title}' was not approved. "
                    f"Reason: {reason} Please review and resubmit."
                ),
                link=f"/landlord/properties/{property_id}",
                data={
                    "property_id": property_id,
                    "property_title": property_title,
                    "rejection_reason": reason,
                },
            )

        logger.info(
            f"✅ [NOTIF] notify_property_reviewed done — {action} for property {property_id}"
        )

    # APPLICATION NOTIFICATIONS
    # =========================================================================

    async def notify_application_submitted(
        self,
        *,
        application_id: str,
        property_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        landlord_phone: Optional[str],
        monthly_income: Optional[int] = None,
        employment_status: Optional[str] = None,
        message: Optional[str] = None,
    ):
        """Notify landlord when a tenant submits an application"""
        logger.info(f"📧 [NOTIF] notify_application_submitted for application {application_id}")

        # Email to landlord
        if landlord_email:
            await _run(
                email_service._send_email,
                landlord_email,
                f"📋 New Application Received — '{property_title}'",
                _html_application_submitted(
                    landlord_name,
                    property_title,
                    tenant_name,
                    monthly_income,
                    employment_status,
                    message,
                    self.base_url,
                ),
                (
                    f"Hi {landlord_name}, you have received a new rental application "
                    f"for '{property_title}' from {tenant_name}. "
                    f"Log in to review the application details."
                ),
            )

        # SMS to landlord (if available)
        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                f"NuloAfrica: New application from {tenant_name} for '{property_title}'. "
                f"Log in to review: {self.base_url}/landlord/applications",
            )

        # In-app notification to landlord
        notification_message = (
            f"You have received a new rental application for '{property_title}' "
            f"from {tenant_name}. Click to review and respond."
        )
        
        logger.info(f"� [NOTIF] Creating notification with message: {notification_message}")
        
        create_notification(
            user_id=landlord_id,
            notif_type="application_submitted",
            title="📋 New Application Received",
            message=notification_message,
            link=f"/landlord/applications/{application_id}",
            data={
                "application_id": application_id,
                "property_id": property_id,
                "property_title": property_title,
                "tenant_name": tenant_name,
                "tenant_id": tenant_id,
            },
        )

        logger.info(
            f"✅ [NOTIF] notify_application_submitted done for application {application_id}"
        )

    async def notify_application_approved(
        self,
        *,
        application_id: str,
        property_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        landlord_name: str,
    ):
        """Notify tenant when their application is approved"""
        logger.info(f"📧 [NOTIF] notify_application_approved for application {application_id}")

        # Email to tenant
        if tenant_email:
            await _run(
                email_service._send_email,
                tenant_email,
                "🎉 Your Application Was Approved!",
                _html_application_approved(
                    tenant_name,
                    property_title,
                    landlord_name,
                    self.base_url,
                ),
                (
                    f"Hi {tenant_name}, congratulations! Your application for '{property_title}' "
                    f"has been approved by the landlord. Log in to view details."
                ),
            )

        # SMS to tenant (if available)
        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                f"NuloAfrica: Your application for '{property_title}' has been approved! "
                f"Log in to view details: {self.base_url}/tenant/applications/{application_id}",
            )

        # In-app notification to tenant
        notification_message = (
            f"Your application for '{property_title}' has been approved by the landlord!"
        )

        logger.info(f"📧 [NOTIF] Creating in-app notification: {notification_message}")

        create_notification(
            user_id=tenant_id,
            notif_type="application_approved",
            title="🎉 Application Approved",
            message=notification_message,
            link=f"/tenant/applications/{application_id}",
            data={
                "application_id": application_id,
                "property_id": property_id,
                "property_title": property_title,
            },
        )

        logger.info(
            f"✅ [NOTIF] notify_application_approved done for application {application_id}"
        )

    async def notify_application_rejected(
        self,
        *,
        application_id: str,
        property_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        rejection_reason: str,
    ):
        """Notify tenant when their application is rejected"""
        logger.info(f"📧 [NOTIF] notify_application_rejected for application {application_id}")

        # Email to tenant
        if tenant_email:
            await _run(
                email_service._send_email,
                tenant_email,
                f"Application Update — {property_title}",
                _html_application_rejected(
                    tenant_name,
                    property_title,
                    rejection_reason,
                    self.base_url,
                ),
                (
                    f"Hi {tenant_name}, your application for '{property_title}' was not approved. "
                    f"Keep browsing and apply for other properties you like!"
                ),
            )

        # SMS to tenant (if available)
        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                f"NuloAfrica: Your application for '{property_title}' was not approved. "
                f"Browse more properties: {self.base_url}/properties",
            )

        # In-app notification to tenant
        notification_message = (
            f"Your application for '{property_title}' was not approved. Keep exploring other properties!"
        )

        logger.info(f"📧 [NOTIF] Creating in-app rejection notification: {notification_message}")

        create_notification(
            user_id=tenant_id,
            notif_type="application_rejected",
            title="Application Update",
            message=notification_message,
            link=f"/tenant/applications/{application_id}",
            data={
                "application_id": application_id,
                "property_id": property_id,
                "property_title": property_title,
                "rejection_reason": rejection_reason,
            },
        )

        logger.info(
            f"✅ [NOTIF] notify_application_rejected done for application {application_id}"
        )

    async def notify_agreement_created(
        self,
        agreement_id: str,
        application_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: str,
        tenant_phone: Optional[str],
        landlord_id: str,
        landlord_name: str,
        landlord_email: str,
        landlord_phone: Optional[str],
    ):
        """
        Fire when a rental agreement is auto-generated after application approval.
        Status = PENDING_TENANT — tenant must sign first.

        Channels:
          - Email to tenant   → "Your agreement is ready — sign now"
          - Email to landlord → "Agreement sent to tenant — you'll be notified when it's your turn"
          - In-app for tenant  → link to /tenant/agreements/{agreement_id}
          - In-app for landlord → link to /landlord/agreements/{agreement_id}
        """
        # ── Email → tenant ────────────────────────────────────────────────────
        if tenant_email:
            await _run(
                email_service._send_email,
                tenant_email,
                f"📋 Your Rental Agreement is Ready — '{property_title}'",
                _html_agreement_ready_to_sign(
                    tenant_name, property_title, agreement_id, self.base_url, self.support_email
                ),
                (
                    f"Hi {tenant_name}, your rental agreement for '{property_title}' is ready. "
                    f"Please review and sign at: {self.base_url}/tenant/agreements/{agreement_id}"
                ),
            )

        # ── Email → landlord ──────────────────────────────────────────────────
        if landlord_email:
            await _run(
                email_service._send_email,
                landlord_email,
                f"📋 Rental Agreement Sent to Tenant — '{property_title}'",
                _html_agreement_sent_to_tenant(
                    landlord_name, tenant_name, property_title, agreement_id, self.base_url, self.support_email
                ),
                (
                    f"Hi {landlord_name}, the rental agreement for '{property_title}' has been sent "
                    f"to {tenant_name} for signature. You'll be notified when it's your turn to countersign."
                ),
            )

        # ── In-app → tenant ───────────────────────────────────────────────────
        # FIX: notif_type must be a valid notifications_type_check value.
        # "agreement_created" is NOT in the constraint — use "system".
        try:
            create_notification(
                user_id=tenant_id,
                notif_type="system",
                title="Rental Agreement Ready — Sign Now",
                message=(
                    f"Your rental agreement for '{property_title}' is ready. "
                    f"Please review the terms and sign to proceed."
                ),
                link=f"/tenant/agreements/{agreement_id}",
                data={
                    "agreement_id": agreement_id,
                    "application_id": application_id,
                    "property_title": property_title,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (tenant) failed for notify_agreement_created: {e}")

        # ── In-app → landlord ─────────────────────────────────────────────────
        try:
            create_notification(
                user_id=landlord_id,
                notif_type="system",
                title="Agreement Sent to Tenant",
                message=(
                    f"The rental agreement for '{property_title}' has been sent to "
                    f"{tenant_name} for their signature. You'll be notified when it's your turn."
                ),
                link=f"/landlord/agreements/{agreement_id}",
                data={
                    "agreement_id": agreement_id,
                    "application_id": application_id,
                    "property_title": property_title,
                    "tenant_name": tenant_name,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (landlord) failed for notify_agreement_created: {e}")

        logger.info(
            f"✅ [NOTIF] notify_agreement_created done for agreement {agreement_id}"
        )

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_agreement_signed_by_tenant(
        self,
        *,
        agreement_id: str,
        application_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        landlord_phone: Optional[str],
    ) -> None:
        """
        Fire after tenant signs. Status → PENDING_LANDLORD.
        Notifies landlord that it's their turn to countersign.

        Channels:
          - Email to landlord  → "Tenant has signed — your turn to countersign"
          - SMS  to landlord   → short nudge
          - In-app for landlord → links directly to /landlord/agreements/{id}
        """
        # ── Email → landlord ──────────────────────────────────────────────────
        if landlord_email:
            await _run(
                email_service._send_email,
                landlord_email,
                f"✍️ Action Required: Countersign Agreement for '{property_title}'",
                _html_landlord_countersign_required(
                    landlord_name, tenant_name, property_title, agreement_id,
                    self.base_url, self.support_email
                ),
                (
                    f"Hi {landlord_name}, {tenant_name} has signed the rental agreement "
                    f"for '{property_title}'. Please log in and countersign to finalise the tenancy: "
                    f"{self.base_url}/landlord/agreements/{agreement_id}"
                ),
            )

        # ── SMS → landlord ────────────────────────────────────────────────────
        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                (
                    f"NuloAfrica: {tenant_name} has signed the rental agreement for "
                    f"'{property_title}'. Please countersign to complete the tenancy: "
                    f"{self.base_url}/landlord/agreements/{agreement_id}"
                ),
            )

        # ── In-app → landlord ─────────────────────────────────────────────────
        # FIX: "agreement_countersign_required" is NOT a valid notifications_type_check value.
        # Use "system" — the correct fallback for events without a dedicated type.
        try:
            create_notification(
                user_id=landlord_id,
                notif_type="system",
                title="Your Signature Required",
                message=(
                    f"{tenant_name} has signed the rental agreement for '{property_title}'. "
                    f"Please review and countersign to finalise the tenancy."
                ),
                link=f"/landlord/agreements/{agreement_id}",
                data={
                    "agreement_id": agreement_id,
                    "application_id": application_id,
                    "property_title": property_title,
                    "tenant_name": tenant_name,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (landlord) failed for notify_agreement_signed_by_tenant: {e}")

        logger.info(
            f"✅ [NOTIF] notify_agreement_signed_by_tenant done for agreement {agreement_id}"
        )

    # ─────────────────────────────────────────────────────────────────────────

    async def notify_agreement_fully_signed(
        self,
        *,
        agreement_id: str,
        application_id: str,
        property_title: str,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        landlord_id: str,
        landlord_name: str,
    ) -> None:
        """
        Fire after landlord countersigns. Status → SIGNED.
        Notifies both parties that the agreement is fully executed.

        Channels:
          - Email to tenant    → "Both parties have signed — proceed to payment"
          - SMS  to tenant     → short celebration message
          - In-app for tenant  → links to /tenant/agreements/{id}
          - In-app for landlord → confirmation that signing is complete
        """
        # ── Email → tenant ────────────────────────────────────────────────────
        if tenant_email:
            await _run(
                email_service._send_email,
                tenant_email,
                f"🎉 Agreement Fully Signed — '{property_title}'",
                _html_agreement_fully_signed(
                    tenant_name, landlord_name, property_title, agreement_id,
                    self.base_url, self.support_email
                ),
                (
                    f"Hi {tenant_name}, great news! {landlord_name} has countersigned your rental "
                    f"agreement for '{property_title}'. Both parties have signed — you can now "
                    f"proceed to payment: {self.base_url}/tenant/agreements/{agreement_id}"
                ),
            )

        # ── SMS → tenant ──────────────────────────────────────────────────────
        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                (
                    f"NuloAfrica: Your rental agreement for '{property_title}' is fully signed! "
                    f"Proceed to payment: {self.base_url}/tenant/agreements/{agreement_id}"
                ),
            )

        # ── In-app → tenant ───────────────────────────────────────────────────
        # FIX: "agreement_fully_signed" is NOT a valid notifications_type_check value.
        # Use "system" for both tenant and landlord in-app notifications.
        try:
            create_notification(
                user_id=tenant_id,
                notif_type="system",
                title="Agreement Fully Signed!",
                message=(
                    f"{landlord_name} has countersigned your agreement for '{property_title}'. "
                    f"Both parties have signed — please proceed to payment."
                ),
                link=f"/tenant/agreements/{agreement_id}",
                data={
                    "agreement_id": agreement_id,
                    "application_id": application_id,
                    "property_title": property_title,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (tenant) failed for notify_agreement_fully_signed: {e}")

        # ── In-app → landlord ─────────────────────────────────────────────────
        try:
            create_notification(
                user_id=landlord_id,
                notif_type="system",
                title="Agreement Fully Signed",
                message=(
                    f"Both you and {tenant_name} have signed the rental agreement for "
                    f"'{property_title}'. The tenancy is now pending payment."
                ),
                link=f"/landlord/agreements/{agreement_id}",
                data={
                    "agreement_id": agreement_id,
                    "application_id": application_id,
                    "property_title": property_title,
                    "tenant_name": tenant_name,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (landlord) failed for notify_agreement_fully_signed: {e}")

        logger.info(
            f"✅ [NOTIF] notify_agreement_fully_signed done for agreement {agreement_id}"
        )

    async def notify_payment_initiated(
        self,
        *,
        transaction_id: str,
        agreement_id: str,
        property_title: str,
        amount_ngn: int,
        tenant_id: str,
        tenant_name: str,
        landlord_id: str,
        landlord_name: str,
    ) -> None:
        """
        Fire immediately after tenant is redirected to Paystack.
        In-app only -- no email/SMS. The tenant is about to leave to complete
        payment; flooding them with email at this moment is bad UX and
        premature (payment not yet confirmed).

        Channels:
          - In-app for tenant   -> "Payment initiated, complete on Paystack"
          - In-app for landlord -> "Tenant has initiated payment"
        """
        amount_fmt = f"N{amount_ngn:,}"

        # -- In-app -> tenant -------------------------------------------------
        try:
            create_notification(
                user_id=tenant_id,
                notif_type="system",
                title="Payment Initiated",
                message=(
                    f"You have initiated payment of {amount_fmt} for '{property_title}'. "
                    f"Complete your payment on Paystack to confirm your tenancy."
                ),
                link=f"/tenant/payments/callback?reference=pending&agreement_id={agreement_id}",
                data={
                    "transaction_id": transaction_id,
                    "agreement_id": agreement_id,
                    "amount_ngn": amount_ngn,
                    "property_title": property_title,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (tenant) failed for notify_payment_initiated: {e}")

        # -- In-app -> landlord -----------------------------------------------
        try:
            create_notification(
                user_id=landlord_id,
                notif_type="system",
                title="Tenant Initiated Payment",
                message=(
                    f"{tenant_name} has initiated payment of {amount_fmt} "
                    f"for '{property_title}'. Payment is being processed."
                ),
                link=f"/landlord/agreements",
                data={
                    "transaction_id": transaction_id,
                    "agreement_id": agreement_id,
                    "amount_ngn": amount_ngn,
                    "property_title": property_title,
                    "tenant_name": tenant_name,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (landlord) failed for notify_payment_initiated: {e}")

        logger.info(
            f"[NOTIF] notify_payment_initiated done for transaction {transaction_id}"
        )

    async def notify_payment_confirmed(
        self,
        *,
        transaction_id: str,
        property_title: str,
        amount_ngn: int,
        tenant_id: str,
        tenant_name: str,
        tenant_email: Optional[str],
        tenant_phone: Optional[str],
        landlord_id: str,
        landlord_name: str,
        landlord_email: Optional[str],
        landlord_phone: Optional[str],
    ) -> None:
        """
        Fire from the Paystack webhook ONLY when charge.success is received.
        This is the confirmation that rent has been paid. Full channels for
        both parties -- this is the most important notification in the flow.

        Channels:
          - Email to tenant    -> "Payment confirmed, tenancy active"
          - SMS  to tenant     -> short confirmation
          - In-app for tenant  -> links to /tenant/payments
          - Email to landlord  -> "Payment received for [property]"
          - SMS  to landlord   -> short alert
          - In-app for landlord -> links to /landlord/payments
        """
        amount_fmt = f"N{amount_ngn:,}"

        # -- Email -> tenant --------------------------------------------------
        if tenant_email:
            await _run(
                email_service._send_email,
                tenant_email,
                f"Payment Confirmed -- '{property_title}'",
                _html_payment_confirmed_tenant(
                    tenant_name, property_title, amount_ngn,
                    self.base_url, self.support_email
                ),
                (
                    f"Hi {tenant_name}, your payment of {amount_fmt} for "
                    f"'{property_title}' has been confirmed. Your tenancy is now active. "
                    f"View your payment: {self.base_url}/tenant/payments"
                ),
            )

        # -- SMS -> tenant ----------------------------------------------------
        if tenant_phone:
            await _run(
                sms_service.send_sms,
                tenant_phone,
                (
                    f"NuloAfrica: Payment of {amount_fmt} confirmed for '{property_title}'. "
                    f"Your tenancy is now active."
                ),
            )

        # -- In-app -> tenant -------------------------------------------------
        try:
            create_notification(
                user_id=tenant_id,
                notif_type="system",
                title="Payment Confirmed!",
                message=(
                    f"Your payment of {amount_fmt} for '{property_title}' has been received. "
                    f"Your tenancy is now active."
                ),
                link="/tenant/payments",
                data={
                    "transaction_id": transaction_id,
                    "amount_ngn": amount_ngn,
                    "property_title": property_title,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (tenant) failed for notify_payment_confirmed: {e}")

        # -- Email -> landlord ------------------------------------------------
        if landlord_email:
            await _run(
                email_service._send_email,
                landlord_email,
                f"Payment Received -- '{property_title}'",
                _html_payment_confirmed_landlord(
                    landlord_name, tenant_name, property_title, amount_ngn,
                    self.base_url, self.support_email
                ),
                (
                    f"Hi {landlord_name}, {tenant_name} has paid {amount_fmt} for "
                    f"'{property_title}'. The tenancy is now active. "
                    f"View payment: {self.base_url}/landlord/payments"
                ),
            )

        # -- SMS -> landlord --------------------------------------------------
        if landlord_phone:
            await _run(
                sms_service.send_sms,
                landlord_phone,
                (
                    f"NuloAfrica: {tenant_name} has paid {amount_fmt} for '{property_title}'. "
                    f"Tenancy is now active."
                ),
            )

        # -- In-app -> landlord -----------------------------------------------
        try:
            create_notification(
                user_id=landlord_id,
                notif_type="system",
                title="Payment Received",
                message=(
                    f"{tenant_name} has paid {amount_fmt} for '{property_title}'. "
                    f"The tenancy is now active and the property is occupied."
                ),
                link="/landlord/payments",
                data={
                    "transaction_id": transaction_id,
                    "amount_ngn": amount_ngn,
                    "property_title": property_title,
                    "tenant_name": tenant_name,
                },
            )
        except Exception as e:
            logger.warning(f"[NOTIF] In-app (landlord) failed for notify_payment_confirmed: {e}")

        logger.info(
            f"[NOTIF] notify_payment_confirmed done for transaction {transaction_id}"
        )



    async def notify_new_message(
        recipient_id: str,
        sender_id: str,
        conversation_id: str,
        property_id: Optional[str],
        message_preview: str,
    ) -> None:
        """
        In-app notification when a user receives a new message.

        Deliberately in-app ONLY -- no email, no SMS.
        Rationale: messages are high-frequency; email/SMS on every message
        would spam users and violate Nigerian UX norms. Use email/SMS only
        for the FIRST message in a brand-new conversation thread (TODO: future).

        Non-fatal: logs errors but never raises. A notification failure must
        never block the message from being saved.
        """
        try:
            # Resolve sender display name.
            # COALESCE full_name -> first_name -> 'Someone' guards against
            # OAuth users whose full_name is NULL in public.users (Rule: always
            # handle NULL full_name for OAuth accounts).
            loop = asyncio.get_event_loop()
            sender_resp = await loop.run_in_executor(
                None,
                lambda: supabase_admin.table("users")
                .select("full_name, first_name, user_type")
                .eq("id", sender_id)
                .execute()
            )
            sender = sender_resp.data[0] if sender_resp.data else None
            sender_name = (
                (sender.get("full_name") or sender.get("first_name") or "Someone")
                if sender
                else "Someone"
            )

            # Truncate preview to keep notifications tidy
            preview = (
                message_preview[:77] + "..."
                if len(message_preview) > 77
                else message_preview
            )

            # Build the deep-link.
            # Frontend messages page is at /tenant/messages or /landlord/messages
            # but the conversation route is the same for both.
            # Use a generic /messages/{id} path -- layout will route correctly.
            link = f"/messages/{conversation_id}"

            await create_notification(
                user_id=recipient_id,
                notification_type="new_message",
                title=f"New message from {sender_name}",
                message=preview,
                link=link,
                data={
                    "conversation_id": conversation_id,
                    "sender_id": sender_id,
                    "property_id": property_id,
                },
            )

        except Exception as e:
            # Non-fatal -- log and continue (matches pattern of all notify_* functions)
            print(f"[NOTIFICATIONS] notify_new_message failed for recipient {recipient_id}: {e}")





    # =========================================================================
    # BACKWARD COMPATIBILITY
    # =========================================================================

    async def send_verification_notification(self, recipient, subject, message,
                                              onboarding_id=None, template_data=None):
        """Legacy method — sends a plain email via email_service."""
        if recipient:
            await _run(
                email_service._send_email,
                recipient,
                subject,
                f"<p>{message}</p>",
                message,
            )

    async def send_onboarding_submitted_notification(self, user_email, user_name, onboarding_id):
        await self.notify_onboarding_submitted(
            user_id="",
            user_email=user_email,
            user_name=user_name,
            onboarding_id=str(onboarding_id),
        )

    async def send_verification_approved_notification(self, user_email, user_name, trust_score):
        await self.notify_verification_approved(
            user_id="",
            user_email=user_email,
            user_name=user_name,
            trust_score=trust_score,
        )

    async def send_verification_rejected_notification(self, user_email, user_name,
                                                       rejection_reason, onboarding_id):
        await self.notify_verification_rejected(
            user_id="",
            user_email=user_email,
            user_name=user_name,
            rejection_reason=rejection_reason,
            onboarding_id=str(onboarding_id),
        )

    async def send_admin_new_submission_notification(self, admin_email, landlord_name,
                                                      onboarding_id, submission_time):
        await self.notify_admin_new_submission(
            admin_email=admin_email,
            landlord_name=landlord_name,
            landlord_email="",
            onboarding_id=str(onboarding_id),
        )

    async def send_admin_notification_new_submission(self, admin_email, landlord_name,
                                                      landlord_email, onboarding_id):
        await self.notify_admin_new_submission(
            admin_email=admin_email,
            landlord_name=landlord_name,
            landlord_email=landlord_email,
            onboarding_id=str(onboarding_id),
        )

    async def send_document_processing_failed_notification(self, user_email, user_name,
                                                            document_type, error_message):
        await self.notify_document_processing_failed(
            user_id="",
            user_email=user_email,
            user_name=user_name,
            document_type=document_type,
            error_message=error_message,
        )




# ─────────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────────

notification_service = NotificationService()


# ─────────────────────────────────────────────────────────────────────────────
# EMAIL HTML BUILDERS
# ─────────────────────────────────────────────────────────────────────────────
#
# Wordmark: "Nulo" Montserrat ExtraBold black (#0F172A)
#           "Africa" Montserrat Bold orange (#F97316)
# No images — pure text, works in every email client.
# ─────────────────────────────────────────────────────────────────────────────

_CSS = """<style>
@import url('https://fonts.googleapis.com/css2?family=Montserrat:wght@400;600;700;800&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{background:#F1F5F9;font-family:'Montserrat',Arial,sans-serif;-webkit-font-smoothing:antialiased}
.wrap{max-width:600px;margin:0 auto;padding:32px 16px 48px}
.card{background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 20px rgba(0,0,0,0.08)}

/* ── Header ── */
.hdr{padding:32px 32px 24px;text-align:center}
.hdr.orange{background:linear-gradient(135deg,#F97316 0%,#EA580C 100%)}
.hdr.green {background:linear-gradient(135deg,#16A34A 0%,#15803D 100%)}
.hdr.red   {background:linear-gradient(135deg,#DC2626 0%,#B91C1C 100%)}
.hdr.amber {background:linear-gradient(135deg,#D97706 0%,#B45309 100%)}
.hdr.blue  {background:linear-gradient(135deg,#1D4ED8 0%,#1E40AF 100%)}

/* ── Wordmark pill — white bg so black/orange always reads on any header ── */
.brand-pill{display:inline-block;background:#ffffff;
            border-radius:8px;padding:7px 16px;margin-bottom:20px}
.brand-pill .nulo  {font-size:20px;font-weight:800;color:#0F172A;
                    font-family:'Montserrat',Arial,sans-serif;letter-spacing:-0.3px}
.brand-pill .africa{font-size:20px;font-weight:700;color:#F97316;
                    font-family:'Montserrat',Arial,sans-serif;letter-spacing:-0.3px}

/* ── Header title & subtitle ── */
.hdr h1{color:#ffffff;font-size:20px;font-weight:700;margin-bottom:6px;
        font-family:'Montserrat',Arial,sans-serif}
.hdr .sub{color:rgba(255,255,255,0.88);font-size:13px;font-weight:500;margin-top:4px}

/* ── Body ── */
.body{padding:32px}
.body p{color:#334155;font-size:15px;line-height:1.75;margin-bottom:14px;
        font-family:'Montserrat',Arial,sans-serif}
.body strong{color:#0F172A;font-weight:700}
.divider{height:1px;background:#E2E8F0;margin:20px 0}

/* ── Info box ── */
.box{background:#FFF7ED;border-left:4px solid #F97316;
     padding:14px 16px;margin:16px 0;border-radius:0 8px 8px 0}
.box strong{color:#C2410C;font-size:14px;display:block;margin-bottom:3px}
.box p{color:#44403C;font-size:14px;margin:0}

/* ── Status badge ── */
.badge{padding:18px 20px;border-radius:10px;text-align:center;margin:20px 0}
.badge.pending{background:#FFF7ED;border:1px solid #FED7AA}
.badge.pending h3{color:#EA580C;font-size:16px;font-weight:700;margin-bottom:4px;
                  font-family:'Montserrat',Arial,sans-serif}
.badge.success{background:#F0FDF4;border:1px solid #BBF7D0}
.badge.success h3{color:#15803D;font-size:16px;font-weight:700;margin-bottom:4px;
                  font-family:'Montserrat',Arial,sans-serif}
.badge p{color:#64748B;font-size:13px;margin:0}

/* ── Detail table (admin emails) ── */
.detail{width:100%;border-collapse:collapse;margin:16px 0;
        border:1px solid #E2E8F0;border-radius:8px;overflow:hidden}
.detail tr:nth-child(odd) td{background:#F8FAFC}
.detail td{padding:10px 14px;font-size:13px;vertical-align:top;
           font-family:'Montserrat',Arial,sans-serif;border-bottom:1px solid #F1F5F9}
.detail td:first-child{color:#64748B;font-weight:600;white-space:nowrap;width:140px}
.detail td:last-child{color:#0F172A}

/* ── Alert boxes ── */
.warn{background:#FFFBEB;border:1px solid #FCD34D;padding:14px 16px;
      border-radius:8px;margin:16px 0;font-size:14px;color:#92400E;line-height:1.6}
.err {background:#FEF2F2;border:1px solid #FECACA;padding:14px 16px;
      border-radius:8px;margin:16px 0;font-size:14px;color:#991B1B;line-height:1.6}

/* ── Feature list ── */
.feat-item{display:flex;align-items:flex-start;gap:10px;
           padding:12px;background:#F8FAFC;border-radius:8px;margin-bottom:8px}
.feat-dot{width:8px;height:8px;border-radius:50%;background:#F97316;
          flex-shrink:0;margin-top:6px}
.feat-item strong{display:block;color:#0F172A;font-size:14px;font-weight:700;margin-bottom:2px}
.feat-item span{color:#64748B;font-size:13px}

/* ── Buttons ── */
.btns{text-align:center;margin:24px 0 8px}
.btn{display:inline-block;padding:13px 28px;text-decoration:none;
     border-radius:8px;font-weight:700;font-size:14px;margin:4px 6px;
     font-family:'Montserrat',Arial,sans-serif;letter-spacing:0.2px}
.btn.orange{background:#F97316;color:#ffffff}
.btn.green {background:#16A34A;color:#ffffff}
.btn.grey  {background:#64748B;color:#ffffff}

/* ── Footer ── */
.ftr{text-align:center;padding:20px 16px 8px;font-family:'Montserrat',Arial,sans-serif}
.ftr .brand-ftr{font-size:16px;font-weight:800;letter-spacing:-0.3px;margin-bottom:6px}
.ftr .brand-ftr .nulo  {color:#0F172A}
.ftr .brand-ftr .africa{color:#F97316}
.ftr p{color:#94A3B8;font-size:12px;line-height:1.9}
.ftr a{color:#F97316;text-decoration:none}
</style>"""


def _wordmark():
    """White pill containing Nulo (black) + Africa (orange) — reads on any header colour."""
    return (
        '<div class="brand-pill">'
        '<span class="nulo">Nulo</span>'
        '<span class="africa">Africa</span>'
        '</div>'
    )


def _open(hdr_class, title, subtitle=""):
    sub = f'<p class="sub">{subtitle}</p>' if subtitle else ""
    return (
        '<!DOCTYPE html><html lang="en"><head>'
        '<meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'{_CSS}</head><body>'
        '<div class="wrap"><div class="card">'
        f'<div class="hdr {hdr_class}">'
        f'{_wordmark()}'
        f'<h1>{title}</h1>{sub}'
        '</div>'
        '<div class="body">'
    )


def _foot(support_email):
    return (
        '</div>'  # close .body
        '<div class="ftr">'
        '<div class="brand-ftr">'
        '<span class="nulo">Nulo</span><span class="africa">Africa</span>'
        '</div>'
        '<p>Zero Agency Fee Rental Platform</p>'
        '<p>Lagos &bull; Abuja &bull; Port Harcourt</p>'
        f'<p>Questions? <a href="mailto:{support_email}">{support_email}</a></p>'
        '<p style="margin-top:12px;color:#CBD5E1">&copy; 2025 NuloAfrica. All rights reserved.</p>'
        '</div>'
        '</div></div>'  # close .card .wrap
        '</body></html>'
    )


# ─── templates ────────────────────────────────────────────────────────────────

def _html_welcome(user_name, next_step, next_url, support_email, is_landlord=False):
    role = "Landlord" if is_landlord else "Tenant"
    icon = "&#127968;" if is_landlord else "&#128273;"
    return (
        _open("orange", f"{icon} Welcome to NuloAfrica!", f"{role} Account Created")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + f'<p>Your NuloAfrica {role} account is ready. {next_step}</p>'
        + '<div class="divider"></div>'
        + '<div class="box"><strong>Zero Agency Fees</strong>'
        + '<p>Find and rent properties across Lagos, Abuja and Port Harcourt — no agent, no commission.</p></div>'
        + f'<div class="btns"><a href="{next_url}" class="btn orange">Get Started &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_onboarding_submitted(user_name, base_url, support_email):
    return (
        _open("orange", "&#128203; Application Submitted", "We're Reviewing Your Documents")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + '<p>Your landlord verification application has been submitted. Our team will review your documents within 24&#8211;48 hours.</p>'
        + '<div class="badge pending"><h3>&#8987; Under Review</h3><p>Expected decision within 24&#8211;48 hours</p></div>'
        + "<p>We'll notify you by email and in-app as soon as a decision is made.</p>"
        + f'<div class="btns"><a href="{base_url}/onboarding/landlord/verification-pending" class="btn orange">Check Status &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_admin_new_submission(landlord_name, landlord_email, onboarding_id, submitted_at, base_url):
    return (
        _open("blue", "&#128276; New Landlord Submission", "Action Required")
        + '<p>A landlord has submitted their verification application and is awaiting review.</p>'
        + f'<table class="detail"><tr><td>Name</td><td>{landlord_name}</td></tr>'
        + f'<tr><td>Email</td><td>{landlord_email}</td></tr>'
        + f'<tr><td>Submitted</td><td>{submitted_at}</td></tr>'
        + f'<tr><td>Application ID</td><td style="font-family:monospace;font-size:12px">{onboarding_id}</td></tr></table>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/admin/onboarding/details/{onboarding_id}" class="btn orange">Review Application &rarr;</a>'
        + f'<a href="{base_url}/admin/onboarding/queue" class="btn grey">View Queue</a></div>'
        + _foot("nuloafrica26@outlook.com")
    )


def _html_verification_approved(user_name, trust_score, base_url, support_email):
    return (
        _open("green", "&#127881; Verification Approved!", "You're a Verified Landlord")
        + f'<p>Congratulations, <strong>{user_name}</strong>!</p>'
        + '<p>Your identity and documents have been verified. You can now list properties on the marketplace.</p>'
        + f'<div class="badge success"><h3>&#10003; Trust Score: {trust_score}%</h3><p>Tenants can see your verified badge</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>List Properties</strong><span>Add your rentals to the marketplace instantly</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Receive Applications</strong><span>Review and approve tenants directly</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Collect Rent Securely</strong><span>Payments handled through our escrow system</span></div></div>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/landlord/properties/new" class="btn green">List Your First Property &rarr;</a>'
        + f'<a href="{base_url}/landlord/overview" class="btn grey">Go to Dashboard</a></div>'
        + _foot(support_email)
    )


def _html_verification_rejected(user_name, rejection_reason, base_url, support_email):
    return (
        _open("red", "Verification Update", "Action Required")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + '<p>Unfortunately your verification was not approved at this time. Please review the reason below and resubmit with the correct documents.</p>'
        + f'<div class="err"><strong>Reason for rejection:</strong><br>{rejection_reason}</div>'
        + f'<div class="btns"><a href="{base_url}/onboarding/landlord/step-1" class="btn orange">Restart Verification &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_needs_correction(user_name, admin_feedback, base_url, support_email):
    return (
        _open("amber", "&#9888; Corrections Needed", "Please Update Your Application")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + '<p>Our team reviewed your application and needs you to make some corrections before it can be approved.</p>'
        + f'<div class="warn"><strong>Admin Note:</strong><br>{admin_feedback}</div>'
        + f'<div class="btns"><a href="{base_url}/onboarding/landlord/step-1" class="btn orange">Update Application &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_email_verified(user_name, next_label, next_url, support_email):
    return (
        _open("green", "&#10003; Email Verified!", "Your account is confirmed")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + f'<p>Your email has been successfully verified. {next_label}</p>'
        + "<div class=\"badge success\"><h3>&#10003; Account Active</h3><p>You're all set to use NuloAfrica</p></div>"
        + f'<div class="btns"><a href="{next_url}" class="btn green">Continue &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_document_failed(user_name, document_type, error_message, base_url, support_email):
    return (
        _open("amber", "&#9888; Document Issue", "Action Required")
        + f'<p>Hi <strong>{user_name}</strong>,</p>'
        + f'<p>There was a problem processing your <strong>{document_type}</strong>. Please re-upload a clear, legible copy.</p>'
        + f'<div class="err"><strong>Error details:</strong><br>{error_message}</div>'
        + f'<div class="btns"><a href="{base_url}/onboarding/landlord/step-1" class="btn orange">Re-upload Document &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_property_listed(landlord_name, property_title, base_url, support_email):
    return (
        _open("orange", "&#128203; Property Submitted", "Under Review")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p>Your property listing has been submitted and is now under review by our team.</p>'
        + f'<div class="box"><strong>&#127968; {property_title}</strong><p>Submitted — pending approval</p></div>'
        + '<div class="badge pending"><h3>&#8987; Under Review</h3><p>Expected decision within 24 hours</p></div>'
        + f'<div class="btns"><a href="{base_url}/landlord/properties" class="btn orange">View My Properties &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_admin_property_listed(landlord_name, landlord_email, property_title, property_id, submitted_at, base_url):
    return (
        _open("blue", "&#128276; New Property Listing", "Awaiting Your Review")
        + '<p>A landlord has submitted a new property listing for marketplace approval.</p>'
        + f'<table class="detail">'
        + f'<tr><td>Landlord</td><td>{landlord_name}</td></tr>'
        + f'<tr><td>Email</td><td>{landlord_email}</td></tr>'
        + f'<tr><td>Property</td><td>{property_title}</td></tr>'
        + f'<tr><td>Submitted</td><td>{submitted_at}</td></tr>'
        + f'<tr><td>Property ID</td><td style="font-family:monospace;font-size:12px">{property_id}</td></tr></table>'
        + f'<div class="btns"><a href="{base_url}/admin/property-verification" class="btn orange">Review Listing &rarr;</a></div>'
        + _foot("nuloafrica26@outlook.com")
    )


def _html_property_approved(landlord_name, property_title, property_id, base_url, support_email):
    return (
        _open("green", "&#127881; Property Approved!", "Your Listing is Now Live")
        + f'<p>Congratulations, <strong>{landlord_name}</strong>!</p>'
        + f'<p>Your property has been reviewed and approved. It is now live on the NuloAfrica marketplace.</p>'
        + f'<div class="box"><strong>&#127968; {property_title}</strong><p>Live — tenants can find and apply now</p></div>'
        + '<div class="badge success"><h3>&#10003; Live on Marketplace</h3><p>Verified tenants can view and apply for your property</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Receive Applications</strong><span>From verified tenants browsing the marketplace</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Schedule Viewings</strong><span>Accept or decline viewing requests from your dashboard</span></div></div>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/landlord/properties/{property_id}" class="btn green">View Your Listing &rarr;</a>'
        + f'<a href="{base_url}/landlord/overview" class="btn grey">Go to Dashboard</a></div>'
        + _foot(support_email)
    )


def _html_property_rejected(landlord_name, property_title, rejection_reason, base_url, support_email):
    return (
        _open("red", "Property Listing Update", "Action Required")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p>Your property listing was not approved at this time. Please review the feedback, update your listing, and resubmit.</p>'
        + f'<div class="box"><strong>&#127968; {property_title}</strong><p>Requires updates before approval</p></div>'
        + f'<div class="err"><strong>Reason for rejection:</strong><br>{rejection_reason}</div>'
        + f'<div class="btns"><a href="{base_url}/landlord/properties" class="btn orange">Edit &amp; Resubmit &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_application_submitted(landlord_name, property_title, tenant_name, monthly_income, employment_status, message, base_url):
    income_text = f"₦{monthly_income:,}/month" if monthly_income else "Not specified"
    employment_text = employment_status or "Not specified"
    
    return (
        _open("blue", "&#128231; New Application Received", "Review Required")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p>You have received a new rental application for your property <strong>"{property_title}"</strong> from <strong>{tenant_name}</strong>.</p>'
        + '<div class="divider"></div>'
        + '<h3 style="color:#0F172A; font-size:16px; margin-bottom:12px;">Application Details:</h3>'
        + f'<div class="feat-item"><div class="feat-dot"></div><strong>Tenant Name</strong><span>{tenant_name}</span></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><strong>Monthly Income</strong><span>{income_text}</span></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><strong>Employment Status</strong><span>{employment_text}</span></div>'
        + (f'<div class="feat-item"><div class="feat-dot"></div><strong>Message</strong><span>"{message}"</span></div>' if message else '')
        + '<div class="divider"></div>'
        + '<p style="color:#64748B; font-size:14px;">Please review the application at your earliest convenience. You can approve, reject, or request more information from the tenant.</p>'
        + f'<div class="btns"><a href="{base_url}/landlord/applications" class="btn orange">Review Application &rarr;</a></div>'
        + _foot("support@nuloafrica.com")
    )


def _html_application_approved(tenant_name, property_title, landlord_name, base_url):
    """Email template for tenant when their application is approved"""
    return (
        _open("green", "🎉 Your Application Was Approved!", "Welcome to Your New Home")
        + f'<p>Congratulations, <strong>{tenant_name}</strong>!</p>'
        + f'<p>Your application for <strong>"{property_title}"</strong> has been approved by the landlord <strong>{landlord_name}</strong>.</p>'
        + '<div class="divider"></div>'
        + '<div class="badge success"><h3>✓ Application Approved</h3><p>The landlord will be reaching out to you shortly with the next steps.</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Next Steps</strong><span>Expect a message from the landlord with lease agreement details and move-in information</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Secure Transactions</strong><span>All payments are handled through our escrow system — your money is protected</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Support Available</strong><span>Need help? Our support team is here for you</span></div></div>'
        + '<div class="divider"></div>'
        + '<p style="color:#64748B; font-size:14px;">Thank you for choosing NuloAfrica. We\'re excited to help you find your perfect home!</p>'
        + f'<div class="btns"><a href="{base_url}/tenant/applications" class="btn green">View Your Applications &rarr;</a></div>'
        + _foot("support@nuloafrica.com")
    )


def _html_application_rejected(tenant_name, property_title, rejection_reason, base_url):
    """Email template for tenant when their application is rejected"""
    return (
        _open("amber", "Application Update", "Keep Exploring")
        + f'<p>Hi <strong>{tenant_name}</strong>,</p>'
        + f'<p>Thank you for your interest in <strong>"{property_title}"</strong>. Unfortunately, your application was not approved at this time.</p>'
        + '<div class="divider"></div>'
        + f'<div class="warn"><strong>Reason for Decision:</strong><br>{rejection_reason}</div>'
        + '<div class="divider"></div>'
        + '<p style="color:#64748B; font-size:14px;">This doesn\'t mean the end of your search! There are many more great properties on NuloAfrica. Keep browsing and apply for properties you love. With every application, you\'re getting closer to finding your perfect home.</p>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Browse More Properties</strong><span>Thousands of verified listings waiting for you</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Refine Your Search</strong><span>Adjust your preferences and find better matches</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Get Support</strong><span>Our team can help you improve future applications</span></div></div>'
        + f'<div class="btns"><a href="{base_url}/properties" class="btn orange">Browse Properties &rarr;</a></div>'
        + _foot("support@nuloafrica.com")
    )


# ── AGREEMENT EMAIL BUILDERS ──────────────────────────────────────────────────

def _html_agreement_ready_to_sign(tenant_name, property_title, agreement_id, base_url, support_email):
    """Email to tenant: agreement generated, you sign first."""
    return (
        _open("orange", "&#128203; Your Rental Agreement is Ready", "Review &amp; Sign to Proceed")
        + f'<p>Hi <strong>{tenant_name}</strong>,</p>'
        + f'<p>Your rental agreement for <strong>"{property_title}"</strong> has been generated. Please review the full terms and add your digital signature.</p>'
        + '<div class="divider"></div>'
        + '<div class="box"><strong>&#9997; You sign first</strong>'
        + '<p>The landlord will countersign once you\'ve completed your signature. The tenancy is confirmed when both parties have signed.</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Review Lease Terms</strong><span>Read all clauses carefully before signing</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Digital Signature</strong><span>Legally binding — IP address logged for audit trail</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Secure Escrow</strong><span>Payment will follow once both parties have signed</span></div></div>'
        + f'<div class="btns"><a href="{base_url}/tenant/agreements/{agreement_id}" class="btn orange">Review &amp; Sign Agreement &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_agreement_sent_to_tenant(landlord_name, tenant_name, property_title, agreement_id, base_url, support_email):
    """Email to landlord: agreement sent to tenant, waiting for their signature."""
    return (
        _open("blue", "&#128203; Agreement Sent to Tenant", "Awaiting Tenant Signature")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p>The rental agreement for <strong>"{property_title}"</strong> has been sent to <strong>{tenant_name}</strong> for signature.</p>'
        + '<div class="divider"></div>'
        + '<div class="badge pending"><h3>&#8987; Awaiting Tenant Signature</h3><p>The tenant signs first. You\'ll be notified when it\'s your turn to countersign.</p></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><div><strong>Tenant</strong><span>{tenant_name}</span></div></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><div><strong>Property</strong><span>{property_title}</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Next Step</strong><span>You\'ll receive an email and in-app alert when the tenant has signed and it\'s your turn to countersign</span></div></div>'
        + f'<div class="btns"><a href="{base_url}/landlord/agreements/{agreement_id}" class="btn grey">View Agreement &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_landlord_countersign_required(landlord_name, tenant_name, property_title, agreement_id, base_url, support_email):
    """Email to landlord: tenant has signed, now it's your turn to countersign."""
    return (
        _open("orange", "&#9997; Action Required: Countersign Agreement", "Tenant Has Signed")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p><strong>{tenant_name}</strong> has signed the rental agreement for <strong>"{property_title}"</strong>. Please review the agreement and add your countersignature to finalise the tenancy.</p>'
        + '<div class="divider"></div>'
        + '<div class="badge pending"><h3>&#9997; Your Signature Required</h3><p>The tenancy is not legally finalised until you countersign.</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Tenant Signed</strong><span>Signature recorded with timestamp and IP address</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Your Turn</strong><span>Review all terms, then countersign to confirm the tenancy</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>What Happens Next</strong><span>Once both parties have signed, the tenant will be prompted to proceed to payment via escrow</span></div></div>'
        + f'<div class="btns"><a href="{base_url}/landlord/agreements/{agreement_id}" class="btn orange">Review &amp; Countersign &rarr;</a></div>'
        + _foot(support_email)
    )


def _html_agreement_fully_signed(tenant_name, landlord_name, property_title, agreement_id, base_url, support_email):
    """Email to tenant: both parties have signed, proceed to payment."""
    return (
        _open("green", "&#127881; Agreement Fully Signed!", "Proceed to Payment")
        + f'<p>Congratulations, <strong>{tenant_name}</strong>!</p>'
        + f'<p><strong>{landlord_name}</strong> has countersigned your rental agreement for <strong>"{property_title}"</strong>. Both parties have now signed — your tenancy is officially confirmed.</p>'
        + '<div class="divider"></div>'
        + '<div class="badge success"><h3>&#10003; Agreement Fully Executed</h3><p>Both signatures recorded. Your tenancy is legally confirmed.</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Next Step: Payment</strong><span>Complete your rent and caution deposit payment through our secure escrow system</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Escrow Protection</strong><span>Your payment is held securely until move-in is confirmed</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Download PDF</strong><span>A signed copy of your agreement is available for download in your dashboard</span></div></div>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/tenant/agreements/{agreement_id}" class="btn green">Proceed to Payment &rarr;</a>'
        + f'<a href="{base_url}/tenant/agreements/{agreement_id}" class="btn grey">View Agreement</a>'
        + '</div>'
        + _foot(support_email)
    )

def _html_payment_confirmed_tenant(
    tenant_name, property_title, amount_ngn, base_url, support_email
):
    """Email to tenant: payment confirmed, tenancy is now active."""
    amount_fmt = f"&#8358;{amount_ngn:,}"
    return (
        _open("green", "&#10003; Payment Confirmed!", "Your Tenancy is Now Active")
        + f'<p>Congratulations, <strong>{tenant_name}</strong>!</p>'
        + f'<p>Your payment for <strong>"{property_title}"</strong> has been received and confirmed. Your tenancy is now officially active.</p>'
        + '<div class="divider"></div>'
        + f'<div class="badge success"><h3>&#10003; Payment Received</h3><p>{amount_fmt} confirmed via Paystack</p></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Tenancy Active</strong><span>Your rental agreement is now active and the property is yours</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Payment Receipt</strong><span>This email serves as your payment confirmation. Download your signed agreement from your dashboard.</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Maintenance Requests</strong><span>You can now raise maintenance requests directly from your tenant dashboard</span></div></div>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/tenant/payments" class="btn green">View Payment History &rarr;</a>'
        + f'<a href="{base_url}/tenant" class="btn grey">Go to Dashboard</a>'
        + '</div>'
        + _foot(support_email)
    )


def _html_payment_confirmed_landlord(
    landlord_name, tenant_name, property_title, amount_ngn, base_url, support_email
):
    """Email to landlord: rent payment received."""
    amount_fmt = f"&#8358;{amount_ngn:,}"
    return (
        _open("green", "&#128176; Payment Received!", "Rent Confirmed")
        + f'<p>Hi <strong>{landlord_name}</strong>,</p>'
        + f'<p><strong>{tenant_name}</strong> has completed payment for <strong>"{property_title}"</strong>. The tenancy is now active and the property is occupied.</p>'
        + '<div class="divider"></div>'
        + f'<div class="badge success"><h3>&#10003; {amount_fmt} Received</h3><p>Payment confirmed via Paystack</p></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><div><strong>Tenant</strong><span>{tenant_name}</span></div></div>'
        + f'<div class="feat-item"><div class="feat-dot"></div><div><strong>Amount</strong><span>{amount_fmt}</span></div></div>'
        + '<div class="feat-item"><div class="feat-dot"></div><div><strong>Property Status</strong><span>Updated to Occupied on the marketplace</span></div></div>'
        + f'<div class="btns">'
        + f'<a href="{base_url}/landlord/payments" class="btn green">View Payments &rarr;</a>'
        + f'<a href="{base_url}/landlord/overview" class="btn grey">Go to Dashboard</a>'
        + '</div>'
        + _foot(support_email)
    )