"""
Authentication routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
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

@router.post("/register", response_model=AuthResponse)
async def register(user_data: UserRegister):
    """
    Register a new user (tenant or landlord) with landlord verification support
    """
    try:
        print(f"\n [REGISTER] Starting registration for: {user_data.email}")
        
        # Create auth user with Supabase
        print(f" [REGISTER] Creating Supabase auth user...")
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
            "options": {
                "data": {
                    "full_name": user_data.full_name or "User",
                    "user_type": user_data.user_type or "tenant",
                    "phone_number": user_data.phone_number or None,
                }
            }
        })
        
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


@router.post("/login", response_model=AuthResponse)
async def login(credentials: UserLogin):
    """
    Login user with email and password
    """
    try:
        print(f"\n🔵 [LOGIN] Login attempt for: {credentials.email}")
        
        # Authenticate with Supabase Admin (to bypass RLS)
        print(f"🔐 [LOGIN] Authenticating with Supabase...")
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password,
        })
        
        print(f"📥 [LOGIN] Auth response received: {auth_response}")
        
        if not auth_response.user:
            print(f"❌ [LOGIN] No user in auth response")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user_id = auth_response.user.id
        print(f"✅ [LOGIN] User authenticated: {user_id}")
        
        # Fetch user profile
        print(f"🔍 [LOGIN] Fetching user profile...")
        user_data = supabase_admin.table("users").select(
            "id, email, full_name, avatar_url, user_type, trust_score, verification_status, created_at"
        ).eq("id", user_id).single().execute()
        
        if not user_data.data:
            print(f"❌ [LOGIN] User profile not found")
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
        
        # Update last login - REMOVED TO PREVENT HANGING
        # supabase_admin.table("users").update({
        #     "last_login_at": datetime.now().isoformat()
        # }).eq("id", user_id).execute()
        
        print(f"📦 [LOGIN] User data: {user_data.data}")
        
        # Add missing location field if not present
        if 'location' not in user_data.data:
            user_data.data['location'] = None
        
        user_response = UserResponse(**user_data.data)
        
        print(f"✅ [LOGIN] Login successful, returning response")
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
            print(f"📝 [UPDATE PROFILE] Updating user {user_id} with payload: {payload}")
            supabase_admin.table("users").update(payload).eq("id", user_id).execute()
            print(f"✅ [UPDATE PROFILE] Update successful")
        except Exception as update_err:
            # If location column doesn't exist, try without it (fallback)
            if 'location' in str(update_err).lower() and 'location' in payload:
                print(f"⚠️ [UPDATE PROFILE] Location column not found, retrying without it")
                payload.pop('location')
                supabase_admin.table("users").update(payload).eq("id", user_id).execute()
            else:
                print(f"❌ [UPDATE PROFILE] Update failed: {update_err}")
                raise

        # Re-fetch user row
        user_data = supabase_admin.table("users").select("*").eq("id", user_id).single().execute()
        if not user_data.data:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

        print(f"✅ [UPDATE PROFILE] Profile updated successfully")
        return UserResponse(**user_data.data)

    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [UPDATE PROFILE] Unexpected error: {e}")
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
        print(f"\n🔍 [SOCIAL-LOGIN] Email: {payload.profile.get('email')}")
        
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
            print(f"✅ [SOCIAL-LOGIN] Reset admin client auth to service role")
        except Exception as auth_e:
            print(f"⚠️ [SOCIAL-LOGIN] Could not reset admin auth: {auth_e}")
        
        # Check if user exists
        try:
            print(f"🔍 [SOCIAL-LOGIN] Checking if user exists: {email}")
            result = supabase_admin.table("users").select("*").eq("email", email).execute()
            
            if result.data and len(result.data) > 0:
                existing_user = result.data[0]
                user_id = existing_user["id"]
                print(f"✅ [SOCIAL-LOGIN] Existing user: {user_id}")
        except Exception as e:
            print(f"⚠️ [SOCIAL-LOGIN] Error checking existing user: {e}")
            # Retry with a fresh admin client (avoid mutating globals)
            try:
                from app.database import get_supabase_admin
                fresh_admin = get_supabase_admin()
                fresh_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                print(f"🔄 [SOCIAL-LOGIN] Retrying user lookup with fresh admin client...")

                result = fresh_admin.table("users").select("*").eq("email", email).execute()
                if result.data and len(result.data) > 0:
                    existing_user = result.data[0]
                    user_id = existing_user["id"]
                    print(f"✅ [SOCIAL-LOGIN] Existing user found after retry: {user_id}")
            except Exception as retry_e:
                print(f"❌ [SOCIAL-LOGIN] Failed to check user even after retry: {retry_e}")
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
                print(f"✅ [SOCIAL-LOGIN] Updated existing user with onboarding data: {user_id}")
            except Exception as update_e:
                print(f"❌ [SOCIAL-LOGIN] Failed to update existing user: {update_e}")
                # Continue without failing the login
        
        # Extract onboarding fields for Google users
        onboarding_full_name = payload.full_name or full_name
        onboarding_phone = payload.phone_number or phone
        onboarding_location = payload.location
        onboarding_completed = payload.onboarding_completed or False

        # Create new user if needed
        if not user_id:
            user_id = str(uuid4())
            new_user_data = {
                "id": user_id,
                "email": email,
                "full_name": onboarding_full_name or "",
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
                print(f"✅ [SOCIAL-LOGIN] Created user: {user_id}")
            except Exception as insert_e:
                print(f"❌ [SOCIAL-LOGIN] Error creating user: {insert_e}")
                # Retry with a fresh admin client (avoid mutating globals)
                try:
                    from app.database import get_supabase_admin
                    fresh_admin = get_supabase_admin()
                    fresh_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                    print(f"🔄 [SOCIAL-LOGIN] Retrying user creation with fresh admin client...")

                    fresh_admin.table("users").insert(new_user_data).execute()
                    print(f"✅ [SOCIAL-LOGIN] Created user after retry: {user_id}")
                except Exception as retry_e:
                    print(f"❌ [SOCIAL-LOGIN] Failed to create user even after retry: {retry_e}")
                    raise HTTPException(status_code=500, detail="Failed to create user in database")
        
        # ⚡ GENERATE TOKEN IMMEDIATELY (before fetch)
        print(f"🔐 [SOCIAL-LOGIN] Generating JWT token for user: {user_id}")
        expire = datetime.utcnow() + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        access_token = jwt.encode(
            {"sub": user_id, "email": email, "exp": int(expire.timestamp())},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM
        )
        print(f"✅ [SOCIAL-LOGIN] Token generated")
        
        # Try to fetch user data (with timeout)
        user_response = None
        if existing_user:
            user_response = UserResponse(**existing_user)
            print(f"✅ [SOCIAL-LOGIN] Using existing user data")
        else:
            try:
                print(f"🔍 [SOCIAL-LOGIN] Attempting to fetch user data with 5s timeout...")
                
                # 5 second timeout
                async def fetch():
                    # Reset auth before fetch
                    supabase_admin.postgrest.auth(settings.SUPABASE_SERVICE_KEY)
                    r = supabase_admin.table("users").select("*").eq("id", user_id).execute()
                    return r.data[0] if r.data else None
                
                user_data = await asyncio.wait_for(fetch(), timeout=5.0)
                if user_data:
                    user_response = UserResponse(**user_data)
                    print(f"[SOCIAL-LOGIN] Fetched user data: {user_id}")
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
                    print(f"[SOCIAL-LOGIN] Using fallback user data: {user_id}")
                    
            except asyncio.TimeoutError:
                print(f"[SOCIAL-LOGIN] Timeout fetching user data, using fallback")
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
                print(f"[SOCIAL-LOGIN] Error fetching user data: {fetch_e}")
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
                print(f"[SOCIAL-LOGIN] Using fallback user data due to error: {user_id}")
        
        print(f"[SOCIAL-LOGIN] SUCCESS: user_id={user_id}")
        print(f"✅ [SOCIAL-LOGIN] SUCCESS: user_id={user_id}")
        
        return AuthResponse(
            success=True,
            user=user_response,
            access_token=access_token,
            message="Social login successful"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [SOCIAL-LOGIN] ERROR: {e}")
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
        print(f"\n{'='*80}")
        print(f"🔄 [SYNC-PROFILE] REQUEST RECEIVED")
        print(f"{'='*80}")
        print(f"🔄 [SYNC-PROFILE] Syncing user: {profile.email}")
        print(f"🎯 [SYNC-PROFILE] User type: {profile.user_type}")
        print(f"🆔 [SYNC-PROFILE] User ID: {profile.user_id}")
        print(f"📧 [SYNC-PROFILE] First Name: {profile.first_name}")
        print(f"📧 [SYNC-PROFILE] Last Name: {profile.last_name}")
        
        # ✅ IMPORTANT: Prevent admin profile sync - admins must be pre-registered
        if profile.user_type == 'admin':
            print(f"⚠️ [SYNC-PROFILE] Admin sync endpoint called - this should not happen!")
            print(f"💡 [SYNC-PROFILE] Admin accounts must be pre-registered in the database")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Admin profiles cannot be synced via this endpoint. Admin accounts must be pre-registered by system administrators."
            )
        
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
        print(f"💾 [SYNC-PROFILE] Upserting user record...")
        result = supabase_admin.table("users").upsert(
            user_record,
            on_conflict="id"  # Update if user already exists
        ).execute()
        
        if not result.data:
            print(f"⚠️ [SYNC-PROFILE] No data returned from upsert")
        
        # Create appropriate profile table
        print(f"📋 [SYNC-PROFILE] Creating profile table for {profile.user_type}...")
        if profile.user_type == 'landlord':
            supabase_admin.table('landlord_profiles').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            print(f"✅ [SYNC-PROFILE] Created landlord_profile")
            
        elif profile.user_type == 'tenant':
            supabase_admin.table('tenant_profiles').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            print(f"✅ [SYNC-PROFILE] Created tenant_profile")
            
        elif profile.user_type == 'admin':
            supabase_admin.table('admins').upsert({
                'id': profile.user_id,
                'created_at': datetime.now().isoformat(),
                'updated_at': datetime.now().isoformat()
            }, on_conflict="id").execute()
            print(f"✅ [SYNC-PROFILE] Created admin profile")
        
        # Also update auth.users metadata to keep in sync
        print(f"🔄 [SYNC-PROFILE] Updating auth metadata...")
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
            print(f"✅ [SYNC-PROFILE] Auth metadata updated")
        except Exception as meta_error:
            print(f"⚠️ [SYNC-PROFILE] Could not update auth metadata: {meta_error}")
            # Non-critical, continue
        
        print(f"✅ [SYNC-PROFILE] User profile synced successfully!")
        
        return {
            "success": True,
            "user_id": profile.user_id,
            "user_type": profile.user_type,
            "message": f"{profile.user_type.capitalize()} profile created successfully"
        }
        
    except Exception as e:
        print(f"❌ [SYNC-PROFILE] Error: {type(e).__name__}: {str(e)}")
        import traceback
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to sync user profile: {str(e)}"
        )