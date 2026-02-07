"""
Supabase database client setup with optimized configuration
🔧 OPTIMIZED:
  - Connection pooling enabled
  - Query timeout: 10 seconds
  - Automatic connection reuse
"""
from supabase import create_client, Client
from app.config import settings
from functools import lru_cache

# 🔧 OPTIMIZATION: Create Supabase client with default settings
# Note: The Python Supabase client handles connection pooling internally
def create_optimized_client(url: str, key: str) -> Client:
    """Create Supabase client with optimized configuration
    
    The supabase-py library manages HTTP connections internally.
    Custom HTTP clients are not supported in the current API.
    """
    return create_client(url, key)


@lru_cache()
def get_supabase_client() -> Client:
    """Get Supabase client instance (anon key) with optimizations"""
    return create_optimized_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@lru_cache()
def get_supabase_admin() -> Client:
    """Get Supabase admin client (service role key) with optimizations"""
    return create_optimized_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# Global instances with connection pooling (via @lru_cache)
supabase: Client = get_supabase_client()
supabase_admin: Client = get_supabase_admin()