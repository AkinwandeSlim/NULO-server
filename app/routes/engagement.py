"""
Engagement Routes
API endpoints for managing user engagement scores and tracking activities
"""

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from typing import Dict, Any, Optional, List
from datetime import datetime

from app.middleware.auth import get_current_user
from ..services.engagement_service import EngagementService

router = APIRouter(prefix="/engagement", tags=["engagement"])


class EngagementActivityRequest(BaseModel):
    """Request model for tracking engagement activities"""
    user_id: str
    activity_type: str
    metadata: Optional[Dict[str, Any]] = {}


class EngagementResponse(BaseModel):
    """Response model for engagement data"""
    trust_score: int
    engagement_score: int
    engagement_level: str
    engagement_bonus: Optional[int] = None


class EngagementMetricsResponse(BaseModel):
    """Response model for detailed engagement metrics"""
    user_id: str
    user_type: str
    engagement_score: int
    trust_score: int
    engagement_level: str
    metrics: Dict[str, Any]
    last_updated: str


@router.post("/update/{user_id}", response_model=EngagementResponse)
async def update_user_engagement(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Update engagement score for any user type
    
    - Users can update their own engagement score
    - Admins can update any user's engagement score
    """
    # Check permissions
    if current_user.get('user_type') != 'admin' and current_user.get('id') != user_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to update this user's engagement"
        )
    
    try:
        result = EngagementService.update_trust_score_with_engagement(
            user_id, 
            current_user.get('user_type') if current_user.get('id') == user_id else 'tenant'
        )
        
        return EngagementResponse(**result)
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to update engagement: {str(e)}"
        )


@router.get("/{user_id}", response_model=EngagementMetricsResponse)
async def get_user_engagement(
    user_id: str,
    current_user: dict = Depends(get_current_user)
):
    """
    Get current engagement metrics for a user
    
    - Users can view their own engagement metrics
    - Admins can view any user's engagement metrics
    """
    # Check permissions
    if current_user.get('user_type') != 'admin' and current_user.get('id') != user_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this user's engagement"
        )
    
    try:
        # Get user type first -- needed to run the correct scoring formula
        from ..database import supabase_admin
        user_response = supabase_admin.table("users")\
            .select("user_type, trust_score, engagement_score, engagement_level, last_engagement_update")\
            .eq("id", user_id)\
            .single().execute()

        if not user_response.data:
            raise HTTPException(status_code=404, detail="User not found")

        user_data = user_response.data
        user_type = user_data.get("user_type", "tenant")

        # ALWAYS recalculate live from real DB tables.
        # Reading the cached user_engagement_metrics row returns stale zeros for
        # any activity that happened before the engagement system was deployed
        # or was never explicitly tracked (e.g. properties listed, viewings confirmed).
        fresh = EngagementService.calculate_and_persist_engagement(user_id, user_type)

        return EngagementMetricsResponse(
            user_id=user_id,
            user_type=user_type,
            engagement_score=fresh["engagement_score"],
            trust_score=fresh["trust_score"],
            engagement_level=fresh["engagement_level"],
            metrics=fresh["metrics"],
            last_updated=datetime.now().isoformat()
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get engagement metrics: {str(e)}"
        )


@router.post("/track")
async def track_engagement_activity(
    request: EngagementActivityRequest,
    background_tasks: BackgroundTasks,
    current_user: dict = Depends(get_current_user)
):
    """
    Track individual engagement activities
    
    Activities tracked:
    - favorite_added: User saved a property
    - viewing_requested: User requested a viewing
    - viewing_confirmed: Viewing was confirmed
    - message_sent: User sent a message
    - property_listed: Landlord listed a property
    - viewing_responded: Landlord responded to viewing
    - property_viewed: User viewed a property
    - login: User logged in
    """
    # Users can only track their own activities
    if current_user.get('id') != request.user_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to track activities for this user"
        )
    
    try:
        # Track activity in background
        background_tasks.add_task(
            EngagementService.track_engagement_activity,
            request.user_id,
            request.activity_type,
            request.metadata or {}
        )
        
        return {
            "success": True,
            "message": f"Activity '{request.activity_type}' tracked successfully",
            "user_id": request.user_id,
            "activity_type": request.activity_type
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to track activity: {str(e)}"
        )


@router.get("/history/{user_id}")
async def get_engagement_history(
    user_id: str,
    limit: int = 50,
    current_user: dict = Depends(get_current_user)
):
    """
    Get engagement history for a user
    
    Shows how engagement score has changed over time
    """
    # Check permissions
    if current_user.get('user_type') != 'admin' and current_user.get('id') != user_id:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to view this user's engagement history"
        )
    
    try:
        history = EngagementService.get_engagement_history(user_id, limit)
        
        return {
            "user_id": user_id,
            "history": history,
            "total_entries": len(history)
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get engagement history: {str(e)}"
        )


@router.get("/leaderboard")
async def get_engagement_leaderboard(
    user_type: Optional[str] = None,
    limit: int = 20,
    current_user: dict = Depends(get_current_user)
):
    """
    Get engagement leaderboard
    
    - Can filter by user type (tenant/landlord)
    - Shows top engaged users
    """
    try:
        from ..database import supabase_admin
        
        query = supabase_admin.table("users")\
            .select("id, full_name, user_type, engagement_score, trust_score, engagement_level, avatar_url")\
            .order("engagement_score", desc=True)\
            .limit(limit)
        
        if user_type:
            query = query.eq("user_type", user_type)
        
        response = query.execute()
        
        users = response.data or []
        
        # Add rankings
        for i, user in enumerate(users, 1):
            user['rank'] = i
            user['engagement_level_color'] = {
                'High': 'green',
                'Medium': 'orange', 
                'Low': 'blue'
            }.get(user.get('engagement_level', 'Low'), 'blue')
        
        return {
            "leaderboard": users,
            "total_users": len(users),
            "filter_type": user_type or "all",
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get leaderboard: {str(e)}"
        )


@router.get("/stats/summary")
async def get_engagement_stats(
    current_user: dict = Depends(get_current_user)
):
    """
    Get platform-wide engagement statistics (Admin only)
    """
    if current_user.get('user_type') != 'admin':
        raise HTTPException(
            status_code=403,
            detail="Admin access required"
        )
    
    try:
        from ..database import supabase_admin
        
        # Get overall stats
        users_response = supabase_admin.table("users")\
            .select("user_type, engagement_score, trust_score")\
            .execute()
        
        users = users_response.data or []
        
        # Calculate statistics
        total_users = len(users)
        tenants = [u for u in users if u.get('user_type') == 'tenant']
        landlords = [u for u in users if u.get('user_type') == 'landlord']
        
        avg_engagement = sum(u.get('engagement_score', 0) for u in users) / total_users if total_users > 0 else 0
        avg_trust = sum(u.get('trust_score', 0) for u in users) / total_users if total_users > 0 else 0
        
        high_engagement = len([u for u in users if u.get('engagement_score', 0) >= 80])
        medium_engagement = len([u for u in users if 50 <= u.get('engagement_score', 0) < 80])
        low_engagement = len([u for u in users if u.get('engagement_score', 0) < 50])
        
        return {
            "total_users": total_users,
            "total_tenants": len(tenants),
            "total_landlords": len(landlords),
            "average_engagement_score": round(avg_engagement, 2),
            "average_trust_score": round(avg_trust, 2),
            "engagement_distribution": {
                "high": high_engagement,
                "medium": medium_engagement,
                "low": low_engagement
            },
            "generated_at": datetime.now().isoformat()
        }
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get engagement stats: {str(e)}"
        )