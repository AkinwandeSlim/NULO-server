"""
Admin Transaction Monitoring Endpoint
Allows admin to monitor Nomba transactions for reconciliation and debugging.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from app.middleware.auth import get_current_admin
from app.services.nomba_client import nomba_client
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
import logging

router = APIRouter(prefix="/admin/transactions", tags=["admin-transactions"])
logger = logging.getLogger(__name__)


@router.get("/account")
async def get_account_transactions(
    date_from: Optional[str] = Query(None, description="ISO datetime string (e.g., 2023-01-01T00:00:00)"),
    date_to: Optional[str] = Query(None, description="ISO datetime string (e.g., 2025-01-01T00:00:00)"),
    limit: int = Query(50, ge=1, le=100, description="Number of records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user=Depends(get_current_admin),
):
    """
    Fetch all transactions on the NuloAfrica sub-account (business account).
    
    This endpoint allows admins to monitor all transactions flowing through
    the NuloAfrica Nomba sub-account for reconciliation purposes.
    
    The sub-account (id: 282e5b9b-...) is the NuloAfrica business wallet that:
    - Holds the registered webhook URL
    - Holds spendable balance for disbursements
    - All VAs are scoped under it
    
    PER NOMBA DOCS:
    - Endpoint: GET /v1/transactions/accounts/{subAccountId}
    - Returns paginated list with amount, status, type, reference, etc.
    - Supports date range filtering and pagination
    """
    try:
        logger.info(f"📊 [ADMIN_TX] Fetching account transactions | admin={current_user['id']} | dateFrom={date_from} | dateTo={date_to}")
        
        # Default to last 30 days if no date range provided
        if not date_from:
            date_from = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00")
        if not date_to:
            date_to = datetime.now().strftime("%Y-%m-%dT23:59:59")
        
        data = await nomba_client.fetch_account_transactions(
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            page=page,
        )
        
        logger.info(f"✅ [ADMIN_TX] Fetched {len(data.get('content', []))} transactions")
        
        return {
            "success": True,
            "data": data,
            "message": "Transactions fetched successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ [ADMIN_TX] Failed to fetch account transactions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch transactions: {str(e)}"
        )


@router.get("/virtual/{virtual_account}")
async def get_virtual_account_transactions(
    virtual_account: str,
    date_from: Optional[str] = Query(None, description="ISO date string (e.g., 2025-06-24)"),
    date_to: Optional[str] = Query(None, description="ISO date string (e.g., 2025-06-25)"),
    limit: int = Query(50, ge=1, le=100, description="Number of records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user=Depends(get_current_admin),
):
    """
    Fetch transactions for a specific virtual account (NUBAN).
    
    This endpoint allows admins to monitor transactions for a specific
    tenant's NUBAN for debugging and reconciliation.
    
    PER NOMBA DOCS:
    - Endpoint: GET /v1/transactions/virtual
    - Requires virtual_account parameter (NUBAN number)
    - Returns paginated list of transactions for that VA
    """
    try:
        logger.info(f"📊 [ADMIN_TX] Fetching VA transactions | virtual_account={virtual_account} | admin={current_user['id']}")
        
        data = await nomba_client.fetch_virtual_account_transactions(
            virtual_account=virtual_account,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
            page=page,
        )
        
        logger.info(f"✅ [ADMIN_TX] Fetched {len(data.get('content', []))} transactions for VA {virtual_account}")
        
        return {
            "success": True,
            "data": data,
            "message": "Virtual account transactions fetched successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ [ADMIN_TX] Failed to fetch VA transactions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch virtual account transactions: {str(e)}"
        )


@router.get("/bank")
async def get_bank_transactions(
    limit: int = Query(50, ge=1, le=100, description="Number of records per page"),
    page: int = Query(1, ge=1, description="Page number"),
    current_user=Depends(get_current_admin),
):
    """
    Fetch credit/debit bank transactions on the NuloAfrica sub-account.
    
    This endpoint allows admins to monitor bank transfers (disbursements)
    for reconciliation and debugging.
    
    The sub-account (id: 282e5b9b-...) is the NuloAfrica business wallet that:
    - Holds the registered webhook URL
    - Holds spendable balance for disbursements
    - All VAs are scoped under it
    
    PER NOMBA DOCS:
    - Endpoint: GET /v1/transactions/bank/{subAccountId}
    - Returns paginated list of bank transactions
    """
    try:
        logger.info(f"📊 [ADMIN_TX] Fetching bank transactions | admin={current_user['id']}")
        
        data = await nomba_client.fetch_bank_transactions(
            limit=limit,
            page=page,
        )
        
        logger.info(f"✅ [ADMIN_TX] Fetched {len(data.get('content', []))} bank transactions")
        
        return {
            "success": True,
            "data": data,
            "message": "Bank transactions fetched successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ [ADMIN_TX] Failed to fetch bank transactions: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch bank transactions: {str(e)}"
        )


@router.get("/sub-account/details")
async def get_sub_account_details(
    sub_account_id: Optional[str] = Query(None, description="Sub account ID (UUID) - defaults to configured sub-account"),
    account_ref: Optional[str] = Query(None, description="Account reference - alternative to sub_account_id"),
    current_user=Depends(get_current_admin),
):
    """
    Fetch details of the NuloAfrica sub-account.
    
    This endpoint allows admins to view the sub-account details including
    status, type, account name, and linked bank accounts.
    
    PER NOMBA DOCS:
    - Endpoint: GET /v1/accounts/sub-account-details
    - Query params: subAccountId OR accountRef (one is required)
    - Returns: account details, status, type, linked banks
    """
    try:
        logger.info(f"📊 [ADMIN_TX] Fetching sub-account details | admin={current_user['id']} | sub_account_id={sub_account_id}")
        
        # Use configured sub-account ID if not provided
        if not sub_account_id and not account_ref:
            sub_account_id = nomba_client.sub_account_id
        
        data = await nomba_client.fetch_sub_account_details(
            sub_account_id=sub_account_id,
            account_ref=account_ref,
        )
        
        logger.info(f"✅ [ADMIN_TX] Fetched sub-account details | accountId={data.get('accountId')}")
        
        return {
            "success": True,
            "data": data,
            "message": "Sub-account details fetched successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ [ADMIN_TX] Failed to fetch sub-account details: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch sub-account details: {str(e)}"
        )


@router.get("/sub-account/balance")
async def get_sub_account_balance(
    sub_account_id: Optional[str] = Query(None, description="Sub account ID (UUID) - defaults to configured sub-account"),
    current_user=Depends(get_current_admin),
):
    """
    Fetch the balance of the NuloAfrica sub-account.
    
    This endpoint allows admins to view the current balance of the
    NuloAfrica business account for reconciliation purposes.
    
    PER NOMBA DOCS:
    - Endpoint: GET /v1/accounts/{subAccountId}/balance
    - Returns: amount, currency, timeCreated
    """
    try:
        logger.info(f"📊 [ADMIN_TX] Fetching sub-account balance | admin={current_user['id']} | sub_account_id={sub_account_id}")
        
        # Use configured sub-account ID if not provided
        if not sub_account_id:
            sub_account_id = nomba_client.sub_account_id
        
        data = await nomba_client.fetch_sub_account_balance(sub_account_id=sub_account_id)
        
        logger.info(f"✅ [ADMIN_TX] Fetched sub-account balance | amount={data.get('amount')} {data.get('currency')}")
        
        return {
            "success": True,
            "data": data,
            "message": "Sub-account balance fetched successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ [ADMIN_TX] Failed to fetch sub-account balance: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to fetch sub-account balance: {str(e)}"
        )
