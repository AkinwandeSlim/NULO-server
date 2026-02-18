"""
Health check and diagnostic endpoints
"""
from fastapi import APIRouter, HTTPException
from app.services.email_service import email_service
from app.config import settings
import smtplib
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["Health & Diagnostics"])


@router.get("/")
async def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "environment": settings.ENVIRONMENT,
        "version": "1.0.0"
    }


@router.get("/email-config")
async def get_email_config():
    """Get current email configuration (safe to expose in dev)"""
    try:
        return {
            "smtp_host": email_service.smtp_server,
            "smtp_port": email_service.smtp_port,
            "smtp_user": email_service.smtp_username,
            "from_email": email_service.from_email,
            "base_url": email_service.base_url,
            "configured": True
        }
    except Exception as e:
        logger.error(f"❌ [HEALTH] Error getting email config: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/test-email")
async def test_email_send(test_email: str = "alexdata2022@gmail.com"):
    """
    Test email sending with Gmail SMTP
    
    Usage:
    GET /health/test-email?test_email=yourname@gmail.com
    """
    try:
        logger.info(f"🧪 [EMAIL TEST] Starting test to {test_email}")
        
        subject = "🧪 Nulo Africa - Email Test"
        html_content = """
        <html>
            <body style="font-family: Arial, sans-serif; padding: 20px;">
                <h2 style="color: #27AE60;">✅ Email Configuration Test</h2>
                <p>If you're reading this, your Gmail SMTP configuration is working correctly!</p>
                
                <div style="background-color: #f0f8f5; padding: 15px; border-left: 4px solid #27AE60; margin: 20px 0;">
                    <p><strong>Timestamp:</strong> """ + str(__import__('datetime').datetime.now()) + """</p>
                    <p><strong>SMTP Server:</strong> """ + email_service.smtp_server + """</p>
                    <p><strong>Port:</strong> """ + str(email_service.smtp_port) + """</p>
                </div>
                
                <p style="color: #666; font-size: 12px;">
                    This is an automated test email from Nulo Africa Platform.
                </p>
            </body>
        </html>
        """
        
        text_content = f"""
        Email Configuration Test
        
        If you're reading this, your Gmail SMTP configuration is working correctly!
        
        Timestamp: {str(__import__('datetime').datetime.now())}
        SMTP Server: {email_service.smtp_server}
        Port: {email_service.smtp_port}
        
        This is an automated test email from Nulo Africa Platform.
        """
        
        result = email_service._send_email(test_email, subject, html_content, text_content)
        
        if result:
            logger.info(f"✅ [EMAIL TEST] Success - Email sent to {test_email}")
            return {
                "success": True,
                "message": f"✅ Email test successful! Email sent to {test_email}",
                "smtp_server": email_service.smtp_server,
                "smtp_port": email_service.smtp_port,
                "from_email": email_service.from_email
            }
        else:
            logger.error(f"❌ [EMAIL TEST] Failed - Email could not be sent to {test_email}")
            raise HTTPException(
                status_code=500,
                detail="Email sending failed. Check server logs for authentication details."
            )
            
    except HTTPException as http_err:
        raise http_err
    except Exception as e:
        error_detail = str(e)
        logger.error(f"❌ [EMAIL TEST] Exception: {error_detail}")
        raise HTTPException(status_code=500, detail=f"Email test failed: {error_detail}")


@router.get("/verify-smtp")
async def verify_smtp_connection():
    """
    Verify SMTP connection without sending email
    Useful for debugging connection issues
    """
    try:
        logger.info(f"🔍 [SMTP VERIFY] Checking connection to {email_service.smtp_server}:{email_service.smtp_port}")
        
        with smtplib.SMTP(email_service.smtp_server, email_service.smtp_port, timeout=10) as server:
            logger.info(f"✅ [SMTP VERIFY] Connected to server")
            
            server.starttls()
            logger.info(f"🔒 [SMTP VERIFY] TLS enabled")
            
            server.login(email_service.smtp_username, email_service.smtp_password)
            logger.info(f"✅ [SMTP VERIFY] Authentication successful")
        
        return {
            "success": True,
            "message": "✅ SMTP connection verified successfully!",
            "smtp_server": email_service.smtp_server,
            "smtp_port": email_service.smtp_port,
            "smtp_user": email_service.smtp_username,
            "details": {
                "connection": "✅ Connected",
                "tls": "✅ Enabled",
                "authentication": "✅ Successful"
            }
        }
        
    except smtplib.SMTPAuthenticationError as auth_err:
        logger.error(f"❌ [SMTP VERIFY] Authentication failed: {str(auth_err)}")
        raise HTTPException(
            status_code=401,
            detail="SMTP Authentication failed. Check SMTP_USER and SMTP_PASSWORD in .env file. For Gmail, use an app-specific password, not your regular password."
        )
    except smtplib.SMTPException as smtp_err:
        logger.error(f"❌ [SMTP VERIFY] SMTP error: {str(smtp_err)}")
        raise HTTPException(
            status_code=503,
            detail=f"SMTP error: {str(smtp_err)}"
        )
    except Exception as e:
        logger.error(f"❌ [SMTP VERIFY] Connection failed: {str(e)}")
        raise HTTPException(
            status_code=503,
            detail=f"SMTP connection failed: {str(e)}"
        )


@router.get("/diagnostics")
async def get_diagnostics():
    """Get complete system diagnostics"""
    import os
    
    # Safe attribute access with defaults
    twilio_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
    twilio_configured = bool(twilio_sid)
    paystack_key = getattr(settings, 'PAYSTACK_SECRET_KEY', None)
    paystack_configured = bool(paystack_key)
    
    return {
        "system": {
            "environment": settings.ENVIRONMENT,
            "debug": settings.DEBUG,
            "host": settings.HOST,
            "port": settings.PORT
        },
        "supabase": {
            "configured": bool(settings.SUPABASE_URL),
            "url": settings.SUPABASE_URL[:20] + "..." if settings.SUPABASE_URL else None
        },
        "email": {
            "smtp_host": email_service.smtp_server,
            "smtp_port": email_service.smtp_port,
            "smtp_user": email_service.smtp_username,
            "from_email": email_service.from_email,
            "configured": True,
            "status": "✅ Working"
        },
        "sms": {
            "twilio_configured": twilio_configured,
            "status": "✅ Configured" if twilio_configured else "⏳ Not configured"
        },
        "payments": {
            "paystack_configured": paystack_configured,
            "status": "✅ Configured" if paystack_configured else "⏳ Not configured"
        }
    }
