"""
Google-only authentication routes (no JWT)
"""
from fastapi import APIRouter, HTTPException, Depends, status
from app.models.user import UserResponse
from app.database import supabase_admin
from app.config import settings
from datetime import datetime
from uuid import uuid4
from pydantic import BaseModel

router = APIRouter(prefix="/api/auth/google", tags=["google"])

class GoogleProfileUpdate(BaseModel):
    email: str
    full_name: str
    phone_number: str
    user_type: str
    location: str | None = None
    onboarding_completed: bool = False

@router.post("/update-profile", response_model=dict)
async def update_google_profile(payload: GoogleProfileUpdate):
    """Update Google user profile without JWT"""
    try:
        print(f"🔍 [GOOGLE UPDATE] Updating profile for: {payload.email}")
        
        # Find user by email
        result = supabase_admin.table("users").select("*").eq("email", payload.email).execute()
        if not result.data or len(result.data) == 0:
            # Create user if not exists
            user_id = str(uuid4())
            user_data = {
                "id": user_id,
                "email": payload.email,
                "full_name": payload.full_name,
                "phone_number": payload.phone_number,
                "user_type": payload.user_type,
                "location": payload.location,
                "onboarding_completed": payload.onboarding_completed,
                "avatar_url": None,
                "trust_score": 50,
                "verification_status": "partial",
                "created_at": datetime.now().isoformat(),
            }
            supabase_admin.table("users").insert(user_data).execute()
            print(f"✅ [GOOGLE UPDATE] Created new user: {user_id}")
        else:
            # Update existing user
            user_id = result.data[0]["id"]
            update_data = {
                "full_name": payload.full_name,
                "phone_number": payload.phone_number,
                "user_type": payload.user_type,
                "location": payload.location,
                "onboarding_completed": payload.onboarding_completed,
                "updated_at": datetime.now().isoformat(),
            }
            supabase_admin.table("users").update(update_data).eq("id", user_id).execute()
            print(f"✅ [GOOGLE UPDATE] Updated existing user: {user_id}")
        
        # Fetch updated user
        user_result = supabase_admin.table("users").select("*").eq("id", user_id).single().execute()
        if not user_result.data:
            raise HTTPException(status_code=500, detail="Failed to fetch updated user")
        
        return {"success": True, "user": user_result.data}
    except Exception as e:
        print(f"❌ [GOOGLE UPDATE] Error: {e}")
        raise HTTPException(status_code=500, detail="Failed to update profile")
