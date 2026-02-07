"""
Optimized Properties API Routes
Advanced caching, AI optimization, and performance monitoring
"""
from fastapi import APIRouter, HTTPException, Query, Depends, status
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any
from datetime import datetime
import asyncio
import time
import json

from app.middleware.auth import get_optional_current_user
from app.services.property_cache import property_cache
from app.services.property_optimizer import property_optimizer
from app.models.property import PropertySearch, PropertyResponse

router = APIRouter(prefix="/properties")

@router.get("/search-optimized")
async def search_properties_optimized(
    location: Optional[str] = Query(None, description="Location search"),
    min_price: Optional[float] = Query(None, ge=0, alias="min_budget"),
    max_price: Optional[float] = Query(None, ge=0, alias="max_budget"),
    beds: Optional[int] = Query(None, ge=0, alias="bedrooms"),
    baths: Optional[int] = Query(None, ge=1, alias="bathrooms"),
    property_type: Optional[str] = Query(None, description="Property type filter"),
    sort: str = Query("newest", regex="^(newest|price_low|price_high|featured)$", description="Sort order"),
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=50, description="Results per page"),
    current_user: Optional[Dict[str, Any]] = Depends(get_optional_current_user)
):
    """
    Ultra-optimized property search with AI enhancement and Redis caching
    """
    start_time = time.time()
    
    try:
        # 1. Normalize and validate search parameters
        search_params = {
            "location": location.strip() if location else None,
            "min_price": min_price or 0,
            "max_price": max_price or 10000000,
            "beds": beds or 0,
            "baths": baths or 0,
            "property_type": property_type or "all",
            "sort": sort,
            "page": page,
            "limit": min(limit, 50),  # Performance cap
            "user_id": current_user.get("id") if current_user else None
        }
        
        print(f"🚀 [OPTIMIZED_SEARCH] Request: {search_params}")
        
        # 2. Execute optimized search with AI enhancement
        results = await property_optimizer.optimize_search_query(search_params)
        
        # 3. Add performance metadata
        execution_time = time.time() - start_time
        results["performance"] = {
            **results.get("performance", {}),
            "total_execution_time": round(execution_time, 3),
            "cache_hit": execution_time < 0.1,  # Assume cache hit if very fast
            "optimized": True,
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # 4. Log performance metrics
        await _log_search_metrics(search_params, results, execution_time)
        
        print(f"✅ [OPTIMIZED_SEARCH] Completed in {execution_time:.3f}s - {len(results.get('properties', []))} results")
        
        return JSONResponse(
            content=results,
            headers={
                "X-Execution-Time": str(execution_time),
                "X-Cache-Hit": str(results["performance"]["cache_hit"]).lower(),
                "X-Results-Count": str(len(results.get("properties", [])))
            }
        )
        
    except Exception as e:
        print(f"❌ [OPTIMIZED_SEARCH] Error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Search optimization failed: {str(e)}"
        )

@router.get("/search-cache-stats")
async def get_search_cache_stats():
    """Get cache performance statistics"""
    try:
        stats = await property_cache.get_cache_stats()
        return {
            "cache_performance": stats,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get cache stats: {str(e)}"
        )

@router.post("/invalidate-cache")
async def invalidate_property_cache(
    property_id: Optional[str] = Query(None, description="Specific property ID to invalidate, or all if not provided")
):
    """Invalidate property cache (for admin use)"""
    try:
        await property_cache.invalidate_property_cache(property_id)
        return {
            "message": f"Cache invalidated for property {property_id}" if property_id else "All property cache invalidated",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Cache invalidation failed: {str(e)}"
        )

@router.get("/search-suggestions")
async def get_search_suggestions(
    query: str = Query(..., min_length=2, description="Search query for suggestions"),
    limit: int = Query(10, ge=1, le=20, description="Number of suggestions")
):
    """
    AI-powered search suggestions with caching
    """
    try:
        # This would integrate with an AI service for intelligent suggestions
        # For now, return basic location-based suggestions
        
        suggestions = await _generate_search_suggestions(query, limit)
        
        return {
            "query": query,
            "suggestions": suggestions,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate suggestions: {str(e)}"
        )

@router.get("/trending-searches")
async def get_trending_searches():
    """Get trending property searches based on cache analytics"""
    try:
        # This would analyze cache patterns to identify trending searches
        trending = await _get_trending_searches()
        
        return {
            "trending_searches": trending,
            "timestamp": datetime.utcnow().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get trending searches: {str(e)}"
        )

# Helper functions
async def _log_search_metrics(search_params: Dict[str, Any], results: Dict[str, Any], execution_time: float):
    """Log search metrics for AI optimization"""
    try:
        metrics = {
            "search_params": search_params,
            "result_count": len(results.get("properties", [])),
            "execution_time": execution_time,
            "cache_hit": results.get("performance", {}).get("cache_hit", False),
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # In production, this would go to a metrics system like Prometheus
        print(f"📊 [METRICS] {json.dumps(metrics)}")
        
    except Exception as e:
        print(f"⚠️ Metrics logging error: {e}")

async def _generate_search_suggestions(query: str, limit: int) -> list:
    """Generate AI-powered search suggestions"""
    # Basic implementation - in production, this would use ML
    common_locations = [
        "Lagos", "Abuja", "Port Harcourt", "Ikeja", "Victoria Island",
        "Lekki", "Ikoyi", "Ajah", "Maryland", "Surulere"
    ]
    
    suggestions = []
    query_lower = query.lower()
    
    for location in common_locations:
        if query_lower in location.lower():
            suggestions.append({
                "text": location,
                "type": "location",
                "count": 0  # Would come from analytics
            })
    
    return suggestions[:limit]

async def _get_trending_searches() -> list:
    """Get trending searches based on cache analytics"""
    # This would analyze cache patterns to identify trending searches
    # For now, return mock data
    return [
        {"query": "Lagos", "type": "location", "count": 156},
        {"query": "3 bedroom", "type": "property_type", "count": 89},
        {"query": "Ikoyi", "type": "location", "count": 67},
        {"query": "apartment", "type": "property_type", "count": 45}
    ]

# Initialize services on startup
async def init_property_services():
    """Initialize property optimization services"""
    await property_cache.init_redis()
    print("🚀 Property optimization services initialized")
