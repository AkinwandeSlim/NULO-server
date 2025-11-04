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


security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)  # Don't raise error if no token


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify JWT token and return current user
    """
    token = credentials.credentials
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    try:
        # Verify token with Supabase
        user_response = supabase_admin.auth.get_user(token)
        
        if not user_response or not user_response.user:
            raise credentials_exception
        
        user_id = user_response.user.id
        
        # Fetch complete user profile from database
        response = supabase_admin.table("users").select(
            "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
        ).eq("id", user_id).single().execute()
        
        if not response.data:
            raise credentials_exception
        
        return response.data
        
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
    if current_user.get("user_type") != "landlord":
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
