"""
Engagement Service
Handles all engagement score calculations and trust score integration
"""

from datetime import datetime, timedelta
from typing import Dict, Any, Optional
from decimal import Decimal
import asyncio

from ..database import supabase_admin
from ..models.user import UserBase


class EngagementService:
    """Service for calculating and managing user engagement scores"""
    
    @staticmethod
    def calculate_tenant_engagement(metrics: Dict[str, Any]) -> int:
        """
        Calculate engagement score for tenants (0-100)
        
        Scoring:
        - Property Discovery: 30 points max (views + favorites)
        - Active Engagement: 50 points max (viewing requests + confirmed)
        - Communication: 15 points max (messages sent)
        - Platform Usage: 5 points max (login frequency)
        """
        score = 0
        
        # Property Discovery (30 points max)
        score += min(metrics.get('properties_viewed_count', 0) * 2, 20)  # 2 pts per view, max 20
        score += min(metrics.get('favorites_count', 0) * 5, 10)        # 5 pts per favorite, max 10
        
        # Active Engagement (50 points max)
        score += min(metrics.get('viewing_requests_count', 0) * 10, 30)  # 10 pts per request, max 30
        score += min(metrics.get('confirmed_viewings_count', 0) * 15, 20) # 15 pts per confirmed, max 20
        
        # Communication (15 points max)
        score += min(metrics.get('messages_sent_count', 0) * 3, 15)      # 3 pts per message, max 15
        
        # Platform Usage (5 points max)
        score += min(metrics.get('login_frequency', 0) * 1, 5)           # 1 pt per login week, max 5
        
        return min(score, 100)
    
    @staticmethod
    def calculate_landlord_engagement(metrics: Dict[str, Any]) -> int:
        """
        Calculate engagement score for landlords (0-100)
        
        Scoring:
        - Property Management: 40 points max (properties listed + completion)
        - Tenant Interaction: 35 points max (responses + messages)
        - Responsiveness: 20 points max (response time)
        - Platform Usage: 5 points max (login frequency)
        """
        score = 0
        
        # Property Management (40 points max)
        score += min(metrics.get('properties_listed', 0) * 8, 32)        # 8 pts per property, max 32
        score += min(metrics.get('profile_completion_score', 0) * 0.8, 8)    # 0.8 pts per % complete, max 8
        
        # Tenant Interaction (35 points max)
        score += min(metrics.get('viewing_responses_count', 0) * 5, 20)     # 5 pts per response, max 20
        score += min(metrics.get('messages_sent_count', 0) * 3, 15)        # 3 pts per message, max 15
        
        # Responsiveness (20 points max)
        avg_response_time = float(metrics.get('avg_response_time_hours', 999))
        if avg_response_time <= 2:
            score += 20  # Excellent response time
        elif avg_response_time <= 6:
            score += 15  # Good response time
        elif avg_response_time <= 24:
            score += 10  # Acceptable response time
        
        # Platform Usage (5 points max)
        score += min(metrics.get('login_frequency', 0) * 1, 5)           # 1 pt per login week, max 5
        
        return min(score, 100)
    
    @staticmethod
    def calculate_engagement_score(metrics: Dict[str, Any], user_type: str) -> int:
        """Calculate engagement score based on user type"""
        if user_type == 'tenant':
            return EngagementService.calculate_tenant_engagement(metrics)
        elif user_type == 'landlord':
            return EngagementService.calculate_landlord_engagement(metrics)
        else:
            return 0
    
    @staticmethod
    def get_engagement_level(score: int) -> str:
        """Determine engagement level based on score"""
        if score >= 80:
            return 'High'
        elif score >= 50:
            return 'Medium'
        else:
            return 'Low'
    
    @staticmethod
    def update_trust_score_with_engagement(user_id: str, user_type: str) -> Dict[str, Any]:
        """
        Update trust score with engagement bonus
        
        Formula: Final Trust Score = Base Trust Score + (Engagement Score × 0.3)
        Max bonus from engagement = 30 points (100 × 0.3)
        """
        try:
            # Get current metrics
            metrics_response = supabase_admin.table("user_engagement_metrics")\
                .select("*").eq("user_id", user_id).single().execute()
            
            if not metrics_response.data:
                # Initialize metrics if not exists
                init_metrics = {
                    "user_id": user_id,
                    "user_type": user_type,
                    "created_at": datetime.now().isoformat(),
                    "updated_at": datetime.now().isoformat()
                }
                supabase_admin.table("user_engagement_metrics").upsert(init_metrics).execute()
                metrics_response.data = init_metrics
            
            metrics = metrics_response.data or {}
            
            # Calculate engagement score
            engagement_score = EngagementService.calculate_engagement_score(metrics, user_type)
            
            # Get current trust score
            user_response = supabase_admin.table("users")\
                .select("trust_score").eq("id", user_id).single().execute()
            
            current_trust = user_response.data.get('trust_score', 50) if user_response.data else 50
            base_trust = 50  # Base score for new users
            
            # Calculate engagement bonus (30% max)
            engagement_bonus = int(engagement_score * 0.3)
            
            # Update trust score (max 100)
            new_trust_score = min(base_trust + engagement_bonus, 100)
            
            # Determine engagement level
            engagement_level = EngagementService.get_engagement_level(engagement_score)
            
            # Update users table
            supabase_admin.table("users").update({
                "trust_score": new_trust_score,
                "engagement_score": engagement_score,
                "engagement_level": engagement_level,
                "last_engagement_update": datetime.now().isoformat()
            }).eq("id", user_id).execute()
            
            # Track history
            supabase_admin.table("engagement_history").insert({
                "user_id": user_id,
                "engagement_score": engagement_score,
                "trust_score": new_trust_score,
                "engagement_level": engagement_level,
                "change_reason": "engagement_update",
                "created_at": datetime.now().isoformat()
            }).execute()
            
            return {
                "trust_score": new_trust_score,
                "engagement_score": engagement_score,
                "engagement_level": engagement_level,
                "engagement_bonus": engagement_bonus
            }
            
        except Exception as e:
            print(f"❌ [ENGAGEMENT] Failed to update trust score for user {user_id}: {e}")
            raise e
    
    @staticmethod
    async def track_engagement_activity(user_id: str, activity_type: str, metadata: Dict[str, Any] = None) -> bool:
        """
        Track individual engagement activities and update scores
        
        Activity Types:
        - favorite_added: User saved a property
        - viewing_requested: User requested a viewing
        - viewing_confirmed: Viewing was confirmed
        - message_sent: User sent a message
        - property_listed: Landlord listed a property
        - viewing_responded: Landlord responded to viewing
        - property_viewed: User viewed a property
        - login: User logged in
        """
        try:
            # Map activity types to database fields
            update_mapping = {
                'favorite_added': 'favorites_count',
                'viewing_requested': 'viewing_requests_count', 
                'viewing_confirmed': 'confirmed_viewings_count',
                'message_sent': 'messages_sent_count',
                'property_listed': 'properties_listed',
                'viewing_responded': 'viewing_responses_count',
                'property_viewed': 'properties_viewed_count',
                'login': 'login_frequency'
            }
            
            if activity_type not in update_mapping:
                print(f"⚠️ [ENGAGEMENT] Unknown activity type: {activity_type}")
                return False
            
            # Update specific metric using the database function
            field = update_mapping[activity_type]
            supabase_admin.rpc('increment_engagement_metric', {
                'p_user_id': user_id,
                'p_field': field,
                'p_increment': 1
            }).execute()
            
            # Get user type and trigger engagement score update
            user_response = supabase_admin.table("users")\
                .select("user_type").eq("id", user_id).single().execute()
            
            if user_response.data:
                user_type = user_response.data.get('user_type')
                # Trigger engagement score update asynchronously
                asyncio.create_task(
                    EngagementService.update_trust_score_with_engagement(user_id, user_type)
                )
            
            print(f"✅ [ENGAGEMENT] Tracked activity '{activity_type}' for user {user_id}")
            return True
            
        except Exception as e:
            print(f"❌ [ENGAGEMENT] Failed to track activity for user {user_id}: {e}")
            return False
    

    @staticmethod
    def calculate_live_metrics(user_id: str, user_type: str) -> Dict[str, Any]:
        """
        Calculate engagement metrics LIVE from actual DB tables.

        The user_engagement_metrics table is only updated via activity tracking
        events (track_engagement_activity). This means any activity that happened
        before the engagement system was deployed, or that was never explicitly
        tracked, produces stale zeros.

        This method bypasses the cache and reads real counts directly from:
          - properties table (landlord_id)
          - viewing_requests table (landlord_id / tenant_id)
          - favorites table (user_id)
          - messages table (sender_id)

        Called by GET /engagement/{user_id} so dashboards always show correct scores.
        """
        metrics: Dict[str, Any] = {}

        try:
            if user_type == 'landlord':
                # Properties listed
                props_r = supabase_admin.table("properties")                    .select("id", count="exact")                    .eq("landlord_id", user_id).execute()
                metrics['properties_listed'] = props_r.count or 0

                # Viewing responses = confirmed viewings the landlord actioned
                confirmed_r = supabase_admin.table("viewing_requests")                    .select("id, created_at, updated_at", count="exact")                    .eq("landlord_id", user_id)                    .eq("status", "confirmed").execute()
                metrics['viewing_responses_count'] = confirmed_r.count or 0

                # All viewings received (for response-time denominator)
                all_vr = supabase_admin.table("viewing_requests")                    .select("id", count="exact")                    .eq("landlord_id", user_id).execute()
                metrics['total_viewings_received'] = all_vr.count or 0

                # Messages sent by this landlord
                try:
                    msgs_r = supabase_admin.table("messages")                        .select("id", count="exact")                        .eq("sender_id", user_id).execute()
                    metrics['messages_sent_count'] = msgs_r.count or 0
                except Exception:
                    metrics['messages_sent_count'] = 0

                # Profile completion: count non-null key fields
                try:
                    user_r = supabase_admin.table("users")                        .select("full_name, phone_number, avatar_url")                        .eq("id", user_id).single().execute()
                    if user_r.data:
                        filled = sum(1 for v in [
                            user_r.data.get('full_name'),
                            user_r.data.get('phone_number'),
                            user_r.data.get('avatar_url')
                        ] if v)
                        metrics['profile_completion_score'] = int((filled / 3) * 100)
                    else:
                        metrics['profile_completion_score'] = 0
                except Exception:
                    metrics['profile_completion_score'] = 0

                # Avg response time: default 24h until real timing data is tracked
                metrics['avg_response_time_hours'] = 24
                metrics['login_frequency'] = 0

            elif user_type == 'tenant':
                # Viewing requests made by tenant
                vr = supabase_admin.table("viewing_requests")                    .select("id", count="exact")                    .eq("tenant_id", user_id).execute()
                metrics['viewing_requests_count'] = vr.count or 0

                # Confirmed viewings
                conf_r = supabase_admin.table("viewing_requests")                    .select("id", count="exact")                    .eq("tenant_id", user_id)                    .eq("status", "confirmed").execute()
                metrics['confirmed_viewings_count'] = conf_r.count or 0

                # Saved properties (favorites)
                try:
                    favs_r = supabase_admin.table("favorites")                        .select("id", count="exact")                        .eq("user_id", user_id).execute()
                    metrics['favorites_count'] = favs_r.count or 0
                except Exception:
                    metrics['favorites_count'] = 0

                # Messages sent
                try:
                    msgs_r = supabase_admin.table("messages")                        .select("id", count="exact")                        .eq("sender_id", user_id).execute()
                    metrics['messages_sent_count'] = msgs_r.count or 0
                except Exception:
                    metrics['messages_sent_count'] = 0

                # Properties viewed — requires a view-tracking table not yet implemented.
                # Fall back to 0 until that table exists.
                metrics['properties_viewed_count'] = 0
                metrics['login_frequency'] = 0

        except Exception as e:
            print(f"[ENGAGEMENT] calculate_live_metrics error for {user_id}: {e}")

        return metrics

    @staticmethod
    def calculate_and_persist_engagement(user_id: str, user_type: str) -> Dict[str, Any]:
        """
        Calculate live engagement score and persist it back to the users table.
        Called by the GET /engagement/{user_id} endpoint so scores are always fresh.
        """
        try:
            metrics = EngagementService.calculate_live_metrics(user_id, user_type)
            engagement_score = EngagementService.calculate_engagement_score(metrics, user_type)
            engagement_level = EngagementService.get_engagement_level(engagement_score)

            base_trust = 50
            engagement_bonus = int(engagement_score * 0.3)
            new_trust_score = min(base_trust + engagement_bonus, 100)

            # Persist fresh scores back to users table
            supabase_admin.table("users").update({
                "engagement_score": engagement_score,
                "engagement_level": engagement_level,
                "trust_score": new_trust_score,
                "last_engagement_update": datetime.now().isoformat()
            }).eq("id", user_id).execute()

            # Upsert user_engagement_metrics so the cached table is in sync
            try:
                supabase_admin.table("user_engagement_metrics").upsert({
                    "user_id": user_id,
                    "user_type": user_type,
                    **metrics,
                    "updated_at": datetime.now().isoformat()
                }).execute()
            except Exception:
                pass  # Non-fatal -- live values are already returned

            return {
                "engagement_score": engagement_score,
                "engagement_level": engagement_level,
                "trust_score": new_trust_score,
                "engagement_bonus": engagement_bonus,
                "metrics": metrics,
            }

        except Exception as e:
            print(f"[ENGAGEMENT] calculate_and_persist_engagement error for {user_id}: {e}")
            return {
                "engagement_score": 0,
                "engagement_level": "Low",
                "trust_score": 50,
                "engagement_bonus": 0,
                "metrics": {},
            }

    @staticmethod
    def get_user_engagement_metrics(user_id: str) -> Optional[Dict[str, Any]]:
        """Get current engagement metrics for a user"""
        try:
            response = supabase_admin.table("user_engagement_metrics")\
                .select("*").eq("user_id", user_id).single().execute()
            
            return response.data if response.data else None
            
        except Exception as e:
            print(f"❌ [ENGAGEMENT] Failed to get metrics for user {user_id}: {e}")
            return None
    
    @staticmethod
    def get_engagement_history(user_id: str, limit: int = 50) -> list:
        """Get engagement history for a user"""
        try:
            response = supabase_admin.table("engagement_history")\
                .select("*")\
                .eq("user_id", user_id)\
                .order("created_at", desc=True)\
                .limit(limit)\
                .execute()
            
            return response.data if response.data else []
            
        except Exception as e:
            print(f"❌ [ENGAGEMENT] Failed to get history for user {user_id}: {e}")
            return []