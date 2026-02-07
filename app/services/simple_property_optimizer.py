"""
Simple Property Optimizer - No Redis Required
Lightweight optimization using browser caching and smart query optimization
"""
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import json
import hashlib
from app.database import supabase_admin

class SimplePropertyOptimizer:
    def __init__(self):
        self.query_stats = {}
        self.optimization_enabled = True
        
    async def optimize_search_query(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize search query without Redis - focuses on database efficiency"""
        
        # 1. Build optimized query
        optimized_query = await self._build_optimized_query(search_params)
        
        # 2. Execute with performance monitoring
        start_time = datetime.now(timezone.utc)
        results = await self._execute_optimized_query(optimized_query)
        execution_time = (datetime.now(timezone.utc) - start_time).total_seconds()
        
        # 3. Add optimization metadata for frontend caching
        results["optimization"] = {
            "execution_time": round(execution_time, 3),
            "query_optimized": True,
            "cache_key": self._generate_cache_key(search_params),
            "client_cache_ttl": self._calculate_client_cache_ttl(search_params),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # 4. Log performance for monitoring
        await self._log_query_performance(search_params, execution_time, results)
        
        return results
    
    def _generate_cache_key(self, search_params: Dict[str, Any]) -> str:
        """Generate cache key for frontend use"""
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
        
        param_string = json.dumps(normalized_params, sort_keys=True)
        cache_key = f"nulo_search_{hashlib.md5(param_string.encode()).hexdigest()[:16]}"
        
        return cache_key
    
    def _calculate_client_cache_ttl(self, search_params: Dict[str, Any]) -> int:
        """Calculate optimal cache TTL for frontend (in seconds)"""
        base_ttl = 300  # 5 minutes
        
        # Popular searches get longer TTL
        if search_params.get("location") and search_params["location"] in ["lagos", "abuja", "port harcourt"]:
            base_ttl = 600  # 10 minutes
        
        # Price-filtered searches get shorter TTL (more volatile)
        if search_params.get("min_price") or search_params.get("max_price"):
            base_ttl = 180  # 3 minutes
        
        # First page gets longer TTL (more stable)
        if search_params.get("page", 1) == 1:
            base_ttl = int(base_ttl * 1.5)
        
        return min(base_ttl, 900)  # Max 15 minutes
    
    async def _build_optimized_query(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """Build optimized database query"""
        
        # Base query with optimized field selection
        query = supabase_admin.table("properties").select(
            """
            id, title, price, beds, baths, sqft, property_type, 
            location, address, city, state, images, status, 
            created_at, landlord_id, featured,
            latitude, longitude
            """,
            count="exact"
        ).eq("status", "vacant")
        
        # Apply filters in optimal order (most selective first)
        filters = self._get_ordered_filters(search_params)
        
        for filter_name, filter_value in filters:
            if filter_value is not None and filter_value != "":
                query = self._apply_filter(query, filter_name, filter_value)
        
        # Apply smart sorting
        query = self._apply_smart_sorting(query, search_params)
        
        # Apply pagination
        pagination = self._optimize_pagination(search_params)
        query = self._apply_pagination(query, pagination)
        
        return {
            "query": query,
            "filters": filters,
            "pagination": pagination,
            "search_params": search_params
        }
    
    def _get_ordered_filters(self, search_params: Dict[str, Any]) -> List[tuple]:
        """Order filters by selectivity for better performance"""
        filters = []
        
        # Most selective first
        if search_params.get("property_type") and search_params["property_type"] != "all":
            filters.append(("property_type", search_params["property_type"]))
        
        if search_params.get("beds", 0) > 0:
            filters.append(("beds", search_params["beds"]))
        
        if search_params.get("baths", 0) > 0:
            filters.append(("baths", search_params["baths"]))
        
        if search_params.get("location"):
            filters.append(("location", search_params["location"]))
        
        if search_params.get("min_price", 0) > 0:
            filters.append(("min_price", search_params["min_price"]))
        
        if search_params.get("max_price", 0) < 10000000:
            filters.append(("max_price", search_params["max_price"]))
        
        return filters
    
    def _apply_filter(self, query, filter_name: str, filter_value: Any):
        """Apply individual filter"""
        if filter_name == "property_type":
            return query.eq("property_type", filter_value)
        elif filter_name == "beds":
            return query.eq("beds", filter_value)
        elif filter_name == "baths":
            return query.gte("baths", filter_value)
        elif filter_name == "location":
            return query.ilike("location", f"%{filter_value}%")
        elif filter_name == "min_price":
            return query.gte("price", filter_value)
        elif filter_name == "max_price":
            return query.lte("price", filter_value)
        return query
    
    def _apply_smart_sorting(self, query, search_params: Dict[str, Any]):
        """Apply intelligent sorting based on search context"""
        sort = search_params.get("sort", "newest")
        
        # Location searches benefit from featured properties first
        if search_params.get("location") and sort == "newest":
            return query.order("featured", desc=True).order("created_at", desc=True)
        
        # Price searches benefit from price sorting
        if (search_params.get("min_price") or search_params.get("max_price")) and sort == "newest":
            return query.order("price", desc=False).order("created_at", desc=True)
        
        # Standard sorting
        if sort == "newest":
            return query.order("created_at", desc=True)
        elif sort == "price_low":
            return query.order("price", desc=False)
        elif sort == "price_high":
            return query.order("price", desc=True)
        elif sort == "featured":
            return query.order("featured", desc=True).order("created_at", desc=True)
        
        return query.order("created_at", desc=True)
    
    def _optimize_pagination(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """Optimize pagination for better performance"""
        page = max(1, search_params.get("page", 1))
        limit = min(search_params.get("limit", 20), 50)
        
        # First page gets slightly more results for better UX
        if page == 1:
            effective_limit = min(limit + 4, 50)
        else:
            effective_limit = limit
        
        offset = (page - 1) * effective_limit
        range_end = offset + effective_limit - 1
        
        return {
            "page": page,
            "limit": effective_limit,
            "offset": offset,
            "range_end": range_end
        }
    
    def _apply_pagination(self, query, pagination: Dict[str, Any]):
        """Apply optimized pagination"""
        return query.range(pagination["offset"], pagination["range_end"])
    
    async def _execute_optimized_query(self, optimized_query: Dict[str, Any]) -> Dict[str, Any]:
        """Execute optimized query with post-processing"""
        try:
            # Execute the main query
            response = optimized_query["query"].execute()
            
            if not response.data:
                return {
                    "properties": [],
                    "pagination": {
                        "current_page": optimized_query["search_params"].get("page", 1),
                        "total_pages": 0,
                        "total": 0,
                        "limit": optimized_query["search_params"].get("limit", 20)
                    }
                }
            
            # Post-process results for better frontend performance
            processed_properties = await self._post_process_results(response.data)
            
            # Build pagination info
            total_count = response.count or len(response.data)
            current_page = optimized_query["search_params"].get("page", 1)
            limit = optimized_query["search_params"].get("limit", 20)
            total_pages = max(1, (total_count + limit - 1) // limit)
            
            return {
                "properties": processed_properties,
                "pagination": {
                    "current_page": current_page,
                    "total_pages": total_pages,
                    "total": total_count,
                    "limit": limit,
                    "has_next": current_page < total_pages,
                    "has_prev": current_page > 1
                }
            }
            
        except Exception as e:
            print(f"ERROR: Query execution error: {e}")
            raise e
    
    async def _post_process_results(self, properties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Post-process results for better frontend performance"""
        processed = []
        
        for prop in properties:
            processed_prop = {
                **prop,
                "price_formatted": f"₦{prop.get('price', 0):,.0f}",
                "location_short": prop.get('location', '')[:30] + ('...' if len(prop.get('location', '')) > 30 else ''),
                "has_images": bool(prop.get('images')),
                "image_count": len(prop.get('images', [])),
                "search_rank": 1.0  # Simple rank for now
            }
            
            processed.append(processed_prop)
        
        return processed
    
    def _calculate_search_rank(self, property: Dict[str, Any]) -> float:
        """Calculate search relevance score"""
        rank = 0.0
        
        if property.get('featured'):
            rank += 10.0
        
        if property.get('days_since_created', 0) <= 7:
            rank += 5.0
        
        if property.get('has_images'):
            rank += 3.0
        
        # Completeness score
        completeness_score = 0
        required_fields = ['title', 'description', 'price', 'beds', 'baths', 'location']
        for field in required_fields:
            if property.get(field):
                completeness_score += 1
        rank += (completeness_score / len(required_fields)) * 2
        
        return rank
    
    async def _log_query_performance(self, search_params: Dict[str, Any], execution_time: float, results: Dict[str, Any]):
        """Log performance for monitoring"""
        query_hash = hashlib.md5(json.dumps(search_params, sort_keys=True).encode()).hexdigest()
        
        if query_hash not in self.query_stats:
            self.query_stats[query_hash] = {
                "search_params": search_params,
                "executions": [],
                "avg_execution_time": 0,
                "result_count_avg": 0
            }
        
        stats = self.query_stats[query_hash]
        stats["executions"].append({
            "execution_time": execution_time,
            "result_count": len(results.get("properties", [])),
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Update averages
        total_executions = len(stats["executions"])
        stats["avg_execution_time"] = sum(e["execution_time"] for e in stats["executions"]) / total_executions
        stats["result_count_avg"] = sum(e["result_count"] for e in stats["executions"]) / total_executions
        
        # Log slow queries for optimization
        if execution_time > 1.5:
            print(f"SLOW QUERY: {execution_time:.3f}s for {search_params}")

# Global optimizer instance
simple_property_optimizer = SimplePropertyOptimizer()
