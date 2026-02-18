"""
SMS Service - Send SMS via Twilio
Usage: sms_service.send_sms("+234XXXXXXXXXX", "Your message")
"""

import os
import logging
from typing import Optional
from datetime import datetime

try:
    from twilio.rest import Client
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    Client = None

logger = logging.getLogger(__name__)


class SMSService:
    """
    Send SMS via Twilio
    Supports both US numbers and international numbers
    """
    
    def __init__(self):
        self.account_sid = os.getenv('TWILIO_ACCOUNT_SID')
        self.auth_token = os.getenv('TWILIO_AUTH_TOKEN')
        self.messaging_service_sid = os.getenv('TWILIO_MESSAGING_SERVICE_SID')
        self.from_number = os.getenv('TWILIO_FROM_NUMBER')
        
        # Initialize Twilio client
        self.client = None
        if self.account_sid and self.auth_token:
            if TWILIO_AVAILABLE:
                self.client = Client(self.account_sid, self.auth_token)
                logger.info("✅ Twilio client initialized")
            else:
                logger.warning("⚠️ Twilio package not installed. Install with: pip install twilio")
        else:
            logger.warning("⚠️ Twilio credentials not set in environment variables")
    
    def format_phone(self, phone: str) -> str:
        """
        Format phone number to E.164 format
        Examples:
          "08012345678" → "+2348012345678"
          "8012345678" → "+18012345678"
          "+2348012345678" → "+2348012345678"
          "2348012345678" → "+2348012345678"
        """
        phone = phone.strip().replace(" ", "").replace("-", "")
        
        # Already in +format
        if phone.startswith('+'):
            return phone
        
        # Nigerian number starting with 0 (convert to +234)
        if phone.startswith('0') and len(phone) == 11:
            return '+234' + phone[1:]
        
        # Nigerian number with country code (no +)
        if phone.startswith('234') and len(phone) == 13:
            return '+' + phone
        
        # US number (10 digits, add +1)
        if len(phone) == 10 and phone.isdigit():
            return '+1' + phone
        
        # Assume it already has country code, just add +
        if phone.isdigit() and not phone.startswith('+'):
            return '+' + phone
        
        return phone
    
    def validate_phone(self, phone: str) -> bool:
        """Validate phone number (basic check)"""
        formatted = self.format_phone(phone)
        # Should have + and at least 10 digits
        return formatted.startswith('+') and len(formatted) >= 11 and formatted[1:].isdigit()
    
    def send_sms(self, phone: str, message: str) -> bool:
        """
        Send SMS to a phone number via Twilio
        
        Args:
            phone: Phone number (any format)
            message: SMS message content
        
        Returns: True if successful, False otherwise
        """
        try:
            # Validate inputs
            if not phone:
                logger.error("❌ Phone number is empty")
                return False
            
            if not message:
                logger.error("❌ Message is empty")
                return False
            
            # Format and validate phone
            formatted_phone = self.format_phone(phone)
            
            if not self.validate_phone(formatted_phone):
                logger.error(f"❌ Invalid phone number: {phone} (formatted: {formatted_phone})")
                return False
            
            # Truncate message if too long (SMS limit is 160 chars, but we allow more)
            if len(message) > 320:
                logger.warning(f"⚠️ Message too long ({len(message)} chars), truncating...")
                message = message[:320]
            
            # Check if Twilio is configured
            if not self.client:
                logger.warning(f"⚠️ Twilio not configured, would send to {formatted_phone}: {message}")
                return True  # Return True in test mode
            
            # Send SMS
            logger.info(f"📱 Sending SMS to {formatted_phone}: {len(message)} chars")
            
            # Use messaging service SID if available, otherwise use from_number
            if self.messaging_service_sid:
                message_obj = self.client.messages.create(
                    body=message,
                    to=formatted_phone,
                    messaging_service_sid=self.messaging_service_sid
                )
            elif self.from_number:
                message_obj = self.client.messages.create(
                    body=message,
                    from_=self.from_number,
                    to=formatted_phone
                )
            else:
                logger.error("❌ Neither TWILIO_MESSAGING_SERVICE_SID nor TWILIO_FROM_NUMBER configured")
                return False
            
            logger.info(f"✅ SMS sent successfully to {formatted_phone} (SID: {message_obj.sid})")
            return True
        
        except Exception as e:
            logger.error(f"❌ SMS error: {str(e)}")
            return False
    
    # ===== TEMPLATE MESSAGES =====
    
    def get_viewing_confirmation_message(self, tenant_name: str, property_title: str, 
                                         date_str: str, time_slot: str) -> str:
        """Template: Viewing confirmed to tenant"""
        msg = (
            f"Hi {tenant_name},\n"
            f"Your viewing for {property_title} on {date_str} "
            f"at {time_slot} has been CONFIRMED!\n"
            f"See you soon! - NuloAfrica"
        )
        return msg[:320]
    
    def get_landlord_notification_message(self, landlord_name: str, property_title: str,
                                          tenant_name: str, date_str: str, 
                                          time_slot: str) -> str:
        """Template: Viewing scheduled notification to landlord"""
        msg = (
            f"Hi {landlord_name},\n"
            f"Viewing for {property_title} scheduled\n"
            f"Tenant: {tenant_name}\n"
            f"Date: {date_str}\n"
            f"Time: {time_slot}\n"
            f"Be available! - Nulo"
        )
        return msg[:320]
    
    def get_reminder_message(self, tenant_name: str, property_title: str, 
                             hours_before: int) -> str:
        """Template: Viewing reminder"""
        if hours_before == 24:
            msg = (
                f"Hi {tenant_name},\n"
                f"Reminder: Your viewing for {property_title} "
                f"is TOMORROW! Be on time. - NuloAfrica"
            )
        elif hours_before == 1:
            msg = (
                f"Hi {tenant_name},\n"
                f"Your viewing for {property_title} "
                f"starts in 1 HOUR! Head over now! - Nulo"
            )
        else:
            msg = f"Reminder: Your viewing for {property_title} is coming up!"
        
        return msg[:320]
    
    def get_interest_notification_message(self, landlord_name: str, tenant_name: str,
                                          property_title: str) -> str:
        """Template: Tenant interested notification to landlord"""
        msg = (
            f"Hi {landlord_name},\n"
            f"Good news! {tenant_name} is interested in {property_title}\n"
            f"Check your dashboard! - Nulo"
        )
        return msg[:320]


# Create singleton instance
sms_service = SMSService()
