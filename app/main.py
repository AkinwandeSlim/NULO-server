"""
Nulo Africa - FastAPI Backend
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config import settings
from app.middleware.license_middleware import LicenseVerificationMiddleware
from app.middleware.rate_limit import setup_rate_limiter
from app.routes import (
    auth, properties, applications, tenants, favorites,
    messages, viewing_requests, verifications,
    admin_landlord_verification, property_verification,
    tenant_verification, admin_signup,admin_management,
    landlord_onboarding, landlord_dashboard, tenant_dashboard, notifications, admin_dashboard,
    admin_landlord_users, admin_tenant_users, locations, agreements, maintenance, health,
    engagement, banner_dismissals, payments, license, groq_agreement, nomba, disbursements,
)

import logging
import os
from dotenv import load_dotenv
load_dotenv()

# Environment detection
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() == "production"

# Configure logging based on environment
def setup_logging():
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    
    # Clear existing handlers
    logger.handlers = []
    
    # Use human-readable format in development, JSON in production
    if IS_PRODUCTION:
        from pythonjsonlogger import jsonlogger
        formatter = jsonlogger.JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(module)s %(funcName)s %(lineno)d"
        )
    else:
        # Development: human-readable with timestamps
        formatter = logging.Formatter(
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
    
    # Create console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Add handler to logger
    logger.addHandler(console_handler)
    
    return logger

logger = setup_logging()


def format_log(level: str, message: str, **context) -> str:
    """
    Format log message with optional context data.
    In dev: appends key=value pairs to the message.
    In prod: returns a dict for JSON serialization.

    Args:
        level: Log level/event name (e.g., 'request_started', 'api_starting')
        message: Human-readable log message
        **context: Additional context data as keyword arguments
    """
    if IS_PRODUCTION:
        # In production, return dict for JSON formatter
        log_data = {"event": level, "message": message}
        log_data.update(context)
        return log_data
    else:
        # In development, append context to the message
        if context:
            context_str = " | ".join(f"{k}={v}" for k, v in context.items())
            return f"{message} | {context_str}"
        return message

# Create FastAPI app
app = FastAPI(
    title="Nulo Africa API",
    description="Backend API for Nulo Africa - Zero Agency Fee Rental Platform",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# License Middleware - Check if app license is valid on every request
app.add_middleware(LicenseVerificationMiddleware)

# Rate limiter - protects auth endpoints from abuse
setup_rate_limiter(app)

# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    logger.info(format_log(
        "request_started",
        f"🔍 {request.method} {request.url}",
        method=request.method,
        url=str(request.url),
        client_host=request.client.host if request.client else None
    ))
    response = await call_next(request)
    logger.info(format_log(
        "request_completed",
        f"✅ {request.method} {request.url} - {response.status_code}",
        method=request.method,
        url=str(request.url),
        status_code=response.status_code
    ))
    return response

# Validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.error(format_log(
        "validation_error",
        f"❌ Validation error on {request.method} {request.url}",
        method=request.method,
        url=str(request.url),
        detail=str(exc.errors())
    ))
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "error": "Validation error",
            "detail": exc.errors(),
            "errors": exc.errors()
        }
    )

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    error_msg = str(exc)
    logger.error(format_log(
        "global_exception",
        f"❌ Global exception on {request.method} {request.url}: {error_msg}",
        method=request.method,
        url=str(request.url),
        error_message=error_msg,
        exc_type=str(type(exc))
    ))
    
    # Handle SSL/network errors specifically
    if "SSL handshake" in error_msg or "timeout" in error_msg.lower():
        return JSONResponse(
            status_code=503,
            content={
                "success": False,
                "error": "Service temporarily unavailable",
                "detail": "Network connectivity issues. Please try again in a moment."
            }
        )
    
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": error_msg if settings.DEBUG else "An error occurred"
        }
    )

# Health check
@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }

# Root endpoint
@app.get("/")
async def root():
    """Root endpoint"""
    return {
        "message": "Welcome to Nulo Africa API",
        "docs": "/api/docs",
        "version": "1.0.0"
    }

# Include routers
app.include_router(health.router, prefix="/api/v1",tags=["Health & Diagnostics"])
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(properties.router, prefix="/api/v1", tags=["Properties"])
app.include_router(applications.router, prefix="/api/v1", tags=["Applications"])
app.include_router(tenants.router, prefix="/api/v1", tags=["Tenants"])
app.include_router(favorites.router, prefix="/api/v1", tags=["Favorites"])
app.include_router(messages.router, prefix="/api/v1", tags=["Messages"])
app.include_router(viewing_requests.router, prefix="/api/v1", tags=["Viewing Requests"])
app.include_router(verifications.router, prefix="/api/v1", tags=["Verifications"])
app.include_router(admin_landlord_verification.router, prefix="/api/v1/admin", tags=["Admin Landlord Verification"])
app.include_router(property_verification.router, prefix="/api/v1/admin", tags=["Admin Property Verification"])
app.include_router(tenant_verification.router, prefix="/api/v1/admin", tags=["Tenant Verification"])
app.include_router(admin_management.router, prefix="/api/v1", tags=["Admin Management"])
app.include_router(admin_signup.router, prefix="/api/v1", tags=["Admin Signup"])
app.include_router(admin_dashboard.router, prefix="/api/v1", tags=["Admin Dashboard"])
app.include_router(admin_landlord_users.router, prefix="/api/v1", tags=["Admin Landlord Users"])
app.include_router(admin_tenant_users.router, prefix="/api/v1", tags=["Admin Tenant Users"])
app.include_router(landlord_onboarding.router, tags=["Landlord Onboarding"])
app.include_router(landlord_dashboard.router, prefix="/api/v1", tags=["Landlord Dashboard"])
app.include_router(tenant_dashboard.router, prefix="/api/v1", tags=["Tenant Dashboard"])
app.include_router(locations.router, tags=["Locations"])
app.include_router(notifications.router, prefix="/api/v1", tags=["Notifications"])
app.include_router(agreements.router, prefix="/api/v1", tags=["Agreements"])
app.include_router(maintenance.router, prefix="/api/v1", tags=["Maintenance"])
app.include_router(engagement.router, prefix="/api/v1", tags=["Engagement"])
app.include_router(banner_dismissals.router, prefix="/api/v1", tags=["Banner Dismissals"])
app.include_router(payments.router, prefix="/api/v1",tags=["Payment"])
app.include_router(nomba.router, prefix="/api/v1", tags=["Nomba Virtual Accounts"])
app.include_router(disbursements.router, prefix="/api/v1", tags=["Nomba Disbursements"])
app.include_router(license.router, prefix="/api/v1", tags=["License Management"])
app.include_router(groq_agreement.router, tags=["Groq AI Agreement"])

# Test / preview endpoints (NO AUTH) — useful for QA spot-checks of
# generated PDFs without going through the full sign flow. Exposed under
# /api/test/* so it is obviously a debug surface.
from app.routes.test_agreement import router as test_agreement_router
app.include_router(test_agreement_router, prefix="/api", tags=["Test & Preview"])


# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info(format_log(
        "api_starting",
        f"Nulo Africa API starting up | Environment: {settings.ENVIRONMENT}",
        environment=settings.ENVIRONMENT,
        supabase_url=settings.SUPABASE_URL,
        cors_origins=settings.cors_origins
    ))
    
    # Check license status
    from app.license import LicenseService
    is_valid, message = LicenseService.check_license_valid()
    status_info = LicenseService.get_status_info()
    logger.info(format_log(
        "license_check",
        f"License {'valid' if is_valid else 'invalid'}: {message} | Expires: {status_info.get('expiry_date', 'N/A')}",
        is_valid=is_valid,
        license_message=message,
        expiry_date=status_info.get('expiry_date', 'N/A')
    ))
    
 
# Shutdown event
@app.on_event("shutdown")
async def shutdown_event():
    logger.info("👋 Nulo Africa API shutting down...")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
