"""
Notification Service
Handles email notifications for onboarding and verification
"""

import logging
from typing import Dict, Any, Optional
from uuid import UUID
from datetime import datetime
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import smtplib
from jinja2 import Template

logger = logging.getLogger(__name__)


class NotificationService:
    """Service for sending email notifications"""
    
    def __init__(self):
        self.smtp_server = os.getenv('SMTP_SERVER', 'smtp.gmail.com')
        self.smtp_port = int(os.getenv('SMTP_PORT', '587'))
        self.smtp_username = os.getenv('SMTP_USERNAME', '')
        self.smtp_password = os.getenv('SMTP_PASSWORD', '')
        self.from_email = os.getenv('FROM_EMAIL', 'noreply@nuloafrica.com')
        self.base_url = os.getenv('BASE_URL', 'https://nulo-africa.vercel.app')
    
    async def send_verification_notification(
        self,
        recipient: str,
        subject: str,
        message: str,
        onboarding_id: Optional[UUID] = None,
        template_data: Optional[Dict[str, Any]] = None
    ):
        """Send verification notification"""
        try:
            # Prepare email content
            if template_data:
                html_content = await self._render_template(template_data['template'], template_data)
                text_content = await self._render_text_template(template_data['template'], template_data)
            else:
                html_content = self._create_default_html(message, onboarding_id)
                text_content = message
            
            # Send email
            await self._send_email(
                to_email=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content
            )
            
            logger.info(f"Notification sent to {recipient}: {subject}")
            
        except Exception as e:
            logger.error(f"Failed to send notification to {recipient}: {str(e)}")
            raise
    
    async def send_onboarding_started_notification(
        self,
        user_email: str,
        user_name: str,
        onboarding_id: UUID
    ):
        """Send notification when onboarding starts"""
        template_data = {
            'template': 'onboarding_started',
            'user_name': user_name,
            'onboarding_id': str(onboarding_id),
            'dashboard_url': f"{self.base_url}/onboarding/landlord/step-1",
            'support_email': 'support@nuloafrica.com'
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject="Welcome to NuloAfrica - Let's Complete Your Verification",
            message=f"Hi {user_name}, let's complete your 4Ps verification process.",
            onboarding_id=onboarding_id,
            template_data=template_data
        )
    
    async def send_step_completed_notification(
        self,
        user_email: str,
        user_name: str,
        step_number: int,
        next_step_url: str
    ):
        """Send notification when a step is completed"""
        template_data = {
            'template': 'step_completed',
            'user_name': user_name,
            'step_number': step_number,
            'next_step_url': next_step_url,
            'dashboard_url': self.base_url
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject=f"Step {step_number} Completed - Great Progress!",
            message=f"Hi {user_name}, you've completed step {step_number} of your verification.",
            template_data=template_data
        )
    
    async def send_onboarding_submitted_notification(
        self,
        user_email: str,
        user_name: str,
        onboarding_id: UUID
    ):
        """Send notification when onboarding is submitted for review"""
        template_data = {
            'template': 'onboarding_submitted',
            'user_name': user_name,
            'onboarding_id': str(onboarding_id),
            'verification_url': f"{self.base_url}/onboarding/landlord/verification-pending",
            'expected_time': "24-48 hours",
            'support_email': 'support@nuloafrica.com'
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject="Verification Submitted - We'll Review Your Documents",
            message=f"Hi {user_name}, your verification has been submitted for admin review.",
            onboarding_id=onboarding_id,
            template_data=template_data
        )
    
    async def send_verification_approved_notification(
        self,
        user_email: str,
        user_name: str,
        trust_score: int
    ):
        """Send notification when verification is approved"""
        template_data = {
            'template': 'verification_approved',
            'user_name': user_name,
            'trust_score': trust_score,
            'dashboard_url': f"{self.base_url}/landlord/overview",
            'list_property_url': f"{self.base_url}/landlord/properties/new",
            'support_email': 'support@nuloafrica.com'
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject=f"🎉 Verification Approved! Your Trust Score is {trust_score}%",
            message=f"Congratulations {user_name}! Your verification has been approved.",
            template_data=template_data
        )
    
    async def send_verification_rejected_notification(
        self,
        user_email: str,
        user_name: str,
        rejection_reason: str,
        onboarding_id: UUID
    ):
        """Send notification when verification is rejected"""
        template_data = {
            'template': 'verification_rejected',
            'user_name': user_name,
            'rejection_reason': rejection_reason,
            'onboarding_id': str(onboarding_id),
            'restart_url': f"{self.base_url}/onboarding/landlord/step-1",
            'support_email': 'support@nuloafrica.com'
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject="Verification Update - Action Required",
            message=f"Hi {user_name}, your verification needs attention.",
            onboarding_id=onboarding_id,
            template_data=template_data
        )
    
    async def send_admin_new_submission_notification(
        self,
        admin_email: str,
        landlord_name: str,
        onboarding_id: UUID,
        submission_time: datetime
    ):
        """Send notification to admin about new submission"""
        template_data = {
            'template': 'admin_new_submission',
            'landlord_name': landlord_name,
            'onboarding_id': str(onboarding_id),
            'submission_time': submission_time.strftime('%Y-%m-%d %H:%M'),
            'admin_url': f"{self.base_url}/admin/onboarding/queue",
            'review_url': f"{self.base_url}/admin/onboarding/details/{onboarding_id}"
        }
        
        await self.send_verification_notification(
            recipient=admin_email,
            subject=f"New Onboarding Submission - {landlord_name}",
            message=f"New onboarding submission from {landlord_name} requires review.",
            onboarding_id=onboarding_id,
            template_data=template_data
        )
    



    # ADD THIS if not present:
    async def send_admin_notification_new_submission(
        self,
        admin_email: str,
        landlord_name: str,
        landlord_email: str,
        onboarding_id: str
    ):
        """Send notification to admin about new landlord verification"""
        template_data = {
            'template': 'admin_new_submission',
            'landlord_name': landlord_name,
            'landlord_email': landlord_email,
            'onboarding_id': str(onboarding_id),
            'review_url': f"{self.base_url}/admin/landlord-verification/{onboarding_id}"
        }
        
        await self.send_verification_notification(
            recipient=admin_email,
            subject=f"🔔 New Landlord Verification: {landlord_name}",
            message=f"New landlord {landlord_name} has completed onboarding",
            onboarding_id=onboarding_id,
            template_data=template_data
        )




    async def send_document_processing_failed_notification(
        self,
        user_email: str,
        user_name: str,
        document_type: str,
        error_message: str
    ):
        """Send notification when document processing fails"""
        template_data = {
            'template': 'document_processing_failed',
            'user_name': user_name,
            'document_type': document_type,
            'error_message': error_message,
            'dashboard_url': f"{self.base_url}/onboarding/landlord/verification-pending",
            'support_email': 'support@nuloafrica.com'
        }
        
        await self.send_verification_notification(
            recipient=user_email,
            subject=f"Document Processing Issue - {document_type}",
            message=f"Hi {user_name}, there was an issue processing your {document_type}.",
            template_data=template_data
        )
    
    async def _send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str
    ):
        """Send email using SMTP"""
        try:
            # Create message
            msg = MIMEMultipart('alternative')
            msg['Subject'] = subject
            msg['From'] = f"NuloAfrica <{self.from_email}>"
            msg['To'] = to_email
            
            # Attach text and HTML parts
            text_part = MIMEText(text_content, 'plain')
            html_part = MIMEText(html_content, 'html')
            
            msg.attach(text_part)
            msg.attach(html_part)
            
            # Send email
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                server.send_message(msg)
            
            logger.info(f"Email sent successfully to {to_email}")
            
        except Exception as e:
            logger.error(f"Failed to send email: {str(e)}")
            raise
    
    def _create_default_html(self, message: str, onboarding_id: Optional[UUID] = None) -> str:
        """Create default HTML email template"""
        verification_url = f"{self.base_url}/onboarding/landlord/verification-pending" if onboarding_id else self.base_url
        
        html_template = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>NuloAfrica Notification</title>
            <style>
                body {{
                    font-family: Arial, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                .header {{
                    background: linear-gradient(135deg, #ff6b35, #f7931e);
                    color: white;
                    padding: 30px;
                    text-align: center;
                    border-radius: 10px 10px 0 0;
                }}
                .content {{
                    background: #f9f9f9;
                    padding: 30px;
                    border-radius: 0 0 10px 10px;
                }}
                .button {{
                    display: inline-block;
                    background: #ff6b35;
                    color: white;
                    padding: 12px 30px;
                    text-decoration: none;
                    border-radius: 5px;
                    margin: 20px 0;
                }}
                .footer {{
                    text-align: center;
                    margin-top: 30px;
                    color: #666;
                    font-size: 12px;
                }}
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏠 NuloAfrica</h1>
                <p>Trusted Property Marketplace</p>
            </div>
            <div class="content">
                <h2>Verification Update</h2>
                <p>{message}</p>
                <a href="{verification_url}" class="button">View Dashboard</a>
                <p>If you have any questions, please contact our support team.</p>
            </div>
            <div class="footer">
                <p>&copy; 2024 NuloAfrica. All rights reserved.</p>
                <p>Support: support@nuloafrica.com</p>
            </div>
        </body>
        </html>
        """
        
        return html_template
    
    async def _render_template(self, template_name: str, data: Dict[str, Any]) -> str:
        """Render HTML email template"""
        templates = {
            'onboarding_started': self._get_onboarding_started_template(),
            'step_completed': self._get_step_completed_template(),
            'onboarding_submitted': self._get_onboarding_submitted_template(),
            'verification_approved': self._get_verification_approved_template(),
            'verification_rejected': self._get_verification_rejected_template(),
            'admin_new_submission': self._get_admin_new_submission_template(),
            'document_processing_failed': self._get_document_processing_failed_template()
        }
        
        template_content = templates.get(template_name, self._get_default_template())
        template = Template(template_content)
        return template.render(**data)
    
    async def _render_text_template(self, template_name: str, data: Dict[str, Any]) -> str:
        """Render text email template"""
        text_templates = {
            'onboarding_started': f"""
Hi {data.get('user_name', 'User')},

Welcome to NuloAfrica! Let's complete your 4Ps verification process to unlock all features.

Get started here: {data.get('dashboard_url', '')}

The 4Ps verification includes:
1. Profile Verification (Identity documents)
2. Property Information
3. Payment Setup (Bank details)
4. Protection (Insurance & Guarantor)

This process typically takes 15-20 minutes to complete.

If you need any help, contact us at support@nuloafrica.com

Best regards,
The NuloAfrica Team
            """,
            'verification_approved': f"""
Congratulations {data.get('user_name', 'User')}! 🎉

Your verification has been approved with a trust score of {data.get('trust_score', 0)}%.

You can now:
- List properties on our marketplace
- Receive rental applications
- Manage your properties efficiently

Start listing your first property: {data.get('list_property_url', '')}

Thank you for choosing NuloAfrica!

Best regards,
The NuloAfrica Team
            """
        }
        
        return text_templates.get(template_name, f"Hi {data.get('user_name', 'User')},\n\n{data.get('message', '')}\n\nBest regards,\nThe NuloAfrica Team")
    
    def _get_onboarding_started_template(self) -> str:
        """HTML template for onboarding started"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Welcome to NuloAfrica</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: linear-gradient(135deg, #ff6b35, #f7931e); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }
                .content { background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }
                .button { display: inline-block; background: #ff6b35; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }
                .step { background: white; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #ff6b35; }
                .footer { text-align: center; margin-top: 30px; color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🏠 Welcome to NuloAfrica</h1>
                <p>Let's Complete Your 4Ps Verification</p>
            </div>
            <div class="content">
                <h2>Hi {{ user_name }},</h2>
                <p>Welcome to NuloAfrica! We're excited to have you join our trusted property marketplace.</p>
                <p>To get started, you'll need to complete our 4Ps verification process. This ensures safety and trust for all users.</p>
                
                <h3>The 4Ps Verification Process:</h3>
                <div class="step">
                    <strong>1. Profile Verification</strong><br>
                    Identity documents (NIN, BVN, ID card, selfie)
                </div>
                <div class="step">
                    <strong>2. Property Information</strong><br>
                    Details about properties you plan to list
                </div>
                <div class="step">
                    <strong>3. Payment Setup</strong><br>
                    Bank account details for rent collection
                </div>
                <div class="step">
                    <strong>4. Protection</strong><br>
                    Insurance and guarantor information
                </div>
                
                <p>This process typically takes 15-20 minutes to complete.</p>
                
                <a href="{{ dashboard_url }}" class="button">Start Verification</a>
                
                <p>If you need any help during this process, don't hesitate to contact our support team at {{ support_email }}.</p>
                
                <p>We're here to help you succeed in the Nigerian property market!</p>
            </div>
            <div class="footer">
                <p>&copy; 2024 NuloAfrica. All rights reserved.</p>
                <p>Support: {{ support_email }}</p>
            </div>
        </body>
        </html>
        """
    
    def _get_verification_approved_template(self) -> str:
        """HTML template for verification approved"""
        return """
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <meta name="viewport" content="width=device-width, initial-scale=1.0">
            <title>Verification Approved!</title>
            <style>
                body { font-family: Arial, sans-serif; line-height: 1.6; color: #333; max-width: 600px; margin: 0 auto; padding: 20px; }
                .header { background: linear-gradient(135deg, #28a745, #20c997); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }
                .content { background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }
                .trust-score { background: #28a745; color: white; padding: 20px; border-radius: 10px; text-align: center; margin: 20px 0; }
                .button { display: inline-block; background: #28a745; color: white; padding: 12px 30px; text-decoration: none; border-radius: 5px; margin: 20px 0; }
                .feature { background: white; padding: 15px; margin: 10px 0; border-radius: 5px; border-left: 4px solid #28a745; }
                .footer { text-align: center; margin-top: 30px; color: #666; font-size: 12px; }
            </style>
        </head>
        <body>
            <div class="header">
                <h1>🎉 Verification Approved!</h1>
                <p>You're Now a Verified Landlord</p>
            </div>
            <div class="content">
                <h2>Congratulations, {{ user_name }}!</h2>
                <p>Your verification has been approved and you're now ready to list properties on NuloAfrica.</p>
                
                <div class="trust-score">
                    <h3>Your Trust Score: {{ trust_score }}%</h3>
                    <p>This score reflects the completeness and accuracy of your verification</p>
                </div>
                
                <h3>What You Can Do Now:</h3>
                <div class="feature">
                    <strong>🏠 List Properties</strong><br>
                    Add your rental properties to our marketplace
                </div>
                <div class="feature">
                    <strong>📋 Receive Applications</strong><br>
                    Get rental applications from verified tenants
                </div>
                <div class="feature">
                    <strong>💰 Manage Payments</strong><br>
                    Collect rent securely through our platform
                </div>
                <div class="feature">
                    <strong>📊 Track Performance</strong><br>
                    Monitor occupancy and rental income
                </div>
                
                <a href="{{ list_property_url }}" class="button">List Your First Property</a>
                <a href="{{ dashboard_url }}" class="button" style="background: #6c757d; margin-left: 10px;">Go to Dashboard</a>
                
                <p>Thank you for choosing NuloAfrica. We're committed to helping you succeed in the Nigerian property market!</p>
            </div>
            <div class="footer">
                <p>&copy; 2024 NuloAfrica. All rights reserved.</p>
                <p>Support: {{ support_email }}</p>
            </div>
        </body>
        </html>
        """
    
    def _get_default_template(self) -> str:
        """Default HTML template"""
        return self._create_default_html("{{ message }}")
    
    def _get_step_completed_template(self) -> str:
        return self._get_default_template()
    
    def _get_onboarding_submitted_template(self) -> str:
        return self._get_default_template()
    
    def _get_verification_rejected_template(self) -> str:
        return self._get_default_template()
    
    def _get_admin_new_submission_template(self) -> str:
        return self._get_default_template()
    
    def _get_document_processing_failed_template(self) -> str:
        return self._get_default_template()


# Global instance
notification_service = NotificationService()


# Async functions for background tasks
async def send_verification_notification(
    recipient: str,
    subject: str,
    message: str,
    onboarding_id: Optional[UUID] = None,
    template_data: Optional[Dict[str, Any]] = None
):
    """Async wrapper for sending verification notification"""
    await notification_service.send_verification_notification(
        recipient, subject, message, onboarding_id, template_data
    )
