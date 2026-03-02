"""
Token caching middleware - Reduces repeated token validation calls
Caches validated tokens in-memory with TTL to avoid backend overload
"""
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
import asyncio
from functools import wraps

class TokenCache:
    """Simple in-memory token cache with TTL"""
    
    def __init__(self, ttl_seconds: int = 300):  # 5 minutes default
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Dict[str, Any]] = {}
        self.lock = asyncio.Lock()
    
    async def get(self, token: str) -> Optional[Dict[str, Any]]:
        """Get cached user data for token"""
        async with self.lock:
            if token in self.cache:
                entry = self.cache[token]
                # Check if expired
                if datetime.now() < entry['expires_at']:
                    print(f"💾 [TOKEN CACHE] Cache hit for token: {token[:20]}...")
                    return entry['data']
                else:
                    # Expired, remove it
                    del self.cache[token]
                    print(f"🔄 [TOKEN CACHE] Cache expired for token: {token[:20]}...")
            
            return None
    
    async def set(self, token: str, user_data: Dict[str, Any]) -> None:
        """Cache validated user data for token"""
        async with self.lock:
            self.cache[token] = {
                'data': user_data,
                'expires_at': datetime.now() + timedelta(seconds=self.ttl_seconds),
                'cached_at': datetime.now()
            }
            print(f"💾 [TOKEN CACHE] Cached token: {token[:20]}... (TTL: {self.ttl_seconds}s)")
    
    async def invalidate(self, token: str) -> None:
        """Invalidate cached token"""
        async with self.lock:
            if token in self.cache:
                del self.cache[token]
                print(f"🗑️ [TOKEN CACHE] Invalidated: {token[:20]}...")
    
    async def clear(self) -> None:
        """Clear entire cache"""
        async with self.lock:
            size = len(self.cache)
            self.cache.clear()
            print(f"🗑️ [TOKEN CACHE] Cleared {size} entries")
    
    async def stats(self) -> Dict[str, Any]:
        """Get cache statistics"""
        async with self.lock:
            return {
                'total_entries': len(self.cache),
                'ttl_seconds': self.ttl_seconds,
                'cached_at': datetime.now().isoformat()
            }


# Global token cache instance
token_cache = TokenCache(ttl_seconds=300)  # 5-minute TTL


async def with_token_cache(validation_func):
    """Decorator to add caching to token validation functions"""
    @wraps(validation_func)
    async def wrapper(token: str):
        # Check cache first
        cached_user = await token_cache.get(token)
        if cached_user:
            return cached_user
        
        # Not cached, validate
        user_data = await validation_func(token)
        
        # Cache the result
        if user_data:
            await token_cache.set(token, user_data)
        
        return user_data
    
    return wrapper
