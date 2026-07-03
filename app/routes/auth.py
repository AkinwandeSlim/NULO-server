"""
Authentication routes
"""
from fastapi import APIRouter, HTTPException, Depends, status, Request
from app.middleware.rate_limit import limiter
from app.models.user import UserRegister, UserLogin, UserResponse, AuthResponse, SocialLoginRequest
from app.database import supabase, supabase_admin
from app.middleware.auth import get_current_user
from datetime import datetime
from jose import jwt
from app.config import settings
from uuid import uuid4
from datetime import timedelta
from typing import Optional
from pydantic import BaseModel

router = APIRouter(prefix="/auth")

class SyncUserProfile(BaseModel):
    user_id: str
    email: str
    first_name: str
    last_name: str
    full_name: str
    user_type: str  # 'tenant' | 'landlord' | 'admin'
    auth_provider: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    phone_number: Optional[str] = None
    user_type: Optional[str] = None
    location: Optional[str] = None
    onboarding_completed: Optional[bool] = None  #


def _email_already_registered(email: str) -> Optional[dict]:
    """
    AUTH-05 helper: returns a dict with the existing user_id and user_type
    if the email is already registered (in either auth.users or public.users),
    otherwise None.

    We intentionally check BOTH locations because:
      - A user might exist in auth.users (Supabase Auth) without a row
        in public.users (signup half-completed, OAuth-only, etc.).
      - A row might exist in public.users (admin-created, import, etc.)
        without an auth.users row.

    We treat any hit as "already registered" so the user gets a single,
    consistent "this email is taken" message regardless of which side
    has the record.

    Returns {"id": str, "user_type": str} when a duplicate is found, or
    None if the email is free. The user_type is critical so the frontend
    can route the user to the right "account exists" landing page
    (e.g. "you already have a landlord account, sign in instead").
    """
    if not email:
        return None
    try:
        normalized = email.strip().lower()

        # 1) Check public.users (the table the rest of the app reads from)
        #    Fetch user_type at the same time so we can tell the frontend
        #    what role the existing account has.
        public_lookup = (
            supabase_admin.table("users")
            .select("id, user_type")
            .eq("email", normalized)
            .limit(1)
            .execute()
        )
        if public_lookup.data and len(public_lookup.data) > 0:
            row = public_lookup.data[0]
            return {
                "id": row.get("id"),
                "user_type": (row.get("user_type") or "tenant").strip().lower(),
            }

        # 2) Check auth.users via the admin API. Falls back silently if
        #    the project doesn't have admin.list_users enabled — the
        #    public.users check above is the source of truth.
        try:
            admin_list = supabase_admin.auth.admin.list_users()
            for u in getattr(admin_list, "users", []) or []:
                if (u.email or "").strip().lower() == normalized:
                    # We don't always have user_type in the admin response;
                    # default to "tenant" if it's missing so the frontend
                    # still gets a usable existing_type.
                    raw_meta = getattr(u, "user_metadata", None) or {}
                    inferred_type = (
                        (raw_meta.get("user_type") if isinstance(raw_meta, dict) else None)
                        or "tenant"
                    )
                    return {
                        "id": getattr(u, "id", None),
                        "user_type": str(inferred_type).strip().lower(),
                    }
        except Exception as inner_err:
            # Don't fail the whole registration flow if admin listing is
            # unavailable — log and continue. The next layer
            # (supabase.auth.sign_up) will still surface its own
            # "already registered" error if needed.
            import logging
            logging.getLogger(__name__).debug(
                f"[AUTH-05] admin.list_users unavailable: {inner_err}"
            )

        return None
    except Exception:
        # Defensive: if the lookup itself blows up (DB hiccup, RLS
        # misconfig, etc.) we DON'T block registration — let Supabase's
        # own sign_up error be the source of truth.
        return None


@router.post("/register", response_model=AuthResponse)
async def register(user_data: UserRegister):
    """
    Register a new user (tenant or landlord) with landlord verification support
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"\n Starting registration for: {user_data.email}")

        # ── AUTH-05: Cross-account email uniqueness guard ─────────────────
        # Check both Supabase auth (admin API) AND the public.users table
        # because:
        #   - A user may have started an OAuth flow but never completed
        #     signup, leaving a row in auth.users but not in public.users.
        #   - Conversely, manual DB inserts (e.g. from the admin panel)
        #     can create a public.users row without an auth.users row.
        # Either way, we must NOT silently allow a second account with the
        # same email — that leads to two roles under one email, duplicate
        # notifications and login ambiguity. Return a clean 409 so the
        # frontend can show a helpful "already registered" message.
        existing = _email_already_registered(user_data.email)
        if existing:
            existing_id = existing.get("id")
            existing_role = (existing.get("user_type") or "tenant").strip().lower()
            requested_role = (user_data.user_type or "tenant").strip().lower()

            logger.warning(
                f"⚠️ [AUTH-05] Duplicate registration attempt blocked for "
                f"{user_data.email} (existing user_id={existing_id}, "
                f"existing_role={existing_role}, requested_role={requested_role})"
            )

            # Build a detail message that explicitly tells the frontend
            # what role the existing account has, so the user gets a
            # clear, role-aware "account already exists" page instead of
            # a generic toast that just says "email is taken".
            role_phrase = {
                "tenant":   "as a tenant",
                "landlord": "as a landlord",
                "admin":    "as an admin",
            }.get(existing_role, f"as a {existing_role}")

            request_phrase = {
                "tenant":   "tenant",
                "landlord": "landlord",
                "admin":    "admin",
            }.get(requested_role, requested_role)

            detail_msg = (
                f"This email is already registered {role_phrase}. "
                f"Cannot create a {request_phrase} account with the same email. "
                f"Please sign in to your existing {existing_role} account instead."
            )

            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": detail_msg,
                    "existing_user_id": existing_id,
                    "existing_type": existing_role,
                    "requested_type": requested_role,
                    "email": user_data.email,
                },
            )

        # Create auth user with Supabase
        logger.info(f" Creating Supabase auth user...")
        try:
            # ── BUG-001 fix: Ensure verification link redirects to the correct
            # production domain (not localhost) so the verification flow
            # completes end-to-end. The redirect URL is constructed from the
            # configured ALLOWED_ORIGINS (production frontend) — falls back to
            # the first origin if no explicit redirect env var is set.
            redirect_base = (
                getattr(settings, "FRONTEND_URL", None)
                or settings.cors_origins[0].rstrip("/")
            )
            verification_redirect_url = (
                f"{redirect_base}/auth/callback?type=signup&next="
                f"{'/landlord/overview' if (user_data.user_type or 'tenant') == 'landlord' else '/tenant'}"
            )

            auth_response = supabase.auth.sign_up({
                "email": user_data.email,
                "password": user_data.password,
                "options": {
                    "data": {
                        "full_name": user_data.full_name or "User",
                        "user_type": user_data.user_type or "tenant",
                        "phone_number": user_data.phone_number or None,
                    },
                    # BUG-001: Send the user to the correct app domain after
                    # clicking the verification link. Without this, Supabase
                    # falls back to its Site URL config (often localhost in
                    # dev/staging) and the link appears broken.
                    "email_redirect_to": verification_redirect_url,
                }
            })
        except Exception as sign_up_err:
            # Some versions of supabase-py raise rather than return
            # an "already registered" response. Catch it here so we
            # can return the same friendly 409 the frontend expects.
            err_str = str(sign_up_err).lower()
            if (
                "already" in err_str
                or "registered" in err_str
                or "user already" in err_str
                or "duplicate" in err_str
            ):
                # Re-fetch the existing record so we can include the role
                # in the 409 detail — this lets the frontend route the
                # user to a role-aware "account exists" page even when
                # Supabase's own sign_up is the one that caught the
                # duplicate.
                existing_after = _email_already_registered(user_data.email) or {}
                existing_role_after = (
                    existing_after.get("user_type") or "tenant"
                ).strip().lower()
                requested_role_after = (
                    user_data.user_type or "tenant"
                ).strip().lower()
                logger.warning(
                    f"⚠️ [AUTH-05] Supabase sign_up reported "
                    f"already-registered for {user_data.email}: {sign_up_err}"
                )
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": (
                            f"This email is already registered as a "
                            f"{existing_role_after}. Cannot create a "
                            f"{requested_role_after} account with the same "
                            f"email. Please sign in to your existing "
                            f"{existing_role_after} account instead."
                        ),
                        "existing_user_id": existing_after.get("id"),
                        "existing_type": existing_role_after,
                        "requested_type": requested_role_after,
                        "email": user_data.email,
                    },
                )
            # Different error — re-raise so the outer handler can deal with it.
            raise

        print(f" [REGISTER] Supabase auth response received")

        if not auth_response.user:
            print(f" [REGISTER] Failed to create auth user")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user"
            )
        
        user_id = auth_response.user.id
        print(f" [REGISTER] Auth user created: {user_id}")
        
        # Prepare user record with landlord verification fields
        user_record = {
            "id": user_id,
            "email": user_data.email,
            "phone_number": user_data.phone_number or None,
            "full_name": user_data.full_name,
            "user_type": user_data.user_type or "tenant",
            "avatar_url": None,
            "location": None,
            "trust_score": 50,
            "verification_status": "pending" if user_data.user_type == "landlord" else "partial",
            "onboarding_completed": False,
        }
        
        # Add landlord verification fields if applicable
        if user_data.user_type == "landlord":
            user_record.update({
                "nin": user_data.nin,
                "bvn": user_data.bvn,
                "id_document": user_data.id_document,
                "selfie_photo": user_data.selfie_photo,
                "account_type": user_data.account_type,
                "verification_submitted_at": datetime.now().isoformat() if (user_data.nin and user_data.bvn) else None,
            })
            
            # Add company fields if company account
            if user_data.account_type == "company":
                user_record.update({
                    "company_name": user_data.company_name,
                    "cac_number": user_data.cac_number,
                    "cac_certificate": user_data.cac_certificate,
                    "tax_id": user_data.tax_id,
                })
        
        print(f" [REGISTER] Inserting user record...")
        db_result = supabase_admin.table("users").insert(user_record).execute()
        
        if db_result.data and len(db_result.data) > 0:
            print(f" [REGISTER] Database record created")
            created_user = db_result.data[0]
            user_response = UserResponse(**created_user)
        else:
            print(f" [REGISTER] DB insert failed, using manual response")
            # Fallback to manual construction
            user_response = UserResponse(
                id=user_id,
                email=user_data.email,
                full_name=user_data.full_name,
                avatar_url=None,
                location=None,
                user_type=user_data.user_type or "tenant",
                trust_score=50,
                verification_status="pending" if user_data.user_type == "landlord" else "partial",
                created_at=datetime.now(),
            )

        # Create a session for the newly registered user
        session = supabase.auth.get_session()
        if not session:
            print(f" [REGISTER] No session found after registration")
            access_token = auth_response.session.access_token if auth_response.session else None
        else:
            access_token = session.access_token

        print(f" [REGISTER] User registered successfully!")
        return AuthResponse(
            success=True,
            user=user_response,
            access_token=access_token,
            token_type="bearer",
            message="User registered successfully!" + (" Please wait for landlord verification." if user_data.user_type == "landlord" else " Please complete your profile.")
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f" [REGISTER] Error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        
        # Handle specific Supabase errors
        error_msg = str(e).lower()
        if "user already registered" in error_msg or "already registered" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This email is already registered. Please sign in instead."
            )
        elif "password" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Password must be at least 8 characters long."
            )
        elif "email" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Please provide a valid email address."
            )
        else:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Registration failed: {str(e)}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# BUG-002 / BUG-006 fix: Resend verification email endpoint
# ──────────────────────────────────────────────────────────────────────────────
class ResendVerificationRequest(BaseModel):
    email: str


@router.post("/resend-verification")
@limiter.limit("3/10minutes")  # BUG-001: Rate limit to prevent abuse
async def resend_verification_email(req: ResendVerificationRequest, request: Request):
    """
    Re-send the email verification link to a user who never confirmed their
    address (BUG-002). Also used by the "I have verified my email" recovery
    flow on the landlord onboarding page when the original link bounced
    (BUG-006).

    Always returns 200 with a generic success message so we do not leak
    whether the email exists — this prevents account enumeration. The actual
    email is sent only if Supabase has a matching user that is still
    unverified.
    """
    try:
        if not req.email:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is required",
            )

        normalized = req.email.strip().lower()

        # Build the verification redirect URL from configured frontend
        redirect_base = (
            getattr(settings, "FRONTEND_URL", None)
            or settings.cors_origins[0].rstrip("/")
        )
        verification_redirect_url = (
            f"{redirect_base}/auth/callback?type=signup&next=/landlord/overview"
        )

        # resend() sends a fresh confirmation email if the user exists and
        # is still unverified. It is a no-op (silent success) otherwise,
        # which is exactly the behaviour we want for the public endpoint.
        try:
            supabase.auth.resend({
                "type": "signup",
                "email": normalized,
                "options": {
                    "email_redirect_to": verification_redirect_url,
                },
            })
        except Exception as resend_err:
            # Don't surface Supabase's "user not found" to the caller — log
            # it server-side and return a generic success.
            import logging
            logging.getLogger(__name__).warning(
                f"[RESEND-VERIFICATION] Supabase resend raised for "
                f"{normalized}: {resend_err}"
            )

        return {
            "success": True,
            "message": (
                "If an account exists for that email and is not yet "
                "verified, a new verification link has been sent."
            ),
        }
    except HTTPException:
        raise
    except Exception as e:
        # Always return success-shaped response so the public endpoint
        # cannot be used to enumerate accounts.
        import logging
        logging.getLogger(__name__).error(
            f"[RESEND-VERIFICATION] Unexpected error: {e}"
        )
        return {
            "success": True,
            "message": (
                "If an account exists for that email and is not yet "
                "verified, a new verification link has been sent."
            ),
        }


@router.post("/login", response_model=AuthResponse)
async def login(credentials: UserLogin):
    """
    Login user with email and password
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"\n Login attempt for: {credentials.email}")
        
        # Authenticate with Supabase Admin (to bypass RLS)
        logger.info(f" Authenticating with Supabase...")
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password,
        })
        
        logger.info(f" Auth response received: {auth_response}")
        
        if not auth_response.user:
            logger.error(f" No user in auth response")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user_id = auth_response.user.id
        logger.info(f" User authenticated: {user_id}")
        
        # Fetch user profile
        logger.info(f" Fetching user profile...")
        user_data = supabase_admin.table("users").select(
            "id, email, full_name, avatar_url, user_type, trust_score, verification_status, created_at"
        ).eq("id", user_id).single().execute()
        
        if not user_data.data:
            logger.error(f" User profile not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
        
        # Update last login - REMOVED TO PREVENT HANGING
        # supabase_admin.table("users").update({
        #     "last_login_at": datetime.now().isoformat()
        # }).eq("id", user_id).execute()
        
        logger.info(f" User data: {user_data.data}")
        
        # Add missing location field if not present
        if 'location' not in user_data.data:
            user_data.data['location'] = None
        
        user_response = UserResponse(**user_data.data)
        
        logger.info(f" Login successful, returning response")
        return AuthResponse(
            success=True,
            user=user_response,
            access_token=auth_response.session.access_token,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_message = str(e)
        # Check for specific Supabase auth errors
        if "Invalid login credentials" in error_message or "invalid_grant" in error_message:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Login failed: {error_message}"
        )


@router.get("/me", response_model=UserResponse)
async def get_current_user_profile(current_user: dict = Depends(get_current_user)):
    """
    Get current authenticated user profile
    """
    try:
        user_id = current_user["id"]
        
        # Fetch complete user profile
        user_data = supabase_admin.table("users").select("*").eq("id", user_id).single().execute()
        
        if not user_data.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found"
            )
        
        return UserResponse(**user_data.data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.patch("/me", response_model=UserResponse)
async def update_current_user_profile(update: UserUpdate, current_user: dict = Depends(get_current_user)):
    """
    Update current authenticated user's profile (partial updates allowed)
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        user_id = current_user["id"]

        # Build payload with only provided fields
        payload = {}
        if update.full_name is not None:
            payload["full_name"] = update.full_name
        if update.phone_number is not None:
            payload["phone_number"] = update.phone_number
        if update.user_type is not None:
            payload["user_type"] = update.user_type
        if update.location is not None:
            payload["location"] = update.location
        if update.onboarding_completed is not None:  # ✅ Added
            payload["onboarding_completed"] = update.onboarding_completed

        if not payload:
            return await get_current_user_profile(current_user)

        # Perform update using supabase admin client with better error handling
        try:
            logger.info(f" Updating user {user_id} with payload: {payload}")
            supabase_admin.table("users").update(payload).eq("id", user_id).execute()
            logger.info(f" Update successful")
        except Exception as update_err:
            # If location column doesn't exist, try without it (fallback)
            if 'location' in str(update_err).lower() and 'location' in payload:
                logger.warning(f" Location column not found, retrying without it")
                payload.pop('location')
                supabase_admin.table("users").update(payload).eq("id", user_id).execute()
            else:
                logger.error(f" Update failed: {update_err}")
                raise

        # Re-fetch user row
        user_data = supabase_admin.table("users").select("*").eq("id", user_id).single().execute()
        if not user_data.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        logger.info(f" Profile updated successfully")
        return UserResponse(**user_data.data)

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f" Unexpected error: {e}")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(e))


@router.post("/logout")
async def logout():
    """
    Logout current user - SIMPLIFIED VERSION
    """
    try:
        print(f"🔴 [LOGOUT] Logout request received")
        
        # For now, just return success - the frontend will clear tokens
        # In a real implementation, you might want to invalidate the token
        # But since we're using JWT tokens, clearing on client side is sufficient
        
        print(f"✅ [LOGOUT] Logout successful")
        return {"success": True, "message": "Logged out successfully"}
        
    except Exception as e:
        print(f"❌ [LOGOUT] Error: {str(e)}")
        # Always return success for logout - we want frontend to clear tokens regardless
        return {"success": True, "message": "Logged out successfully"}


@router.post("/social-login", response_model=AuthResponse)
async def social_login(payload: SocialLoginRequest):
    """Handle social login - FIXED VERSION with timeout protection"""
    import asyncio
    from uuid import uuid4
    
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"\n Email: {payload.profile.get('email')}")
        
        email = payload.profile.get("email")
        if not email:
            raise HTTPException(status_code=400, detail="Email required")
        
        full_name = payload.profile.get("name") or payload.profile.get("full_name")
        avatar = payload.profile.get("picture")
        phone = payload.profile.get("phone")
        
        user_id = None
        existing_user = None
        
        # Reset admin client authentication to ensure service role
        try:
            supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
            logger.info(f" Reset admin client auth to service role")
        except Exception as auth_e:
            logger.warning(f" Could not reset admin auth: {auth_e}")
        
        # Check if user exists
        try:
            logger.info(f" Checking if user exists: {email}")
            result = supabase_admin.table("users").select("*").eq("email", email).execute()
            
            if result.data and len(result.data) > 0:
                existing_user = result.data[0]
                user_id = existing_user["id"]
                logger.info(f" Existing user: {user_id}")
        except Exception as e:
            logger.warning(f" Error checking existing user: {e}")
            # Retry with a fresh admin client (avoid mutating globals)
            try:
                from app.database import get_supabase_admin
                fresh_admin = get_supabase_admin()
                fresh_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                logger.info(f" Retrying user lookup with fresh admin client...")

                result = fresh_admin.table("users").select("*").eq("email", email).execute()
                if result.data and len(result.data) > 0:
                    existing_user = result.data[0]
                    user_id = existing_user["id"]
                    logger.info(f" Existing user found after retry: {user_id}")
            except Exception as retry_e:
                logger.error(f" Failed to check user even after retry: {retry_e}")
                # Continue with new user creation
        
        # Update existing user with onboarding data if provided
        if user_id and (payload.full_name or payload.phone_number or payload.location is not None or payload.onboarding_completed is not None):
            update_payload = {}
            if payload.full_name:
                update_payload["full_name"] = payload.full_name
            if payload.phone_number:
                update_payload["phone_number"] = payload.phone_number
            if payload.location is not None:
                update_payload["location"] = payload.location
            if payload.onboarding_completed is not None:
                update_payload["onboarding_completed"] = payload.onboarding_completed
            if payload.user_type:
                update_payload["user_type"] = payload.user_type

            try:
                supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                supabase_admin.table("users").update(update_payload).eq("id", user_id).execute()
                logger.info(f" Updated existing user with onboarding data: {user_id}")
            except Exception as update_e:
                logger.error(f" Failed to update existing user: {update_e}")
                # Continue without failing the login
        
        # Extract onboarding fields for Google users
        onboarding_full_name = payload.full_name or full_name
        onboarding_phone = payload.phone_number or phone
        onboarding_location = payload.location
        onboarding_completed = payload.onboarding_completed or False

        # Resolve a safe display name — never store empty/NULL for OAuth users
        # Priority: explicit full_name → email local-part → 'User'
        safe_name = onboarding_full_name
        if not safe_name or not str(safe_name).strip():
            safe_name = (email or "").split("@", 1)[0] or "User"

        # Create new user if needed
        if not user_id:
            user_id = str(uuid4())
            new_user_data = {
                "id": user_id,
                "email": email,
                "full_name": safe_name,
                "phone_number": onboarding_phone,
                "user_type": payload.user_type or "tenant",
                "avatar_url": avatar,
                "trust_score": 50,
                "verification_status": "partial",
                "onboarding_completed": onboarding_completed,
                "location": onboarding_location,
                "created_at": datetime.now().isoformat(),
            }
            
            try:
                # Reset auth before user creation
                supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                supabase_admin.table("users").insert(new_user_data).execute()
                logger.info(f" Created user: {user_id}")
            except Exception as insert_e:
                logger.error(f" Error creating user: {insert_e}")
                # Retry with a fresh admin client (avoid mutating globals)
                try:
                    from app.database import get_supabase_admin
                    fresh_admin = get_supabase_admin()
                    fresh_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                    logger.info(f" Retrying user creation with fresh admin client...")

                    fresh_admin.table("users").insert(new_user_data).execute()
                    logger.info(f" Created user after retry: {user_id}")
                except Exception as retry_e:
                    logger.error(f" Failed to create user even after retry: {retry_e}")
                    raise HTTPException(status_code=500, detail="Failed to create user in database")
        
        # ⚡ GENERATE TOKEN IMMEDIATELY (before fetch)
        logger.info(f" Generating JWT token for user: {user_id}")
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = jwt.encode(
            {"sub": user_id, "email": email, "exp": int(expire.timestamp())},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        logger.info(f" Token generated")
        
        # Try to fetch user data (with timeout)
        user_response = None
        if existing_user:
            user_response = UserResponse(**existing_user)
            logger.info(f" Using existing user data")
        else:
            try:
                logger.info(f" Attempting to fetch user data with 5s timeout...")
                
                # 5 second timeout
                async def fetch():
                    # Reset auth before fetch
                    supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                    r = supabase_admin.table("users").select("*").eq("id", user_id).execute()
                    return r.data[0] if r.data else None
                
                user_data = await asyncio.wait_for(fetch(), timeout=5.0)
                if user_data:
                    user_response = UserResponse(**user_data)
                    logger.info(f" Fetched user data: {user_id}")
                else:
                    # Fallback: create user response from new_user_data
                    user_response = UserResponse(
                        id=user_id,
                        email=email,
                        full_name=full_name or "",
                        phone_number=phone,
                        user_type=payload.user_type or "tenant",
                        avatar_url=avatar,
                        trust_score=50,
                        verification_status="partial",
                        onboarding_completed=False,
                        created_at=datetime.now().isoformat()
                    )
                    logger.info(f" Using fallback user data: {user_id}")
                    
            except asyncio.TimeoutError:
                logger.warning(f" Timeout fetching user data, using fallback")
                # Fallback: create user response from new_user_data
                user_response = UserResponse(
                    id=user_id,
                    email=email,
                    full_name=full_name or "",
                    phone_number=phone,
                    user_type=payload.user_type or "tenant",
                    avatar_url=avatar,
                    trust_score=50,
                    verification_status="partial",
                    onboarding_completed=False,
                    created_at=datetime.now().isoformat()
                )
            except Exception as fetch_e:
                logger.error(f" Error fetching user data: {fetch_e}")
                # Fallback: create user response from new_user_data
                user_response = UserResponse(
                    id=user_id,
                    email=email,
                    full_name=full_name or "",
                    phone_number=phone,
                    user_type=payload.user_type or "tenant",
                    avatar_url=avatar,
                    trust_score=50,
                    verification_status="partial",
                    onboarding_completed=False,
                    created_at=datetime.now().isoformat()
                )
                logger.info(f" Using fallback user data due to error: {user_id}")
        
        logger.info(f" SUCCESS: user_id={user_id}")
        
        return AuthResponse(
            success=True,
            user=user_response,
            access_token=access_token,
            message="Social login successful"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f" ERROR: {e}")
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=str(e))






@router.post("/sync-user-profile")
async def sync_user_profile(profile: SyncUserProfile):
    """
    Sync user profile from Supabase Auth to public.users table.
    This ensures user_type is set correctly, bypassing trigger timing issues.
    
    No authentication required - called during signup before user has session.
    
    NOTE: Admin users should NOT use this endpoint - admin profiles must be 
    pre-registered by system administrators.
    """
    try:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"\n{'='*80}")
        logger.info(f"REQUEST RECEIVED")
        logger.info(f"{'='*80}")
        logger.info(f"Syncing user: {profile.email}")
        logger.info(f"User type: {profile.user_type}")
        logger.info(f"User ID: {profile.user_id}")
        logger.info(f"First Name: {profile.first_name}")
        logger.info(f"Last Name: {profile.last_name}")
        
        # ✅ IMPORTANT: Prevent admin profile sync - admins must be pre-registered
        if profile.user_type == 'admin':
            logger.warning(f"Admin sync endpoint called - this should not happen!")
            logger.info(f"Admin accounts must be pre-registered in the database")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin profiles cannot be synced via this endpoint. Admin accounts must be pre-registered by system administrators."
            )
        
        # ✅ AUTH-05 FIX: Check for duplicate email with different user ID
        logger.info(f"Checking for duplicate email...")
        try:
            duplicate_check = supabase_admin.table("users").select(
                "id, user_type, email"
            ).eq(
                "email", profile.email.lower()
            ).neq(
                "id", profile.user_id
            ).execute()
            
            if duplicate_check.data and len(duplicate_check.data) > 0:
                existing_user = duplicate_check.data[0]
                existing_role = existing_user.get('user_type')
                is_role_conflict = existing_role != profile.user_type
                
                logger.warning(f"EMAIL CONFLICT DETECTED:")
                logger.warning(f"   New user ID: {profile.user_id}")
                logger.warning(f"   New user type: {profile.user_type}")
                logger.warning(f"   Existing user ID: {existing_user.get('id')}")
                logger.warning(f"   Existing user type: {existing_role}")
                logger.warning(f"   Email: {profile.email}")
                logger.warning(f"   Is role conflict: {is_role_conflict}")
                
                # Build appropriate error message
                if is_role_conflict:
                    # AUTH-05: Different role attempt (e.g., tenant → landlord)
                    error_detail = f"Email '{profile.email}' is already registered as a {existing_role}. Cannot create a {profile.user_type} account with this email."
                    logger.error(f"ROLE CONFLICT: Trying {profile.user_type}, existing is {existing_role}")
                else:
                    # Duplicate: Same role with different OAuth UID (shouldn't happen often)
                    error_detail = f"Email '{profile.email}' is already registered as a {existing_role} account."
                    logger.error(f"DUPLICATE ACCOUNT: Both are {existing_role}")
                
                # Return 409 Conflict - cannot create duplicate email account.
                # Send a structured detail so the frontend can route the user to
                # the right role-aware "account exists" page.
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "message": error_detail,
                        "existing_user_id": existing_user.get("id"),
                        "existing_type": existing_role,
                        "requested_type": profile.user_type,
                        "email": profile.email,
                        "is_role_conflict": is_role_conflict,
                    },
                )
        except Exception as e:
            if isinstance(e, HTTPException):
                raise  # Re-raise our 409 Conflict error
            else:
                logger.warning(f"Error checking for duplicates: {e}")
                # Continue - this might be a temporary DB issue
        
        # Prepare user record with correct user_type
        user_record = {
            "id": profile.user_id,
            "email": profile.email,
            "first_name": profile.first_name,
            "last_name": profile.last_name,
            "full_name": profile.full_name,
            "user_type": profile.user_type,  # ✅ Explicitly set
            "auth_provider": profile.auth_provider,
            "email_verified": False,
            "onboarding_completed": False,
            "onboarding_step": 1 if profile.user_type == 'landlord' else 4,
            "verification_status": 'pending' if profile.user_type == 'landlord' else 'approved',
            "trust_score": 50,
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat()
        }
        
        # Use UPSERT to handle both new and existing users
        logger.info(f"Upserting user record...")
        result = supabase_admin.table("users").upsert(
            user_record,
            on_conflict="id"  # Update if user already exists
        ).execute()
        
        if not result.data:
            logger.warning(f"No data returned from upsert")
        
        # Create appropriate profile table
        logger.info(f"Creating profile table for {profile.user_type}...")
        if profile.user_type == 'landlord':
            supabase_admin.table('landlord_profiles').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            logger.info(f"Created landlord_profile")
            
        elif profile.user_type == 'tenant':
            supabase_admin.table('tenant_profiles').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            logger.info(f"Created tenant_profile")
            
        elif profile.user_type == 'admin':
            supabase_admin.table('admins').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            logger.info(f"Created admin profile")
        
        # Also update auth.users metadata to keep in sync
        logger.info(f"Updating auth metadata...")
        try:
            supabase_admin.auth.admin.update_user_by_id(
                profile.user_id,
                {
                    "user_metadata": {
                        "user_type": profile.user_type,
                        "first_name": profile.first_name,
                        "last_name": profile.last_name,
                        "full_name": profile.full_name
                    }
                }
            )
            logger.info(f"Auth metadata updated")
        except Exception as meta_error:
            logger.warning(f"Could not update auth metadata: {meta_error}")
            # Non-critical, continue
        
        logger.info(f"User profile synced successfully!")
        
        return {
            "success": True,
            "user_id": profile.user_id,
            "user_type": profile.user_type,
            "message": f"{profile.user_type.capitalize()} profile created successfully"
        }
        
    except Exception as e:
        logger.error(f" Error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync user profile: {str(e)}"
        )