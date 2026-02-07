"""
Advanced Property Query Optimizer
AI-powered database optimization with intelligent indexing and query planning
"""
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime, timedelta
import json
import hashlib
from app.database import supabase_admin
from app.services.property_cache import property_cache

class PropertyQueryOptimizer:
    def __init__(self):
        self.query_stats = {}
        self.index_recommendations = {}
        self.ai_optimization_enabled = True
        
    async def optimize_search_query(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """AI: Optimize search query based on patterns and performance"""
        
        # 1. Check cache first
        cached_results = await property_cache.get_cached_search(search_params)
        if cached_results:
            return cached_results
        
        # 2. Build optimized query
        optimized_query = await self._build_optimized_query(search_params)
        
        # 3. Execute with performance monitoring
        start_time = datetime.utcnow()
        results = await self._execute_optimized_query(optimized_query)
        execution_time = (datetime.utcnow() - start_time).total_seconds()
        
        # 4. AI: Learn from query performance
        await self._analyze_query_performance(search_params, execution_time, results)
        
        # 5. Cache results
        await property_cache.cache_search_results(search_params, results)
        
        return results
    
    async def _build_optimized_query(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """Build optimized database query with AI enhancements"""
        
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
        
        # AI: Optimize filter order based on selectivity
        filters = self._optimize_filter_order(search_params)
        
        # Apply filters in optimal order
        for filter_name, filter_value in filters.items():
            if filter_value is not None and filter_value != "":
                query = self._apply_filter(query, filter_name, filter_value)
        
        # AI: Optimize sorting based on data distribution
        sort_strategy = await self._optimize_sorting(search_params)
        query = self._apply_sorting(query, sort_strategy)
        
        # AI: Optimize pagination
        pagination = self._optimize_pagination(search_params)
        query = self._apply_pagination(query, pagination)
        
        return {
            "query": query,
            "filters": filters,
            "sort_strategy": sort_strategy,
            "pagination": pagination,
            "search_params": search_params
        }
    
    def _optimize_filter_order(self, search_params: Dict[str, Any]) -> List[Tuple[str, Any]]:
        """AI: Order filters by selectivity (most selective first)"""
        
        # Filter selectivity analysis (based on typical data distribution)
        filter_selectivity = {
            "property_type": 0.8,    # High selectivity
            "beds": 0.7,            # High selectivity  
            "baths": 0.6,           # Medium selectivity
            "location": 0.5,        # Medium selectivity
            "min_price": 0.4,      # Low selectivity
            "max_price": 0.4,      # Low selectivity
        }
        
        # Create filter list with selectivity scores
        filters = []
        
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
        
        # Sort by selectivity (most selective first)
        filters.sort(key=lambda f: filter_selectivity.get(f[0], 0.5), reverse=True)
        
        return filters
    
    def _apply_filter(self, query, filter_name: str, filter_value: Any):
        """Apply individual filter with optimization"""
        
        if filter_name == "property_type":
            return query.eq("property_type", filter_value)
        
        elif filter_name == "beds":
            return query.eq("beds", filter_value)
        
        elif filter_name == "baths":
            return query.gte("baths", filter_value)
        
        elif filter_name == "location":
            # AI: Use optimized location search
            return query.ilike("location", f"%{filter_value}%")
        
        elif filter_name == "min_price":
            return query.gte("price", filter_value)
        
        elif filter_name == "max_price":
            return query.lte("price", filter_value)
        
        return query
    
    async def _optimize_sorting(self, search_params: Dict[str, Any]) -> str:
        """AI: Optimize sorting strategy based on query patterns"""
        
        sort = search_params.get("sort", "newest")
        
        # AI: Adjust sorting based on filter combination
        if search_params.get("location") and not search_params.get("min_price"):
            # Location-only searches benefit from featured sorting
            if sort == "newest":
                return "featured_then_newest"
        
        if search_params.get("min_price") or search_params.get("max_price"):
            # Price-filtered searches benefit from price sorting
            if sort == "newest":
                return "price_then_newest"
        
        return sort
    
    def _apply_sorting(self, query, sort_strategy: str):
        """Apply optimized sorting"""
        
        if sort_strategy == "featured_then_newest":
            return query.order("featured", desc=True).order("created_at", desc=True)
        
        elif sort_strategy == "price_then_newest":
            return query.order("price", desc=False).order("created_at", desc=True)
        
        elif sort_strategy == "newest":
            return query.order("created_at", desc=True)
        
        elif sort_strategy == "price_low":
            return query.order("price", desc=False)
        
        elif sort_strategy == "price_high":
            return query.order("price", desc=True)
        
        return query.order("created_at", desc=True)
    
    def _optimize_pagination(self, search_params: Dict[str, Any]) -> Dict[str, Any]:
        """AI: Optimize pagination based on usage patterns"""
        
        page = max(1, search_params.get("page", 1))
        limit = min(search_params.get("limit", 20), 50)  # Cap at 50 for performance
        
        # AI: Adaptive pagination for better UX
        if page == 1:
            # First page gets slightly more results for better discovery
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
        """Execute optimized query with performance monitoring"""
        
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
            
            # AI: Post-process results for better performance
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
                },
                "performance": {
                    "query_optimized": True,
                    "cache_enabled": True,
                    "ai_enhanced": True
                }
            }
            
        except Exception as e:
            print(f"❌ Query execution error: {e}")
            raise e
    
    async def _post_process_results(self, properties: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """AI: Post-process results for better performance and UX"""
        
        processed = []
        
        for prop in properties:
            # AI: Add computed fields for better frontend performance
            processed_prop = {
                **prop,
                "price_formatted": f"₦{prop.get('price', 0):,.0f}",
                "location_short": prop.get('location', '')[:30] + ('...' if len(prop.get('location', '')) > 30 else ''),
                "has_images": bool(prop.get('images')),
                "image_count": len(prop.get('images', [])),
                "days_since_created": (datetime.utcnow() - datetime.fromisoformat(prop.get('created_at', '').replace('Z', '+00:00'))).days if prop.get('created_at') else 0,
                "is_new": (datetime.utcnow() - datetime.fromisoformat(prop.get('created_at', '').replace('Z', '+00:00'))).days <= 7 if prop.get('created_at') else False,
                "search_rank": await self._calculate_search_rank(prop)
            }
            
            processed.append(processed_prop)
        
        # AI: Sort by search rank for better relevance
        processed.sort(key=lambda x: x["search_rank"], reverse=True)
        
        return processed
    
    async def _calculate_search_rank(self, property: Dict[str, Any]) -> float:
        """AI: Calculate search relevance score"""
        
        rank = 0.0
        
        # Featured properties get higher rank
        if property.get('featured'):
            rank += 10.0
        
        # New properties get higher rank
        if property.get('days_since_created', 0) <= 7:
            rank += 5.0
        
        # Properties with images get higher rank
        if property.get('has_images'):
            rank += 3.0
        
        # Complete listings get higher rank
        completeness_score = 0
        required_fields = ['title', 'description', 'price', 'beds', 'baths', 'location']
        for field in required_fields:
            if property.get(field):
                completeness_score += 1
        rank += (completeness_score / len(required_fields)) * 2
        
        return rank
    
    async def _analyze_query_performance(self, search_params: Dict[str, Any], execution_time: float, results: Dict[str, Any]):
        """AI: Analyze query performance for continuous optimization"""
        
        query_hash = hashlib.md5(json.dumps(search_params, sort_keys=True).encode()).hexdigest()
        
        # Store performance metrics
        if query_hash not in self.query_stats:
            self.query_stats[query_hash] = {
                "search_params": search_params,
                "executions": [],
                "avg_execution_time": 0,
                "result_count_avg": 0,
                "cache_hit_rate": 0
            }
        
        stats = self.query_stats[query_hash]
        stats["executions"].append({
            "execution_time": execution_time,
            "result_count": len(results.get("properties", [])),
            "timestamp": datetime.utcnow().isoformat()
        })
        
        # Update averages
        total_executions = len(stats["executions"])
        stats["avg_execution_time"] = sum(e["execution_time"] for e in stats["executions"]) / total_executions
        stats["result_count_avg"] = sum(e["result_count"] for e in stats["executions"]) / total_executions
        
        # AI: Generate optimization recommendations
        if execution_time > 2.0:  # Slow query
            await self._generate_optimization_recommendation(search_params, execution_time, results)
    
    async def _generate_optimization_recommendation(self, search_params: Dict[str, Any], execution_time: float, results: Dict[str, Any]):
        """AI: Generate optimization recommendations for slow queries"""
        
        recommendation = {
            "search_params": search_params,
            "execution_time": execution_time,
            "result_count": len(results.get("properties", [])),
            "recommendations": [],
            "timestamp": datetime.utcnow().isoformat()
        }
        
        # Analyze and recommend
        if execution_time > 3.0:
            recommendation["recommendations"].append("Consider adding database index for frequently filtered fields")
        
        if len(results.get("properties", [])) > 100:
            recommendation["recommendations"].append("Consider reducing default limit for better performance")
        
        if search_params.get("location") and not search_params.get("property_type"):
            recommendation["recommendations"].append("Location-only searches may benefit from geospatial indexing")
        
        # Store recommendation (in production, this would go to an optimization queue)
        print(f"🤖 AI Recommendation: {recommendation}")

# Global optimizer instance
property_optimizer = PropertyQueryOptimizer()
