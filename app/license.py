"""
NuloAfrica License & Expiry System
Protects app from unauthorized use by investors/co-founders
Uses Supabase for persistent storage and secure license management
"""

from datetime import datetime, timedelta
from enum import Enum
import os
from app.database import get_supabase_client


class LicenseStatus(str, Enum):
    ACTIVE = "active"
    EXPIRING_SOON = "expiring_soon"
    EXPIRED = "expired"
    UNDEFINED = "undefined"


class LicenseConfig:
    """Application license configuration"""
    
    # Initial 3-month protection period
    INITIAL_EXPIRY_DATE = (datetime.utcnow() + timedelta(days=90)).isoformat()
    
    # Warning period - show warning if expiring within 7 days
    EXPIRY_WARNING_DAYS = 7
    
    # License key (secret) - only you/trusted founders know this
    # Use environment variable for security
    LICENSE_KEY = os.getenv("NULO_LICENSE_KEY", "nulo-africa-alex-key-2026")
    
    # Grace period - app still works but shows stark warning
    GRACE_PERIOD_DAYS = 3
    
    @staticmethod
    def get_license_status(expiry_date: str) -> LicenseStatus:
        """
        Check license status based on expiry date
        
        Returns:
            LicenseStatus enum indicating status
        """
        try:
            expiry = datetime.fromisoformat(expiry_date)
            
            # Handle timezone-aware expiry dates
            if expiry.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            else:
                now = datetime.utcnow()
            
            if now > expiry:
                return LicenseStatus.EXPIRED
            
            days_until_expiry = (expiry - now).days
            if days_until_expiry <= LicenseConfig.EXPIRY_WARNING_DAYS:
                return LicenseStatus.EXPIRING_SOON
            
            return LicenseStatus.ACTIVE
        except Exception as e:
            print(f"❌ Error getting license status: {str(e)}")
            return LicenseStatus.UNDEFINED
    
    @staticmethod
    def extend_license(current_expiry: str, days: int = 90) -> str:
        """
        Extend license by adding days
        
        Args:
            current_expiry: Current expiry date (ISO format)
            days: Days to extend (default 90 days / 3 months)
        
        Returns:
            New expiry date (ISO format)
        """
        try:
            expiry = datetime.fromisoformat(current_expiry)
            
            # Handle timezone-aware dates
            if expiry.tzinfo is not None:
                from datetime import timezone
                now = datetime.now(timezone.utc)
            else:
                now = datetime.utcnow()
            
            if expiry < now:
                # If already expired, start from today
                expiry = now
            new_expiry = expiry + timedelta(days=days)
            return new_expiry.isoformat()
        except Exception as e:
            print(f"❌ Error extending license: {str(e)}")
            # If parse fails, create new expiry from today
            from datetime import timezone
            return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    
    @staticmethod
    def get_time_remaining(expiry_date: str) -> dict:
        """
        Get human-readable time remaining
        
        Returns:
            {
                "days": int,
                "hours": int,
                "status": "active" | "expiring_soon" | "expired",
                "message": str
            }
        """
        try:
            # Parse expiry date (handles both with/without timezone)
            expiry = datetime.fromisoformat(expiry_date)
            
            # Get current time - make it timezone-aware if expiry is timezone-aware
            if expiry.tzinfo is not None:
                # expiry has timezone, so make now timezone-aware (UTC)
                from datetime import timezone
                now = datetime.now(timezone.utc)
            else:
                # expiry is naive, use naive UTC
                now = datetime.utcnow()
            
            if now > expiry:
                return {
                    "days": 0,
                    "hours": 0,
                    "status": LicenseStatus.EXPIRED,
                    "message": "License has expired"
                }
            
            remaining = expiry - now
            days = remaining.days
            hours = remaining.seconds // 3600
            
            if days <= LicenseConfig.EXPIRY_WARNING_DAYS:
                status = LicenseStatus.EXPIRING_SOON
                message = f"License expiring in {days} days and {hours} hours"
            else:
                status = LicenseStatus.ACTIVE
                message = f"License valid for {days} days"
            
            return {
                "days": days,
                "hours": hours,
                "status": status,
                "message": message
            }
        except Exception as e:
            print(f"❌ Error calculating time remaining: {str(e)}")
            return {
                "days": -1,
                "hours": -1,
                "status": LicenseStatus.UNDEFINED,
                "message": "Unable to verify license"
            }


# Supabase table for license storage
LICENSE_TABLE = "licenses"
LICENSE_KEY = "nulo_main_license"


class LicenseService:
    """Service for managing app license with Supabase storage"""
    
    @staticmethod
    def get_license() -> dict:
        """Get current license info from Supabase"""
        try:
            supabase = get_supabase_client()
            response = supabase.table(LICENSE_TABLE).select("*").eq("license_key", LICENSE_KEY).single().execute()
            
            if response.data:
                return response.data
            
            # Fallback: return default if not found
            return {
                "license_key": LICENSE_KEY,
                "expiry_date": LicenseConfig.INITIAL_EXPIRY_DATE,
                "created_at": datetime.utcnow().isoformat(),
                "extended_count": 0,
                "last_extended_at": None,
                "status": "active"
            }
        except Exception as e:
            print(f"❌ Error getting license: {str(e)}")
            # Return safe default on error (don't break app)
            return {
                "license_key": LICENSE_KEY,
                "expiry_date": LicenseConfig.INITIAL_EXPIRY_DATE,
                "extended_count": 0,
                "last_extended_at": None,
                "status": "active"
            }
    
    @staticmethod
    def check_license_valid() -> tuple[bool, str]:
        """
        Check if license is valid
        
        Returns:
            (is_valid: bool, message: str)
        """
        try:
            license_info = LicenseService.get_license()
            expiry_date = license_info.get("expiry_date")
            
            status = LicenseConfig.get_license_status(expiry_date)
            
            if status == LicenseStatus.EXPIRED:
                return False, "License expired: Application is not available. Please contact support."
            
            if status == LicenseStatus.EXPIRING_SOON:
                time_info = LicenseConfig.get_time_remaining(expiry_date)
                return True, f"⚠️ License expiring: {time_info['message']}"
            
            return True, "License active"
        except Exception as e:
            print(f"❌ License check error: {str(e)}")
            # On error, allow access but log it
            return True, "License check unavailable (allowing access)"
    
    @staticmethod
    def extend_license(license_key: str, days: int = 90) -> tuple[bool, str]:
        """
        Extend license (requires secret license key)
        
        Args:
            license_key: Secret license key for verification
            days: Days to extend (default 90 days / 3 months)
        
        Returns:
            (success: bool, message: str)
        """
        try:
            # Verify license key
            if license_key != LicenseConfig.LICENSE_KEY:
                return False, "Invalid license key"
            
            license_info = LicenseService.get_license()
            current_expiry = license_info.get("expiry_date")
            
            new_expiry = LicenseConfig.extend_license(current_expiry, days)
            
            # Update license in Supabase
            supabase = get_supabase_client()
            response = supabase.table(LICENSE_TABLE).update({
                "expiry_date": new_expiry,
                "extended_count": license_info.get("extended_count", 0) + 1,
                "last_extended_at": datetime.utcnow().isoformat()
            }).eq("license_key", LICENSE_KEY).execute()
            
            if response.data:
                return True, f"✅ License extended until {new_expiry}"
            else:
                return False, "Failed to update license in database"
        
        except Exception as e:
            print(f"❌ License extension error: {str(e)}")
            return False, f"Error extending license: {str(e)}"
    
    @staticmethod
    def get_status_info() -> dict:
        """Get detailed license status info"""
        try:
            license_info = LicenseService.get_license()
            expiry_date = license_info.get("expiry_date")
            
            time_info = LicenseConfig.get_time_remaining(expiry_date)
            
            return {
                **license_info,
                "current_time": datetime.utcnow().isoformat(),
                "time_remaining": time_info,
                "database": "supabase"  # Indicate source
            }
        except Exception as e:
            print(f"❌ Error getting status info: {str(e)}")
            return {
                "error": str(e),
                "current_time": datetime.utcnow().isoformat(),
                "database": "supabase"
            }
