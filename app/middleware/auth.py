"""
Authentication middleware for JWT token verification
"""
from fastapi import Depends, HTTPException, status
# from fastapi.security import HTTPBearer, HTTPAuthCredentials
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from jose import JWTError, jwt
from app.config import settings
from app.database import supabase_admin
from typing import Optional
from datetime import datetime

from jose import ExpiredSignatureError


security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)  # Don't raise error if no token


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify JWT token and return current user
    """
    token = credentials.credentials
    print(f"🔍 [get_current_user] Received token (first 20): {token[:20]}...{token[-10:] if len(token) > 30 else ''}")
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Verify token with Supabase
        print("🔍 [get_current_user] Trying Supabase token validation...")
        user_response = supabase_admin.auth.get_user(token)
        
        if not user_response or not user_response.user:
            # Fallthrough to JWT fallback
            print("⚠️ [get_current_user] Supabase user lookup failed, falling back to internal JWT")
            raise Exception("Supabase user lookup failed")
        
        user_id = user_response.user.id
        print(f"✅ [get_current_user] Supabase token valid, user_id: {user_id}")
        print(f"📧 [get_current_user] User email: {user_response.user.email}")
        print(f"👤 [get_current_user] User metadata: {user_response.user.user_metadata}")
        
        # Fetch complete user profile from database
        response = supabase_admin.table("users").select(
            "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
        ).eq("id", user_id).single().execute()
        
        if not response.data:
            print("❌ [get_current_user] User profile not found in database")
            raise credentials_exception
        
        print("✅ [get_current_user] Supabase validation successful")
        return response.data
        
    except Exception as e:
        print(f"⚠️ [get_current_user] Supabase validation failed: {e}")
        # Try fallback: verify internal JWT issued by this API
        try:
            print("🔍 [get_current_user] Trying internal JWT validation...")
            payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
            user_id = payload.get("sub") or payload.get("user_id")
            if not user_id:
                print("❌ [get_current_user] JWT payload missing user_id")
                raise credentials_exception

            print(f"✅ [get_current_user] Internal JWT valid, user_id: {user_id}")
            response = supabase_admin.table("users").select(
                "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
            ).eq("id", user_id).single().execute()

            if not response.data:
                print("❌ [get_current_user] User profile not found in database")
                raise credentials_exception

            print("✅ [get_current_user] Internal JWT validation successful")
            return response.data
        except ExpiredSignatureError:
            print("❌ [get_current_user] Internal JWT expired")
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token has expired",
                headers={"WWW-Authenticate": "Bearer"},
            )
        except JWTError:
            raise credentials_exception
    except Exception as e:
        print(f"Auth error: {e}")
        raise credentials_exception


async def get_current_tenant(current_user: dict = Depends(get_current_user)):
    """Verify user is a tenant"""
    if current_user.get("user_type") != "tenant":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only tenants can access this resource"
        )
    return current_user


async def get_current_landlord(current_user: dict = Depends(get_current_user)):
    """Verify user is a landlord"""
    user_type = current_user.get("user_type")
    
    # Check if user_type is landlord or if user has a landlord profile
    if user_type != "landlord":
        # Check if user has a landlord profile as fallback
        try:
            landlord_profile = supabase_admin.table("landlord_profiles").select("*").eq("id", current_user["id"]).execute()
            if not landlord_profile.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only landlords can access this resource"
                )
        except Exception as e:
            print(f"❌ [get_current_landlord] Error checking landlord profile: {e}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Only landlords can access this resource"
            )
    
    return current_user


async def get_current_admin(current_user: dict = Depends(get_current_user)):
    """Verify user is an admin"""
    if current_user.get("user_type") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only admins can access this resource"
        )
    
    # Additional check: Verify admin exists in admins table
    try:
        admin_response = supabase_admin.table("admins").select("*").eq("id", current_user["id"]).execute()
        if not admin_response.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin profile not found"
            )
    except Exception as e:
        print(f"Admin profile check error: {e}")
        # Continue anyway for now, but log the error
    
    return current_user


async def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)):
    """
    Get current user if token is provided, otherwise return None
    Used for endpoints that work with or without authentication
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    
    try:
        # Verify token with Supabase
        user_response = supabase_admin.auth.get_user(token)
        
        if not user_response or not user_response.user:
            return None
        
        user_id = user_response.user.id
        
        # Fetch complete user profile from database
        response = supabase_admin.table("users").select(
            "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
        ).eq("id", user_id).single().execute()
        
        if not response.data:
            return None
        
        return response.data
        
    except Exception as e:
        print(f"Optional auth error (non-critical): {e}")
        return None
