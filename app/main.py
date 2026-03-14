"""
Nulo Africa - FastAPI Backend
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from app.config import settings
from app.routes import (
    auth, properties, applications, tenants, favorites,
    messages, viewing_requests, verifications, google,
    admin_landlord_verification, property_verification, 
    tenant_verification, admin_signup,admin_management,
    landlord_onboarding, landlord_dashboard, tenant_dashboard, notifications, admin_dashboard,
    admin_landlord_users, admin_tenant_users, locations, agreements, maintenance, health,
    engagement,payments,
)

import logging
from dotenv import load_dotenv
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

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

# Validation error handler
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request, exc):
    logger.error(f"Validation error: {exc}")
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
    logger.error(f"Global exception: {error_msg}")
    
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
app.include_router(health.router, tags=["Health & Diagnostics"])
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(google.router, tags=["Google Auth"])
app.include_router(properties.router, prefix="/api/v1", tags=["Properties"])
app.include_router(applications.router, prefix="/api/v1", tags=["Applications"])
app.include_router(tenants.router, prefix="/api/v1", tags=["Tenants"])
app.include_router(favorites.router, prefix="/api/v1", tags=["Favorites"])
app.include_router(messages.router, prefix="/api/v1", tags=["Messages"])
app.include_router(viewing_requests.router, prefix="/api/v1", tags=["Viewing Requests"])
app.include_router(verifications.router, prefix="/api/v1", tags=["Verifications"])
app.include_router(admin_landlord_verification.router, prefix="/api/v1/admin", tags=["Admin Landlord Verification"])
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
app.include_router(payments.router, prefix="/api/v1",tags=["Payment"])


# Startup event
@app.on_event("startup")
async def startup_event():
    logger.info("🚀 Nulo Africa API starting up...")
    logger.info(f"📍 Environment: {settings.ENVIRONMENT}")
    logger.info(f"🔗 Supabase URL: {settings.SUPABASE_URL}")
    logger.info(f"🌐 CORS Origins: {settings.cors_origins}")
    
 
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
