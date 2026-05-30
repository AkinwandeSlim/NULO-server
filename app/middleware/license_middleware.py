"""
License Verification Middleware
Checks license status on every API request
If expired, blocks all endpoints (full lockdown)
"""

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
import logging

from app.license import LicenseService, LicenseStatus

logger = logging.getLogger(__name__)


class LicenseVerificationMiddleware(BaseHTTPMiddleware):
    """
    Middleware that verifies license on every request
    - If expired: blocks all endpoints
    - If expiring soon: allows access but includes warning header
    - If active: normal access
    """
    
    # Endpoints that should bypass license check
    # (e.g., health check, license extension endpoint)
    BYPASS_PATHS = {
        "/health",
        "/docs",
        "/redoc",
        "/openapi.json",
        "/license/extend",  # Admin can extend license
        "/license/status",  # Check license status
    }
    
    async def dispatch(self, request: Request, call_next):
        """Check license before processing request"""
        
        # Allow bypass paths through without check
        if request.url.path in self.BYPASS_PATHS:
            return await call_next(request)
        
        # Check license validity
        is_valid, message = LicenseService.check_license_valid()
        
        if not is_valid:
            # License expired - block all requests with 403
            logger.warning(f"License expired. Access denied to {request.url.path}")
            response = JSONResponse(
                status_code=403,
                content={
                    "error": "LICENSE_EXPIRED",
                    "message": message,
                    "detail": "Application license has expired. Please contact support to renew your license.",
                    "support": "support@nuloafrica.com"
                }
            )
            # Add CORS headers to allow frontend to receive the error
            response.headers["Access-Control-Allow-Origin"] = "*"
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
            return response
        
        # Process request
        response = await call_next(request)
        
        # If expiring soon, add warning header
        license_info = LicenseService.get_status_info()
        if license_info["time_remaining"]["status"] == LicenseStatus.EXPIRING_SOON:
            response.headers["X-License-Warning"] = message
            logger.warning(f"License expiring soon: {message}")
        
        return response
