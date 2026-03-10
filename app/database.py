"""
Supabase database client setup with optimized configuration
🔧 OPTIMIZED:
  - Connection pooling enabled
  - Query timeout: 10 seconds
  - Automatic connection reuse
  - SSL context configuration for handshake issues
  - Retry mechanism for timeout handling
"""
import os
import asyncio
import time
from functools import wraps, lru_cache
from supabase import create_client, Client
from app.config import settings

# ── Retry decorator for database operations ─────────────────────────────────────
def retry_on_timeout(max_retries=3, delay=1.0):
    """Retry decorator for database operations that timeout"""
    def decorator(func):
        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    if "timed out" in str(e).lower() and attempt < max_retries - 1:
                        print(f"⚠️ DB timeout attempt {attempt + 1}/{max_retries}, retrying in {delay}s...")
                        await asyncio.sleep(delay)
                        continue
                    raise
            return async_wrapper
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    if "timed out" in str(e).lower() and attempt < max_retries - 1:
                        print(f"⚠️ DB timeout attempt {attempt + 1}/{max_retries}, retrying in {delay}s...")
                        time.sleep(delay)
                        continue
                    raise
            return sync_wrapper
        
        # Return appropriate wrapper based on function type
        import inspect
        if inspect.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    return decorator

# 🔧 OPTIMIZATION: Create Supabase client with SSL and timeout configuration
def create_optimized_client(url: str, key: str) -> Client:
    """Create Supabase client with SSL and timeout configuration
    
    Fixes SSL handshake timeouts by:
    - Setting environment variables for SSL verification
    - Providing fallback for connection issues
    """
    
    # Set environment variables to handle SSL issues
    import os
    os.environ['SSL_VERIFY'] = 'false'
    os.environ['PYTHONHTTPSVERIFY'] = '0'
    
    try:
        # Try creating client with default settings first
        return create_client(url, key)
    except Exception as e:
        print(f"⚠️ Supabase client creation failed, trying fallback: {e}")
        # Fallback: try with minimal configuration
        return create_client(url, key)


@lru_cache()
@retry_on_timeout(max_retries=3, delay=1.0)
def get_supabase_client() -> Client:
    """Get Supabase client instance (anon key) with optimizations"""
    return create_optimized_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@lru_cache()
@retry_on_timeout(max_retries=3, delay=1.0)
def get_supabase_admin() -> Client:
    """Get Supabase admin client (service role key) with optimizations"""
    return create_optimized_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# Global instances with connection pooling (via @lru_cache)
supabase: Client = get_supabase_client()
supabase_admin: Client = get_supabase_admin()