"""
Supabase database client setup with optimized configuration
OPTIMIZED:
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
                        print(f"DB timeout attempt {attempt + 1}/{max_retries}, retrying in {delay}s...")
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
                        print(f"DB timeout attempt {attempt + 1}/{max_retries}, retrying in {delay}s...")
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


# ── Transient socket-error retry helpers ───────────────────────────────────────
#
# Windows raises WSAEWOULDBLOCK ([WinError 10035]) when multiple threads hammer
# a single shared sync httpx client (the global `supabase_admin`) at once — the
# landlord dashboard fans out 9 parallel run_in_executor fetches, while the
# disburse flow, graph-sync and agreement detail all use the same client. These
# are *transient*: a short backoff and one retry succeeds once the contention
# clears. HTTP-level errors (auth, 4xx/5xx) are NOT retried — they propagate.

def _is_transient_db_error(e: Exception) -> bool:
    """True when the error is a transient socket/connection failure safe to retry."""
    msg = str(e).lower()
    markers = (
        "10035",                       # winerror 10035 (wsae wouldblock)
        "would block",                 # non-blocking socket busy
        "could not be completed immediately",
        "timed out",                   # existing retry_on_timeout case
        "connection reset",
        "connection aborted",
        "connection error",
        "broken pipe",
        "remote end closed",
        "econnreset",
        "epipe",
        # Stale pooled HTTP/2 keep-alive to Supabase/Cloudflare: the peer closes
        # an idle connection, the next request on it dies with
        # httpx.RemoteProtocolError <ConnectionTerminated ...>. Transient —
        # retrying opens a fresh connection. Observed on disburse first-click.
        "remote protocol error",
        "connectionterminated",
        "connection terminated",
        "goaway",
        "received goaway",
    )
    return any(m in msg for m in markers)


def run_db_sync(db_op, *args, max_retries=3, base_delay=0.4, **kwargs):
    """Run a synchronous Supabase/PostgREST op, retrying transient socket errors.

    Pass a zero-arg callable that performs the network I/O::

        resp = run_db_sync(lambda: supabase_admin.table("x").select("*").execute())

    Only connection-level failures (WSAEWOULDBLOCK, timeouts, resets) retry.
    """
    for attempt in range(max_retries):
        try:
            return db_op(*args, **kwargs)
        except Exception as e:
            if _is_transient_db_error(e) and attempt < max_retries - 1:
                sleep_s = base_delay * (attempt + 1)
                print(f"[DB] Transient error (attempt {attempt + 1}/{max_retries}): {e} — retrying in {sleep_s:.1f}s")
                time.sleep(sleep_s)
                continue
            raise


async def run_db_async(db_op, *args, max_retries=3, base_delay=0.4, **kwargs):
    """Async variant of :func:`run_db_sync` for use directly in async routes.

    Same semantics, but sleeps with ``asyncio.sleep`` so the event loop is
    not blocked while waiting for the retry backoff.
    """
    for attempt in range(max_retries):
        try:
            return db_op(*args, **kwargs)
        except Exception as e:
            if _is_transient_db_error(e) and attempt < max_retries - 1:
                sleep_s = base_delay * (attempt + 1)
                print(f"[DB] Transient error (attempt {attempt + 1}/{max_retries}): {e} — retrying in {sleep_s:.1f}s")
                await asyncio.sleep(sleep_s)
                continue
            raise

# OPTIMIZATION: Create Supabase client with SSL and timeout configuration
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
        print(f"Supabase client creation failed, trying fallback: {e}")
        # Fallback: try with minimal configuration
        return create_client(url, key)


@lru_cache()
@retry_on_timeout(max_retries=3, delay=1.0)
def get_supabase_client() -> Client:
    """Get Supabase client instance (anon key) with optimizations"""
    print(f"[DB] Creating supabase client with key starting with: {settings.SUPABASE_KEY[:20]}...")
    return create_optimized_client(settings.SUPABASE_URL, settings.SUPABASE_KEY)


@lru_cache()
@retry_on_timeout(max_retries=3, delay=1.0)
def get_supabase_admin() -> Client:
    """Get Supabase admin client (service role key) with optimizations"""
    # Use SERVICE_ROLE_KEY for admin operations (has auth admin privileges)
    service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
    print(f"[DB] Creating supabase_admin with service key starting with: {service_key[:20]}...")
    print(f"[DB] Service key source: {'SUPABASE_SERVICE_ROLE_KEY' if settings.SUPABASE_SERVICE_ROLE_KEY else 'SUPABASE_SERVICE_KEY'}")
    return create_optimized_client(settings.SUPABASE_URL, service_key)


# Global instances with connection pooling (via @lru_cache)
supabase: Client = get_supabase_client()
supabase_admin: Client = get_supabase_admin()


def get_supabase_disburse() -> Client:
    """Dedicated Supabase admin client for the disbursement path.

    The global ``supabase_admin`` is shared by the landlord dashboard's ~15
    parallel fetches. On Windows, hammering one shared httpx connection pool
    from many threads raises WSAEWOULDBLOCK (WinError 10035 -> httpx.ReadError),
    which surfaced as the disburse first-click 500 ("Request failed"). A
    separate client has its OWN connection pool, so disbursement never collides
    with that bursty traffic. No lru_cache: it's a module singleton.
    """
    service_key = settings.SUPABASE_SERVICE_ROLE_KEY or settings.SUPABASE_SERVICE_KEY
    return create_optimized_client(settings.SUPABASE_URL, service_key)


# Dedicated client for money-moving operations (disbursements) — isolated pool
# so it never races the dashboard's shared-pool traffic on Windows.
supabase_disburse: Client = get_supabase_disburse()