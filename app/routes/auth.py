"""
Authentication routes
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.models.user import UserRegister, UserLogin, UserResponse, AuthResponse
from app.database import supabase, supabase_admin
from app.middleware.auth import get_current_user
from datetime import datetime

router = APIRouter(prefix="/auth")


@router.post("/register", response_model=AuthResponse)
async def register(user_data: UserRegister):
    """
    Register a new user (tenant or landlord)
    """
    try:
        # Create auth user with Supabase
        auth_response = supabase.auth.sign_up({
            "email": user_data.email,
            "password": user_data.password,
            "options": {
                "data": {
                    "full_name": user_data.full_name,
                    "user_type": user_data.user_type,
                    "phone_number": user_data.phone_number,
                }
            }
        })
        
        if not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to create user"
            )
        
        user_id = auth_response.user.id
        
        # Create user record in database
        user_record = {
            "id": user_id,
            "email": user_data.email,
            "phone_number": user_data.phone_number,
            "full_name": user_data.full_name,
            "user_type": user_data.user_type,
            "trust_score": 50,
            "verification_status": "partial",
        }
        
        supabase_admin.table("users").insert(user_record).execute()
        
        # TODO: Create type-specific record when tables exist
        # if user_data.user_type == "tenant":
        #     supabase_admin.table("tenants").insert({
        #         "id": user_id,
        #         "profile_completion": 0,
        #         "onboarding_completed": False,
        #     }).execute()
        # elif user_data.user_type == "landlord":
        #     supabase_admin.table("landlords").insert({
        #         "id": user_id,
        #         "guarantee_joined": False,
        #         "guarantee_contribution": 0,
        #     }).execute()
        
        # Prepare response
        user_response = UserResponse(
            id=user_id,
            email=user_data.email,
            full_name=user_data.full_name,
            avatar_url=None,
            user_type=user_data.user_type,
            trust_score=50,
            verification_status="partial",
            created_at=datetime.now(),
        )
        
        return AuthResponse(
            success=True,
            user=user_response,
            access_token=auth_response.session.access_token,
            message="Registration successful! Please check your email to verify your account."
        )
        
    except HTTPException:
        raise
    except Exception as e:
        error_message = str(e)
        # Extract Supabase error message if available
        if hasattr(e, 'message'):
            error_message = e.message
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Registration failed: {error_message}"
        )


@router.post("/login", response_model=AuthResponse)
async def login(credentials: UserLogin):
    """
    Login user with email and password
    """
    try:
        # Authenticate with Supabase Admin (to bypass RLS)
        auth_response = supabase_admin.auth.sign_in_with_password({
            "email": credentials.email,
            "password": credentials.password,
        })
        
        if not auth_response.user:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password"
            )
        
        user_id = auth_response.user.id
        
        # Fetch user profile
        user_data = supabase_admin.table("users").select(
            "id, email, full_name, avatar_url, user_type, trust_score, verification_status, created_at"
        ).eq("id", user_id).single().execute()
        
        if not user_data.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User profile not found"
            )
        
        # Update last login
        supabase_admin.table("users").update({
            "last_login_at": datetime.now().isoformat()
        }).eq("id", user_id).execute()
        
        # TODO: Fetch type-specific data when tables exist
        # profile_data = None
        # if user_data.data["user_type"] == "tenant":
        #     tenant_data = supabase_admin.table("tenants").select("*").eq("id", user_id).single().execute()
        #     profile_data = {"tenant_profile": tenant_data.data} if tenant_data.data else None
        # elif user_data.data["user_type"] == "landlord":
        #     landlord_data = supabase_admin.table("landlords").select("*").eq("id", user_id).single().execute()
        #     profile_data = {"landlord_profile": landlord_data.data} if landlord_data.data else None
        
        user_response = UserResponse(**user_data.data)
        
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
        
        # TODO: Fetch type-specific data when tables exist
        # profile_data = {}
        # if user_data.data["user_type"] == "tenant":
        #     tenant_data = supabase_admin.table("tenants").select("*").eq("id", user_id).single().execute()
        #     if tenant_data.data:
        #         profile_data["tenant_profile"] = tenant_data.data
        # elif user_data.data["user_type"] == "landlord":
        #     landlord_data = supabase_admin.table("landlords").select("*").eq("id", user_id).single().execute()
        #     if landlord_data.data:
        #         profile_data["landlord_profile"] = landlord_data.data
        
        return UserResponse(**user_data.data)
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/logout")
async def logout(current_user: dict = Depends(get_current_user)):
    """
    Logout current user
    """
    try:
        supabase.auth.sign_out()
        return {"success": True, "message": "Logged out successfully"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )
