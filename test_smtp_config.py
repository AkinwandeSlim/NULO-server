#!/usr/bin/env python3
"""
Test script to verify SMTP configuration
"""
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.config import settings

print("=== SMTP Configuration Test ===")
print(f"SMTP_HOST: {settings.SMTP_HOST}")
print(f"SMTP_PORT: {settings.SMTP_PORT}")
print(f"SMTP_USER: {settings.SMTP_USER}")
print(f"SMTP_PASSWORD: {'*' * len(settings.SMTP_PASSWORD) if settings.SMTP_PASSWORD else 'None'}")

# Test SMTP connection
import smtplib
from email.mime.text import MIMEText

print("\n=== Testing SMTP Connection ===")
try:
    server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
    server.starttls()
    print("✅ SMTP connection established")
    
    server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
    print("✅ SMTP authentication successful")
    
    # Test sending a test email
    msg = MIMEText("This is a test email from NuloAfrica SMTP configuration.")
    msg['Subject'] = 'NuloAfrica SMTP Test'
    msg['From'] = settings.SMTP_USER
    msg['To'] = settings.SMTP_USER
    
    server.send_message(msg)
    print("✅ Test email sent successfully")
    
    server.quit()
    print("✅ SMTP connection closed properly")
    
except Exception as e:
    print(f"❌ SMTP Error: {type(e).__name__}: {e}")
    
print("\n=== Test Complete ===")
