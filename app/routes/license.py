"""
License Management Routes
Admin endpoints to check and extend license
Only accessible with secret license key
"""

from fastapi import APIRouter, HTTPException, Query
from app.license import LicenseService, LicenseConfig
from datetime import datetime

router = APIRouter(
    prefix="/license",
    tags=["license"],
    responses={403: {"description": "Invalid license key"}}
)


@router.get("/status")
async def get_license_status():
    """
    Get current license status
    Accessible without authorization (for frontend error handling)
    """
    license_info = LicenseService.get_status_info()
    
    return {
        "license_status": license_info
    }


@router.post("/extend")
async def extend_license(
    license_key: str = Query(..., description="Secret license key"),
    days: int = Query(90, description="Days to extend (default 90)")
):
    """
    Extend license by adding days
    Requires valid license key
    
    Example:
    POST /license/extend?license_key=nulo-africa-founder-key-2025&days=90
    
    Response:
    {
        "success": true,
        "message": "License extended",
        "new_expiry": "2026-03-31T12:00:00"
    }
    """
    
    # Verify license key
    if not license_key or license_key != LicenseConfig.LICENSE_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid or missing license key"
        )
    
    # Extend license
    success, message = LicenseService.extend_license(license_key, days)
    
    if not success:
        raise HTTPException(
            status_code=403,
            detail=message
        )
    
    license_info = LicenseService.get_license()
    
    return {
        "success": True,
        "message": message,
        "new_expiry": license_info["expiry_date"],
        "extended_count": license_info["extended_count"],
        "last_extended_at": license_info["last_extended_at"]
    }


@router.get("/info")
async def get_license_info(license_key: str = Query(..., description="Secret license key")):
    """
    Get detailed license information
    Requires valid license key
    """
    
    if license_key != LicenseConfig.LICENSE_KEY:
        raise HTTPException(
            status_code=403,
            detail="Invalid license key"
        )
    
    return {
        "license_info": LicenseService.get_status_info(),
        "config": {
            "expiry_warning_days": LicenseConfig.EXPIRY_WARNING_DAYS,
            "grace_period_days": LicenseConfig.GRACE_PERIOD_DAYS
        }
    }
