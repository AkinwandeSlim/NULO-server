"""
Nulo Africa - FastAPI Backend
Main application entry point
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.config import settings
from app.routes import auth, properties, applications, tenants, favorites, messages, viewing_requests
import logging

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

# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request, exc):
    logger.error(f"Global exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "success": False,
            "error": "Internal server error",
            "detail": str(exc) if settings.DEBUG else "An error occurred"
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
app.include_router(auth.router, prefix="/api/v1", tags=["Authentication"])
app.include_router(properties.router, prefix="/api/v1", tags=["Properties"])
app.include_router(applications.router, prefix="/api/v1", tags=["Applications"])
app.include_router(tenants.router, prefix="/api/v1", tags=["Tenants"])
app.include_router(favorites.router, prefix="/api/v1", tags=["Favorites"])
app.include_router(messages.router, prefix="/api/v1", tags=["Messages"])
app.include_router(viewing_requests.router, prefix="/api/v1", tags=["Viewing Requests"])

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
