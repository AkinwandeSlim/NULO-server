"""
Supabase database client setup
"""
from supabase import create_client, Client
from app.config import settings
from functools import lru_cache


@lru_cache()
def get_supabase_client() -> Client:
    """Get Supabase client instance (anon key)"""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@lru_cache()
def get_supabase_admin() -> Client:
    """Get Supabase admin client (service role key)"""
    return create_client(settings.SUPABASE_URL, settings.SUPABASE_SERVICE_KEY)


# Global instances
supabase: Client = get_supabase_client()
supabase_admin: Client = get_supabase_admin()
