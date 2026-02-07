from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from typing import Dict
from datetime import datetime, timedelta
import random
import logging

from app.database import supabase_admin

router = APIRouter()
logger = logging.getLogger(__name__)

# Simple in-memory OTP store for simulation: { phone: {code, expires_at} }
OTP_STORE: Dict[str, Dict] = {}


class PhoneSendRequest(BaseModel):
    phone: str


class PhoneVerifyRequest(BaseModel):
    phone: str
    code: str


@router.post('/verifications/phone/send')
async def send_phone_otp(req: PhoneSendRequest):
    phone = req.phone.strip()
    if not phone:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Phone is required')

    # Generate 6-digit OTP
    code = f"{random.randint(0, 999999):06d}"
    expires_at = datetime.utcnow() + timedelta(minutes=5)

    OTP_STORE[phone] = {"code": code, "expires_at": expires_at}

    # Log OTP for dev (in production you'd send via SMS provider)
    logger.info(f"[OTP SEND] phone={phone} code={code} expires_at={expires_at.isoformat()}")

    return {"success": True, "message": "OTP sent (simulated)", "expires_at": expires_at.isoformat()}


@router.post('/verifications/phone/verify')
async def verify_phone_otp(req: PhoneVerifyRequest):
    phone = req.phone.strip()
    code = req.code.strip()

    record = OTP_STORE.get(phone)
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='No OTP requested for this phone')

    if datetime.utcnow() > record['expires_at']:
        del OTP_STORE[phone]
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='OTP expired')

    if record['code'] != code:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail='Invalid OTP')

    # Mark verified in DB if possible (best-effort)
    try:
        supabase_admin.table('users').update({ 'phone_verified': True }).eq('phone_number', phone).execute()
    except Exception as e:
        logger.warning(f"Failed to update phone_verified on users table: {e}")

    # Remove OTP
    del OTP_STORE[phone]

    return {"success": True, "message": "Phone verified"}
