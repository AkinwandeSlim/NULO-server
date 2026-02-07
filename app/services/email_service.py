"""
Simple Email Service using Gmail SMTP or Resend
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List

class EmailService:
    def __init__(self):
        # Gmail SMTP (easier for testing)
        self.smtp_server = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = 587
        self.smtp_username = os.getenv("SMTP_USERNAME", "your-email@gmail.com")
        self.smtp_password = os.getenv("SMTP_PASSWORD", "your-app-password")
        self.from_email = os.getenv("FROM_EMAIL", "noreply@nulo.com")
    
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
                <a href="http://localhost:3000/admin/onboarding/review/{onboarding_id}" 
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
                msg = MIMEMultipart('alternative')
                msg['Subject'] = subject
                msg['From'] = self.from_email
                msg['To'] = admin_email
                
                html_part = MIMEText(html_content, 'html')
                msg.attach(html_part)
                
                with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                    server.starttls()
                    server.login(self.smtp_username, self.smtp_password)
                    server.send_message(msg)
                
                print(f"✅ [EMAIL] Sent to {admin_email}")
            
            return True
            
        except Exception as e:
            print(f"❌ [EMAIL] Error: {str(e)}")
            return False

# Singleton
email_service = EmailService()