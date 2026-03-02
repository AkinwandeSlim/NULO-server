"""
Authentication middleware for JWT token verification
"""
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from jose import JWTError, jwt, ExpiredSignatureError
from app.config import settings
from app.database import supabase_admin
from typing import Optional
import asyncio
from app.middleware.token_cache import token_cache


security = HTTPBearer()
optional_security = HTTPBearer(auto_error=False)


async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """
    Verify JWT token and return current user.
    Flow:
    1. Check token cache (5-min TTL) — instant response
    2. Try Supabase validation with 5s timeout (not 10s)
    3. Fall back to internal JWT validation
    """
    token = credentials.credentials
    print(f"🔍 [get_current_user] Received token (first 20): {token[:20]}...{token[-10:] if len(token) > 30 else ''}")

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ─── PATH 0: Check token cache FIRST ───────────────────────────────────────
    cached_user = await token_cache.get(token)
    if cached_user:
        print(f"✅ [get_current_user] Token found in cache, returning cached user")
        return cached_user

    # ─── PATH 1: Supabase token validation (with REDUCED timeout) ───────────────
    print("🔍 [get_current_user] Trying Supabase token validation...")
    supabase_user_id = None

    try:
        user_response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: supabase_admin.auth.get_user(token)
            ),
            timeout=5.0  # REDUCED from 10s to 5s — fail fast
        )
        if user_response and user_response.user:
            supabase_user_id = user_response.user.id
            print(f"✅ [get_current_user] Supabase token valid, user_id: {supabase_user_id}")
            print(f"📧 [get_current_user] User email: {user_response.user.email}")
            print(f"👤 [get_current_user] User metadata: {user_response.user.user_metadata}")

    except asyncio.TimeoutError:
        print("⚠️ [get_current_user] Supabase auth timed out (>5s) — falling back to JWT")
    except Exception as e:
        print(f"⚠️ [get_current_user] Supabase validation failed: {e}")

    # If Supabase confirmed the user, fetch their DB profile
    if supabase_user_id:
        try:
            response = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: supabase_admin.table("users").select(
                    "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
                ).eq("id", supabase_user_id).single().execute()
            )
            if response.data:
                print("✅ [get_current_user] Supabase validation successful")
                user_data = response.data
                # Cache the result
                await token_cache.set(token, user_data)
                return user_data
            print("❌ [get_current_user] User profile not found in database")
            # Don't raise yet, try JWT fallback
        except HTTPException:
            raise
        except Exception as e:
            print(f"⚠️ [get_current_user] DB lookup after Supabase auth failed: {e}")
            # Fall through to internal JWT

    # ─── PATH 2: Internal JWT fallback (SKIP Supabase verification) ────────────
    print("🔍 [get_current_user] Trying internal JWT validation...")
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        user_id = payload.get("sub") or payload.get("user_id")
        if not user_id:
            print("❌ [get_current_user] JWT payload missing user_id")
            raise credentials_exception

        print(f"✅ [get_current_user] Internal JWT valid, user_id: {user_id}")
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin.table("users").select(
                "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
            ).eq("id", user_id).single().execute()
        )
        if response.data:
            user_data = response.data
            # Cache the result
            await token_cache.set(token, user_data)
            print("✅ [get_current_user] Internal JWT validation successful")
            return user_data
        else:
            print("❌ [get_current_user] User profile not found in database")
            raise credentials_exception

    except ExpiredSignatureError:
        print("❌ [get_current_user] Internal JWT expired")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except JWTError as jwt_err:
        print(f"❌ [get_current_user] JWT decode error: {jwt_err}")
        raise credentials_exception
    except HTTPException:
        raise
    except Exception as e:
        print(f"❌ [get_current_user] Auth error: {e}")
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

    if user_type != "landlord":
        # Fallback: check landlord_profiles table
        try:
            landlord_profile = supabase_admin.table("landlord_profiles").select("id").eq(
                "id", current_user["id"]
            ).execute()
            if not landlord_profile.data:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail="Only landlords can access this resource"
                )
        except HTTPException:
            raise
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

    try:
        admin_response = supabase_admin.table("admins").select("id").eq(
            "id", current_user["id"]
        ).execute()
        if not admin_response.data:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin profile not found"
            )
    except HTTPException:
        raise
    except Exception as e:
        print(f"Admin profile check error: {e}")

    return current_user


async def get_optional_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)
):
    """
    Get current user if token is provided, otherwise return None.
    Used for endpoints that work with or without authentication.
    """
    if not credentials:
        return None

    token = credentials.credentials

    try:
        user_response = await asyncio.wait_for(
            asyncio.get_event_loop().run_in_executor(
                None, lambda: supabase_admin.auth.get_user(token)
            ),
            timeout=10.0
        )
        if not user_response or not user_response.user:
            return None

        user_id = user_response.user.id
        response = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: supabase_admin.table("users").select(
                "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
            ).eq("id", user_id).single().execute()
        )
        return response.data if response.data else None

    except Exception as e:
        print(f"Optional auth error (non-critical): {e}")
        return None





















# """
# Authentication middleware for JWT token verification
# """
# from fastapi import Depends, HTTPException, status
# # from fastapi.security import HTTPBearer, HTTPAuthCredentials
# from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# from jose import JWTError, jwt
# from app.config import settings
# from app.database import supabase_admin
# from typing import Optional
# from datetime import datetime

# from jose import ExpiredSignatureError


# security = HTTPBearer()
# optional_security = HTTPBearer(auto_error=False)  # Don't raise error if no token


# async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)):
#     """
#     Verify JWT token and return current user
#     """
#     token = credentials.credentials
#     print(f"🔍 [get_current_user] Received token (first 20): {token[:20]}...{token[-10:] if len(token) > 30 else ''}")
#     credentials_exception = HTTPException(
#         status_code=status.HTTP_401_UNAUTHORIZED,
#         detail="Could not validate credentials",
#         headers={"WWW-Authenticate": "Bearer"},
#     )
    
#     try:
#         # Verify token with Supabase
#         print("🔍 [get_current_user] Trying Supabase token validation...")
#         user_response = supabase_admin.auth.get_user(token)
        
#         if not user_response or not user_response.user:
#             # Fallthrough to JWT fallback
#             print("⚠️ [get_current_user] Supabase user lookup failed, falling back to internal JWT")
#             raise Exception("Supabase user lookup failed")
        
#         user_id = user_response.user.id
#         print(f"✅ [get_current_user] Supabase token valid, user_id: {user_id}")
#         print(f"📧 [get_current_user] User email: {user_response.user.email}")
#         print(f"👤 [get_current_user] User metadata: {user_response.user.user_metadata}")
        
#         # Fetch complete user profile from database
#         response = supabase_admin.table("users").select(
#             "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
#         ).eq("id", user_id).single().execute()
        
#         if not response.data:
#             print("❌ [get_current_user] User profile not found in database")
#             raise credentials_exception
        
#         print("✅ [get_current_user] Supabase validation successful")
#         return response.data
        
#     except Exception as e:
#         print(f"⚠️ [get_current_user] Supabase validation failed: {e}")
#         # Try fallback: verify internal JWT issued by this API
#         try:
#             print("🔍 [get_current_user] Trying internal JWT validation...")
#             payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
#             user_id = payload.get("sub") or payload.get("user_id")
#             if not user_id:
#                 print("❌ [get_current_user] JWT payload missing user_id")
#                 raise credentials_exception

#             print(f"✅ [get_current_user] Internal JWT valid, user_id: {user_id}")
#             response = supabase_admin.table("users").select(
#                 "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
#             ).eq("id", user_id).single().execute()

#             if not response.data:
#                 print("❌ [get_current_user] User profile not found in database")
#                 raise credentials_exception

#             print("✅ [get_current_user] Internal JWT validation successful")
#             return response.data
#         except ExpiredSignatureError:
#             print("❌ [get_current_user] Internal JWT expired")
#             raise HTTPException(
#                 status_code=status.HTTP_401_UNAUTHORIZED,
#                 detail="Token has expired",
#                 headers={"WWW-Authenticate": "Bearer"},
#             )
#         except JWTError:
#             raise credentials_exception
#     except Exception as e:
#         print(f"Auth error: {e}")
#         raise credentials_exception


# async def get_current_tenant(current_user: dict = Depends(get_current_user)):
#     """Verify user is a tenant"""
#     if current_user.get("user_type") != "tenant":
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Only tenants can access this resource"
#         )
#     return current_user


# async def get_current_landlord(current_user: dict = Depends(get_current_user)):
#     """Verify user is a landlord"""
#     user_type = current_user.get("user_type")
    
#     # Check if user_type is landlord or if user has a landlord profile
#     if user_type != "landlord":
#         # Check if user has a landlord profile as fallback
#         try:
#             landlord_profile = supabase_admin.table("landlord_profiles").select("*").eq("id", current_user["id"]).execute()
#             if not landlord_profile.data:
#                 raise HTTPException(
#                     status_code=status.HTTP_403_FORBIDDEN,
#                     detail="Only landlords can access this resource"
#                 )
#         except Exception as e:
#             print(f"❌ [get_current_landlord] Error checking landlord profile: {e}")
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Only landlords can access this resource"
#             )
    
#     return current_user


# async def get_current_admin(current_user: dict = Depends(get_current_user)):
#     """Verify user is an admin"""
#     if current_user.get("user_type") != "admin":
#         raise HTTPException(
#             status_code=status.HTTP_403_FORBIDDEN,
#             detail="Only admins can access this resource"
#         )
    
#     # Additional check: Verify admin exists in admins table
#     try:
#         admin_response = supabase_admin.table("admins").select("*").eq("id", current_user["id"]).execute()
#         if not admin_response.data:
#             raise HTTPException(
#                 status_code=status.HTTP_403_FORBIDDEN,
#                 detail="Admin profile not found"
#             )
#     except Exception as e:
#         print(f"Admin profile check error: {e}")
#         # Continue anyway for now, but log the error
    
#     return current_user


# async def get_optional_current_user(credentials: Optional[HTTPAuthorizationCredentials] = Depends(optional_security)):
#     """
#     Get current user if token is provided, otherwise return None
#     Used for endpoints that work with or without authentication
#     """
#     if not credentials:
#         return None
    
#     token = credentials.credentials
    
#     try:
#         # Verify token with Supabase
#         user_response = supabase_admin.auth.get_user(token)
        
#         if not user_response or not user_response.user:
#             return None
        
#         user_id = user_response.user.id
        
#         # Fetch complete user profile from database
#         response = supabase_admin.table("users").select(
#             "id, email, full_name, user_type, trust_score, verification_status, avatar_url"
#         ).eq("id", user_id).single().execute()
        
#         if not response.data:
#             return None
        
#         return response.data
        
#     except Exception as e:
#         print(f"Optional auth error (non-critical): {e}")
#         return None
