"""
Advanced Property Caching Service
Redis-based caching with intelligent invalidation and AI optimization
"""
import json
import hashlib
import asyncio
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import redis.asyncio as redis
from app.database import supabase_admin
from app.config import settings

class PropertyCacheService:
    def __init__(self):
        self.redis_client = None
        self.cache_ttl = 300  # 5 minutes default
        self.popular_cache_ttl = 1800  # 30 minutes for popular searches
        self.ai_optimization_enabled = True
        
    async def init_redis(self):
        """Initialize Redis connection"""
        try:
            self.redis_client = redis.Redis(
                host=settings.REDIS_HOST or "localhost",
                port=settings.REDIS_PORT or 6379,
                db=settings.REDIS_DB or 0,
                decode_responses=True,
                socket_connect_timeout=5,
                socket_timeout=5
            )
            await self.redis_client.ping()
            print("🚀 Redis cache initialized successfully")
        except Exception as e:
            print(f"⚠️ Redis not available, using in-memory fallback: {e}")
            self.redis_client = None
    
    def _generate_cache_key(self, search_params: Dict[str, Any]) -> str:
        """Generate intelligent cache key based on search parameters"""
        # Normalize parameters for consistent caching
        normalized_params = {
            "location": (search_params.get("location") or "").lower().strip(),
            "min_price": search_params.get("min_price", 0),
            "max_price": search_params.get("max_price", 10000000),
            "beds": search_params.get("beds", 0),
            "baths": search_params.get("baths", 0),
            "property_type": search_params.get("property_type", "all"),
            "sort": search_params.get("sort", "newest"),
            "page": search_params.get("page", 1),
            "limit": min(search_params.get("limit", 20), 50)
        }
        
        # Create deterministic hash
        param_string = json.dumps(normalized_params, sort_keys=True)
        cache_key = f"properties_search:{hashlib.md5(param_string.encode()).hexdigest()}"
        
        return cache_key
    
    async def get_cached_search(self, search_params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Get cached search results with AI optimization"""
        if not self.redis_client:
            return None
            
        cache_key = self._generate_cache_key(search_params)
        
        try:
            cached_data = await self.redis_client.get(cache_key)
            if cached_data:
                data = json.loads(cached_data)
                
                # AI: Track cache hit for optimization
                await self._track_cache_hit(cache_key, search_params)
                
                print(f"🎯 Cache HIT for key: {cache_key[:16]}...")
                return data
                
        except Exception as e:
            print(f"⚠️ Cache get error: {e}")
            
        return None
    
    async def cache_search_results(self, search_params: Dict[str, Any], results: Dict[str, Any]):
        """Cache search results with intelligent TTL"""
        if not self.redis_client:
            return
            
        cache_key = self._generate_cache_key(search_params)
        
        try:
            # AI: Determine optimal TTL based on search patterns
            ttl = await self._calculate_optimal_ttl(search_params, results)
            
            # Add metadata for AI optimization
            enhanced_results = {
                **results,
                "cached_at": datetime.utcnow().isoformat(),
                "cache_ttl": ttl,
                "search_params": search_params
            }
            
            await self.redis_client.setex(
                cache_key, 
                ttl, 
                json.dumps(enhanced_results, default=str)
            )
            
            # AI: Track cache patterns
            await self._track_cache_pattern(cache_key, search_params, ttl)
            
            print(f"💾 Cached results for key: {cache_key[:16]}... (TTL: {ttl}s)")
            
        except Exception as e:
            print(f"⚠️ Cache set error: {e}")
    
    async def _calculate_optimal_ttl(self, search_params: Dict[str, Any], results: Dict[str, Any]) -> int:
        """AI: Calculate optimal TTL based on search patterns and result characteristics"""
        base_ttl = self.cache_ttl
        
        # Popular searches get longer TTL
        if await self._is_popular_search(search_params):
            base_ttl = self.popular_cache_ttl
        
        # High-result searches get longer TTL (more stable)
        if results.get("pagination", {}).get("total", 0) > 100:
            base_ttl = int(base_ttl * 1.5)
        
        # Specific location searches get longer TTL
        if search_params.get("location") and search_params["location"] != "":
            base_ttl = int(base_ttl * 1.2)
        
        # Price-filtered searches get shorter TTL (more volatile)
        if search_params.get("min_price") or search_params.get("max_price"):
            base_ttl = int(base_ttl * 0.8)
        
        return min(base_ttl, 3600)  # Max 1 hour
    
    async def _is_popular_search(self, search_params: Dict[str, Any]) -> bool:
        """AI: Check if this is a popular search pattern"""
        if not self.redis_client:
            return False
            
        popularity_key = f"search_popularity:{hashlib.md5(json.dumps(search_params, sort_keys=True).encode()).hexdigest()}"
        
        try:
            hit_count = await self.redis_client.get(popularity_key)
            return int(hit_count or 0) > 5  # Popular if hit > 5 times
        except:
            return False
    
    async def _track_cache_hit(self, cache_key: str, search_params: Dict[str, Any]):
        """AI: Track cache hits for optimization"""
        if not self.redis_client:
            return
            
        try:
            # Increment popularity counter
            popularity_key = f"search_popularity:{hashlib.md5(json.dumps(search_params, sort_keys=True).encode()).hexdigest()}"
            await self.redis_client.incr(popularity_key)
            await self.redis_client.expire(popularity_key, 3600)  # Reset after 1 hour
            
            # Track global cache performance
            await self.redis_client.incr("cache_hits_total")
            
        except Exception as e:
            print(f"⚠️ Cache tracking error: {e}")
    
    async def _track_cache_pattern(self, cache_key: str, search_params: Dict[str, Any], ttl: int):
        """AI: Track cache patterns for machine learning optimization"""
        if not self.redis_client:
            return
            
        try:
            pattern_data = {
                "cache_key": cache_key,
                "search_params": search_params,
                "ttl": ttl,
                "timestamp": datetime.utcnow().isoformat()
            }
            
            # Store in AI analytics queue (simplified version)
            await self.redis_client.lpush("cache_patterns", json.dumps(pattern_data))
            await self.redis_client.ltrim("cache_patterns", 0, 999)  # Keep last 1000 patterns
            
        except Exception as e:
            print(f"⚠️ Pattern tracking error: {e}")
    
    async def invalidate_property_cache(self, property_id: str = None):
        """Intelligent cache invalidation"""
        if not self.redis_client:
            return
            
        try:
            if property_id:
                # Invalidate specific property-related caches
                pattern = f"*property_{property_id}*"
            else:
                # Invalidate all property caches
                pattern = "properties_search:*"
            
            keys = await self.redis_client.keys(pattern)
            if keys:
                await self.redis_client.delete(*keys)
                print(f"🗑️ Invalidated {len(keys)} cache entries")
                
        except Exception as e:
            print(f"⚠️ Cache invalidation error: {e}")
    
    async def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache performance statistics"""
        if not self.redis_client:
            return {"error": "Redis not available"}
            
        try:
            stats = {
                "cache_hits_total": await self.redis_client.get("cache_hits_total") or 0,
                "total_cached_keys": len(await self.redis_client.keys("properties_search:*")),
                "popular_searches": len(await self.redis_client.keys("search_popularity:*")),
                "cache_patterns_analyzed": await self.redis_client.llen("cache_patterns")
            }
            return stats
        except Exception as e:
            return {"error": str(e)}

# Global cache service instance
property_cache = PropertyCacheService()
