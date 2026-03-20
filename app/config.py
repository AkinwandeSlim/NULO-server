"""
Application configuration using Pydantic Settings
"""
from pydantic_settings import BaseSettings
from typing import List
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""
    
    # Supabase
    SUPABASE_URL: str
    SUPABASE_KEY: str
    SUPABASE_SERVICE_KEY: str
    SUPABASE_SERVICE_ROLE_KEY: str | None = None

    # Email Configuration (Resend preferred over SMTP)
    # Resend settings (recommended for production)
    RESEND_API_KEY: str | None = None
    FROM_EMAIL: str = "noreply@nuloafrica.com"
    
    # SMTP settings (fallback for development)
    SMTP_HOST: str | None = None
    SMTP_PORT: int | None = None
    SMTP_USER: str | None = None
    SMTP_PASSWORD: str | None = None
    
    # JWT
    JWT_SECRET_KEY: str
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 24 * 60  # 24 hours instead of 30 minutes
    
    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True
    ENVIRONMENT: str = "development"
    
    # CORS
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://nuloafrica.vercel.app"
    
    # Paystack (Optional)
    PAYSTACK_SECRET_KEY: str | None = None
    PAYSTACK_PUBLIC_KEY: str | None = None
    PAYSTACK_WEBHOOK_URL: str | None = None  # Local: https://abc123.ngrok.io, Cloud: https://nuloafrica.com
    
    # Environment
    ENV: str = "local"  # local | development | production
    
    # SMS Configuration (Optional)
    TWILIO_ACCOUNT_SID: str | None = None
    TWILIO_AUTH_TOKEN: str | None = None
    TWILIO_MESSAGING_SERVICE_SID: str | None = None
    TWILIO_FROM_NUMBER: str | None = None
    
    # Google Maps (Optional)
    GOOGLE_MAPS_API_KEY: str | None = None
    
    # Redis Configuration (Optional)
    REDIS_HOST: str = "localhost"
    REDIS_PORT: int = 6379
    REDIS_DB: int = 0
    REDIS_PASSWORD: str | None = None
    
    @property
    def cors_origins(self) -> List[str]:
        """Parse CORS origins from comma-separated string"""
        return [origin.strip() for origin in self.ALLOWED_ORIGINS.split(",")]
    
    @property
    def is_local(self) -> bool:
        """Check if running in local development"""
        return self.ENV == "local" or self.ENVIRONMENT == "development"
    
    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"  # Allow extra fields in .env


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()


# Global settings instance
settings = get_settings()


