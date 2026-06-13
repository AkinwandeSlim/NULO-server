"""
NombaClient - Wrapper for Nomba Virtual Accounts API
Purpose: Create virtual accounts per agreement, verify webhooks, handle transfers
Reference: MASTER_PRD_NOMBA_INTEGRATION.md Section 6.1
"""

import httpx
import os
import hmac
import hashlib
import json
from typing import Dict, Any, Optional
from datetime import datetime


class NombaClient:
    """Client for Nomba Virtual Accounts API integration"""
    
    def __init__(self):
        self.api_key = os.getenv("NOMBA_API_KEY")
        self.secret_key = os.getenv("NOMBA_SECRET_KEY")
        self.base_url = os.getenv("NOMBA_API_URL", "https://api.nomba.com/v1")
        self.merchant_id = os.getenv("NOMBA_MERCHANT_ID")
        self.timeout = 30
        
        # Validate required environment variables
        if not all([self.api_key, self.secret_key, self.merchant_id]):
            raise ValueError(
                "Missing required Nomba environment variables: "
                "NOMBA_API_KEY, NOMBA_SECRET_KEY, NOMBA_MERCHANT_ID"
            )
    
    async def create_virtual_account(
        self,
        agreement_id: str,
        tenant_name: str,
        tenant_email: str,
        expected_amount: int
    ) -> Dict[str, Any]:
        """
        Create a virtual account for an agreement
        
        Args:
            agreement_id: UUID of the agreement
            tenant_name: Tenant full name
            tenant_email: Tenant email address
            expected_amount: Expected first payment amount in kobo
        
        Returns:
            {
                "success": True,
                "account_number": "1234567890",
                "account_name": "NULOAFRICA-{agreement_id}",
                "nomba_account_id": "acc_xxx"
            }
        
        Raises:
            Exception: If API call fails
        """
        
        account_name = f"NULOAFRICA-{agreement_id}"
        
        payload = {
            "account_name": account_name,
            "account_type": "SETTLEMENT",
            "customer_name": tenant_name,
            "customer_email": tenant_email,
            "merchant_id": self.merchant_id,
            "metadata": {
                "agreement_id": agreement_id,
                "tenant_name": tenant_name,
                "expected_amount": expected_amount,
                "created_at": datetime.utcnow().isoformat()
            }
        }
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/virtual-accounts",
                    json=payload,
                    headers=self._get_headers()
                )
            
            if response.status_code == 201:
                data = response.json()
                return {
                    "success": True,
                    "account_number": data.get("account_number"),
                    "account_name": data.get("account_name", account_name),
                    "nomba_account_id": data.get("id")
                }
            else:
                raise Exception(
                    f"Nomba API error {response.status_code}: {response.text}"
                )
        
        except httpx.RequestError as e:
            raise Exception(f"Nomba API request failed: {str(e)}")
        except Exception as e:
            raise Exception(f"Failed to create virtual account: {str(e)}")
    
    def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str
    ) -> bool:
        """
        Verify Nomba webhook signature using HMAC-SHA256
        
        Args:
            payload: Raw webhook payload bytes
            signature: Signature from X-Signature header
        
        Returns:
            True if signature is valid, False otherwise
        """
        
        try:
            expected_signature = hmac.new(
                self.secret_key.encode(),
                payload,
                hashlib.sha256
            ).hexdigest()
            
            # Use constant-time comparison to prevent timing attacks
            return hmac.compare_digest(expected_signature, signature)
        
        except Exception as e:
            print(f"Error verifying webhook signature: {str(e)}")
            return False
    
    async def get_virtual_account_details(
        self,
        account_id: str
    ) -> Dict[str, Any]:
        """
        Fetch details of a virtual account from Nomba
        
        Args:
            account_id: Nomba account ID
        
        Returns:
            Account details from Nomba API
        """
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    f"{self.base_url}/virtual-accounts/{account_id}",
                    headers=self._get_headers()
                )
            
            if response.status_code == 200:
                return response.json()
            else:
                raise Exception(
                    f"Nomba API error {response.status_code}: {response.text}"
                )
        
        except Exception as e:
            raise Exception(f"Failed to get account details: {str(e)}")
    
    async def deactivate_virtual_account(
        self,
        account_id: str
    ) -> bool:
        """
        Deactivate a virtual account (useful when agreement terminates)
        
        Args:
            account_id: Nomba account ID
        
        Returns:
            True if successful
        """
        
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    f"{self.base_url}/virtual-accounts/{account_id}/deactivate",
                    headers=self._get_headers()
                )
            
            return response.status_code in [200, 204]
        
        except Exception as e:
            print(f"Warning: Failed to deactivate account: {str(e)}")
            return False
    
    def _get_headers(self) -> Dict[str, str]:
        """
        Get standard headers for Nomba API requests
        """
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "NuloAfrica/1.0"
        }
    
    @staticmethod
    def parse_webhook_payload(payload: str) -> Dict[str, Any]:
        """
        Parse and validate webhook payload JSON
        
        Args:
            payload: Raw JSON string from webhook
        
        Returns:
            Parsed JSON object
        
        Raises:
            ValueError: If JSON is invalid
        """
        try:
            return json.loads(payload)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON payload: {str(e)}")


# Global instance for use across the application
nomba_client: Optional[NombaClient] = None


def get_nomba_client() -> NombaClient:
    """
    Get or create Nomba client instance (singleton pattern)
    """
    global nomba_client
    if nomba_client is None:
        nomba_client = NombaClient()
    return nomba_client
