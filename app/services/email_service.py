"""
Email Service using Brevo (primary) or SMTP (fallback)
"""

import os
import smtplib
import httpx
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List
from app.config import settings
import logging

logger = logging.getLogger(__name__)

class EmailService:
    def __init__(self):
        # Brevo configuration (preferred)
        self.brevo_api_key = settings.BREVO_API_KEY
        self.from_email = settings.FROM_EMAIL
        self.from_display = f"Nulo Africa <{self.from_email}>"
        
        # SMTP configuration (fallback)
        self.smtp_server = settings.SMTP_HOST or "smtp.gmail.com"
        self.smtp_port = int(settings.SMTP_PORT or 587)
        self.smtp_username = settings.SMTP_USER or os.getenv("SMTP_USER", "your-email@gmail.com")
        self.smtp_password = settings.SMTP_PASSWORD or os.getenv("SMTP_PASSWORD", "your-app-password")
        
        # Base URL for links
        self.base_url = os.getenv("BASE_URL", "http://localhost:3000")
        
        # Determine email method
        self.use_brevo = bool(self.brevo_api_key)
        
        if self.use_brevo:
            print(f"📧 [EMAIL] Using Brevo API")
        else:
            print(f"📧 [EMAIL] Using SMTP fallback: {self.smtp_server}:{self.smtp_port}")

    def send_landlord_onboarding_notification(
        self,
        admin_emails: List[str],
        landlord_name: str,
        landlord_email: str,
        onboarding_id: str
    ):
        """Send email to admins when landlord submits onboarding"""

        subject = f"🔔 New Landlord Verification: {landlord_name}"

        html_content = f"""
        <html>
        <body style="font-family: Arial, sans-serif;">
            <h2 style="color: #2563eb;">New Landlord Onboarding Submitted</h2>
            <p><strong>Landlord:</strong> {landlord_name}</p>
            <p><strong>Email:</strong> {landlord_email}</p>
            <p><strong>Status:</strong> Pending Review</p>
            <p>
                <a href="{self.base_url}/admin/onboarding/review/{onboarding_id}"
                   style="background: #2563eb; color: white; padding: 10px 20px;
                          text-decoration: none; border-radius: 5px;">
                    Review Application →
                </a>
            </p>
            <p style="color: #666; font-size: 12px;">
                Please review and approve/reject this application.
            </p>
        </body>
        </html>
        """

        try:
            for admin_email in admin_emails:
                return self._send_email(admin_email, subject, html_content)

            return True

        except Exception as e:
            print(f"❌ [EMAIL] Error: {str(e)}")
            return False

    def send_viewing_confirmation_email(
        self,
        tenant_email: str,
        tenant_name: str,
        property_title: str,
        date: str,
        time: str,
        viewing_id: str
    ):
        """Send viewing confirmation email to tenant"""

        subject = f"Viewing Confirmed - {property_title} ✓"

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #FF7A00;">✓ Your Viewing is Confirmed!</h2>

                    <p>Hi {tenant_name},</p>

                    <p>Great news! Your viewing request has been confirmed. Here are the details:</p>

                    <div style="background-color: #fff7f2; padding: 15px; border-left: 4px solid #FF7A00; margin: 20px 0;">
                        <p><strong>Property:</strong> {property_title}</p>
                        <p><strong>Date:</strong> {date}</p>
                        <p><strong>Time:</strong> {time}</p>
                    </div>

                    <p>Please arrive on time. If you need to reschedule, contact the landlord as soon as possible.</p>

                    <p>
                        <a href="{self.base_url}/tenant/viewings/{viewing_id}"
                            style="background-color: #FF7A00; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">
                            View Details
                        </a>
                    </p>

                    <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                    <p style="color: #666; font-size: 12px;">
                        NuloAfrica - Zero Agency Fee Rental Platform<br>
                        Questions? Contact us at support@nuloafrica.com
                    </p>
                </div>
            </body>
        </html>
        """

        text_content = f"""
Your Viewing is Confirmed!

Hi {tenant_name},

Great news! Your viewing request has been confirmed.

Property: {property_title}
Date: {date}
Time: {time}

Please arrive on time. If you need to reschedule, contact the landlord as soon as possible.

View Details: {self.base_url}/tenant/viewings/{viewing_id}

---
NuloAfrica - Zero Agency Fee Rental Platform
        """

        return self._send_email(tenant_email, subject, html_content, text_content)

    def send_landlord_viewing_notification_email(
        self,
        landlord_email: str,
        landlord_name: str,
        tenant_name: str,
        property_title: str,
        date: str,
        time: str,
        viewing_id: str
    ):
        """Send viewing notification email to landlord"""

        subject = f"New Viewing Scheduled - {property_title}"

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #FF7A00;">📅 New Viewing Scheduled</h2>

                    <p>Hi {landlord_name},</p>

                    <p>A tenant has scheduled a viewing for your property. Here are the details:</p>

                    <div style="background-color: #fff7f2; padding: 15px; border-left: 4px solid #FF7A00; margin: 20px 0;">
                        <p><strong>Property:</strong> {property_title}</p>
                        <p><strong>Tenant:</strong> {tenant_name}</p>
                        <p><strong>Date:</strong> {date}</p>
                        <p><strong>Time:</strong> {time}</p>
                    </div>

                    <p>Please make sure you're available at the scheduled time.</p>

                    <p>
                        <a href="{self.base_url}/landlord/viewings"
                            style="background-color: #FF7A00; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">
                            View Details & Contact Tenant
                        </a>
                    </p>

                    <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                    <p style="color: #666; font-size: 12px;">
                        NuloAfrica - Zero Agency Fee Rental Platform<br>
                        Questions? Contact us at support@nuloafrica.com
                    </p>
                </div>
            </body>
        </html>
        """

        text_content = f"""
New Viewing Scheduled

Hi {landlord_name},

A tenant has scheduled a viewing for your property.

Property: {property_title}
Tenant: {tenant_name}
Date: {date}
Time: {time}

Please make sure you're available at the scheduled time.

View Details: {self.base_url}/landlord/viewings

---
NuloAfrica - Zero Agency Fee Rental Platform
        """

        return self._send_email(landlord_email, subject, html_content, text_content)

    def send_viewing_reminder_email(
        self,
        tenant_email: str,
        tenant_name: str,
        property_title: str,
        date: str,
        time: str,
        hours_until: int,
        viewing_id: str
    ):
        """Send viewing reminder email to tenant"""

        if hours_until == 24:
            subject = f"Reminder: Your Viewing Tomorrow - {property_title}"
            message = "Your viewing is tomorrow!"
        elif hours_until == 1:
            subject = f"Reminder: Your Viewing is in 1 Hour - {property_title}"
            message = "Your viewing is in 1 hour!"
        else:
            subject = f"Reminder: Upcoming Viewing - {property_title}"
            message = f"Your viewing is in {hours_until} hours!"

        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333; background-color: #f5f5f5;">
                <div style="max-width: 600px; margin: 0 auto; background-color: white; padding: 20px; border-radius: 8px;">
                    <h2 style="color: #FF7A00;">⏰ {message}</h2>

                    <p>Hi {tenant_name},</p>

                    <p>Just a friendly reminder about your upcoming viewing:</p>

                    <div style="background-color: #fff7f2; padding: 15px; border-left: 4px solid #FF7A00; margin: 20px 0;">
                        <p><strong>Property:</strong> {property_title}</p>
                        <p><strong>Date:</strong> {date}</p>
                        <p><strong>Time:</strong> {time}</p>
                    </div>

                    <p>Please confirm you're still planning to attend. If you need to reschedule or cancel, let the landlord know right away.</p>

                    <p>
                        <a href="{self.base_url}/tenant/viewings/{viewing_id}"
                            style="background-color: #FF7A00; color: white; padding: 10px 20px; text-decoration: none; border-radius: 4px; display: inline-block;">
                            View Viewing Details
                        </a>
                    </p>

                    <hr style="border: none; border-top: 1px solid #ddd; margin: 30px 0;">

                    <p style="color: #666; font-size: 12px;">
                        NuloAfrica - Zero Agency Fee Rental Platform<br>
                        Questions? Contact us at support@nuloafrica.com
                    </p>
                </div>
            </body>
        </html>
        """

        text_content = f"""
{message}

Hi {tenant_name},

Just a friendly reminder about your upcoming viewing:

Property: {property_title}
Date: {date}
Time: {time}

Please confirm you're still planning to attend.

View Details: {self.base_url}/tenant/viewings/{viewing_id}

---
NuloAfrica - Zero Agency Fee Rental Platform
        """

        return self._send_email(tenant_email, subject, html_content, text_content)

    def _send_email(self, to_email: str, subject: str, html_content: str, text_content: str = None):
        """Send email using Brevo (primary) or SMTP (fallback)"""
        
        if self.use_brevo:
            return self._send_via_brevo(to_email, subject, html_content, text_content)
        else:
            return self._send_via_smtp(to_email, subject, html_content, text_content)
    
    def _send_via_brevo(self, to_email, subject, html_content, text_content=None):
        try:
            print(f"📧 [BREVO] Sending to {to_email}: {subject}")
            payload = {
                "sender": {"name": "Nulo Africa", "email": self.from_email},
                "to": [{"email": to_email}],
                "subject": subject,
                "htmlContent": html_content
            }
            if text_content:
                payload["textContent"] = text_content

            with httpx.Client(timeout=30.0) as client:
                response = client.post(
                    "https://api.brevo.com/v3/smtp/email",
                    headers={
                        "api-key": self.brevo_api_key,
                        "Content-Type": "application/json"
                    },
                    json=payload
                )
            if response.status_code == 201:
                message_id = response.json().get("messageId")
                logger.info(f"✅ [BREVO] Email sent successfully. Message ID: {message_id}")
                print(f"✅ [BREVO] Successfully sent to {to_email}")
                return {"success": True, "message_id": message_id}
            else:
                error_msg = f"❌ [BREVO] API Error {response.status_code}: {response.text}"
                logger.error(error_msg)
                print(error_msg)
                return {"success": False, "error": f"API Error {response.status_code}"}
        except Exception as e:
            error_msg = f"❌ [BREVO] Failed: {str(e)}"
            logger.error(error_msg)
            print(error_msg)
            return {"success": False, "error": str(e)}
    
    def _send_via_smtp(self, to_email: str, subject: str, html_content: str, text_content: str = None):
        """Send email via SMTP (fallback method)"""
        try:
            print(f"📧 [SMTP] Sending to {to_email}: {subject}")
            logger.info(f"🔧 [SMTP CONFIG] Server: {self.smtp_server}:{self.smtp_port}, From: {self.from_email}")

            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = getattr(self, 'from_display', self.from_email)
            msg['To'] = to_email

            if text_content:
                msg.attach(MIMEText(text_content, 'plain'))

            msg.attach(MIMEText(html_content, 'html'))

            logger.info(f"🔐 [SMTP] Attempting SMTP connection to {self.smtp_server}:{self.smtp_port}")

            try:
                from email.utils import make_msgid
                msgid = make_msgid()
                msg['Message-ID'] = msgid
                logger.info(f"🔎 [SMTP] Message-ID: {msgid}")
            except Exception:
                msgid = None

            with smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=10) as server:
                logger.info(f"✅ [SMTP] SMTP connection established")
                server.starttls()
                logger.info(f"🔒 [SMTP] TLS enabled")
                server.login(self.smtp_username, self.smtp_password)
                logger.info(f"✅ [SMTP] Authentication successful")
                server.send_message(msg)
                logger.info(f"✅ [SMTP] Message sent successfully")
                if msgid:
                    logger.info(f"📥 [SMTP] Sent Message-ID {msgid} to {to_email}")

            print(f"✅ [SMTP] Successfully sent to {to_email}")
            return {"success": True, "message_id": msgid}

        except smtplib.SMTPAuthenticationError as auth_err:
            error_msg = f"❌ [SMTP] Authentication failed: Check SMTP_USER and SMTP_PASSWORD in .env - {str(auth_err)}"
            logger.error(error_msg)
            print(error_msg)
            return {"success": False, "error": str(auth_err)}
        except smtplib.SMTPException as smtp_err:
            error_msg = f"❌ [SMTP] SMTP Error: {str(smtp_err)}"
            logger.error(error_msg)
            print(error_msg)
            return {"success": False, "error": str(smtp_err)}
        except Exception as e:
            error_msg = f"❌ [SMTP] Failed to send: {str(e)}"
            logger.error(error_msg)
            print(error_msg)
            return {"success": False, "error": str(e)}


# Singleton
email_service = EmailService()