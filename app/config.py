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

    # Email Configuration (Brevo preferred over SMTP)
    # Brevo settings (recommended for production)
    BREVO_API_KEY: str | None = None
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
    ALLOWED_ORIGINS: str = "http://localhost:3000,https://nuloafrica.vercel.app,https://nuloafrica.com,https://www.nuloafrica.com"

    # Frontend URL used for Supabase auth email redirects (signup, password reset).
    # Falls back to the first allowed CORS origin if unset. Set this in production
    # to your public frontend URL (e.g. https://nuloafrica.com) so verification
    # links land on the correct domain instead of localhost.
    FRONTEND_URL: str | None = None
    
    # ---------------------------------------------------------------
    # Paystack -- DEPRECATED for the hackathon (2026-07-05)
    # Hackathon payment flow uses Nomba virtual accounts.
    # These fields are kept as optional/None for backwards-compat with
    # any local env that still has them set; the Paystack code path
    # has been replaced by app/routes/payments.py (410 Gone shim) and
    # app/routes/payments-backup.py (preserved for reference only).
    # ---------------------------------------------------------------
    PAYSTACK_SECRET_KEY: str | None = None   # DEPRECATED: see payments.py shim
    PAYSTACK_PUBLIC_KEY: str | None = None   # DEPRECATED
    PAYSTACK_WEBHOOK_URL: str | None = None  # DEPRECATED
    PAYSTACK_API_URL: str = "https://api.paystack.co"  # DEPRECATED
    
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

    # Feature Flags
    # ENABLE_PROPERTY_STEP: Controls whether landlord onboarding requires
    # Step 3 (Property Information). When False, landlords can skip this step
    # without errors. Default: True for backward compatibility.
    ENABLE_PROPERTY_STEP: bool = True
    
    # DEMO_MODE: When True, skips actual Nomba bank transfers for testing
    # with fictional bank accounts. Set to False in production for real transfers.
    DEMO_MODE: bool = False
    
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


