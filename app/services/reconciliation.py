"""
ReconciliationEngine - Reconcile payments against expected amounts with multi-frequency support
Purpose: Match received payments with expected amounts, handle underpayment/overpayment/duplicates
Reference: MASTER_PRD_NOMBA_INTEGRATION.md Section 6.3

⚠️  IMPLEMENTATION STATUS: ACTIVE — DEFERRED START
─────────────────────────────────────────────────
Status:        Active development, NOT YET INTEGRATED into main routes
Target Start:  June 24, 2026
Prerequisites:
  1. `nomba_client.py` webhook receiver ready
  2. `payment_scheduler.py` schedules stored in DB
  3. Cron job / scheduler to run periodic reconciliation
Do NOT delete — needed for upcoming hackathon integration.
"""

from typing import Dict, Any, Optional
from datetime import datetime, timedelta


class ReconciliationEngine:
    """
    Reconcile payments against expected amounts with support for multiple frequencies
    and grace periods based on Nigerian market norms.
    """
    
    # Tolerance for payment matching (±2%)
    TOLERANCE_PERCENT = 2.0
    
    # Grace periods by frequency (days)
    GRACE_DAYS = {
        'ANNUAL': 7,           # 7 days grace for annual (traditional landlords)
        'SEMI_ANNUAL': 5,      # 5 days grace for bi-annual
        'QUARTERLY': 3,        # 3 days grace for quarterly
        'MONTHLY': 1           # 1 day grace for monthly (modern tenants)
    }
    
    @staticmethod
    def reconcile(
        agreement_id: str,
        expected_amount: int,
        received_amount: int,
        payment_frequency: str,
        next_due_date: datetime,
        current_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Reconcile a payment against expected amount
        
        Args:
            agreement_id: Agreement UUID
            expected_amount: Expected payment amount in kobo
            received_amount: Actual received amount in kobo
            payment_frequency: 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY', 'MONTHLY'
            next_due_date: When payment was due (datetime or date object)
            current_date: Current date (defaults to now)
        
        Returns:
            {
                "agreement_id": "uuid",
                "reconciliation_status": "FULL_PAYMENT|PARTIAL_PAYMENT|OVERPAYMENT|UNDERPAYMENT|PENDING",
                "variance": -50000,  # negative = under, positive = over
                "variance_percent": -3.33,
                "grace_status": "EARLY|WITHIN_GRACE|AFTER_GRACE",
                "matched": true,
                "notes": "Payment within tolerance",
                "grace_days": 7
            }
        
        Raises:
            ValueError: If frequency is invalid or amounts are negative
        """
        
        # Validate inputs
        if payment_frequency not in ReconciliationEngine.GRACE_DAYS:
            raise ValueError(
                f"Invalid frequency: {payment_frequency}. "
                f"Must be one of {list(ReconciliationEngine.GRACE_DAYS.keys())}"
            )
        
        if expected_amount < 0 or received_amount < 0:
            raise ValueError("Amounts cannot be negative")
        
        # Use current date if not provided
        if current_date is None:
            current_date = datetime.utcnow()
        
        # Normalize dates to just the date part for comparison
        if hasattr(next_due_date, 'date'):
            next_due_date = next_due_date.date()
        if hasattr(current_date, 'date'):
            current_date_obj = current_date.date()
        else:
            current_date_obj = current_date
        
        # Get grace period for this frequency
        grace_days = ReconciliationEngine.GRACE_DAYS.get(payment_frequency, 1)
        grace_until_date = next_due_date + timedelta(days=grace_days)
        
        # Determine grace status
        if current_date_obj <= next_due_date:
            grace_status = "EARLY"
        elif current_date_obj <= grace_until_date:
            grace_status = "WITHIN_GRACE"
        else:
            grace_status = "AFTER_GRACE"
        
        # Calculate variance
        variance = received_amount - expected_amount
        variance_percent = (
            (variance / expected_amount * 100) if expected_amount > 0 else 0
        )
        
        # Determine reconciliation status and matched flag
        if received_amount == 0:
            status = "PENDING"
            matched = False
            notes = "No payment received yet"
        
        elif abs(variance_percent) <= ReconciliationEngine.TOLERANCE_PERCENT:
            # Payment within tolerance range (±2%)
            status = "FULL_PAYMENT"
            matched = True
            notes = (
                f"Payment matched within {ReconciliationEngine.TOLERANCE_PERCENT}% tolerance. "
                f"Expected NGN {expected_amount:,}, received NGN {received_amount:,}"
            )
        
        elif variance < 0 and abs(variance_percent) > ReconciliationEngine.TOLERANCE_PERCENT:
            # Underpayment exceeds tolerance
            status = "UNDERPAYMENT"
            matched = False
            shortfall = abs(variance)
            notes = (
                f"Underpayment of NGN {shortfall:,}. "
                f"Expected NGN {expected_amount:,}, received NGN {received_amount:,}. "
                f"Shortfall: {abs(variance_percent):.2f}%"
            )
        
        elif variance > 0:
            # Overpayment (possible prepayment for next period or goodwill)
            status = "OVERPAYMENT"
            matched = True  # Accept but flag for follow-up
            excess = variance
            notes = (
                f"Overpayment of NGN {excess:,}. "
                f"May be prepayment for next period or goodwill payment. "
                f"Excess: {variance_percent:.2f}%"
            )
        
        else:
            # Edge case: unusual payment pattern
            status = "MISDIRECTED"
            matched = False
            notes = "Payment amount is unusually different from expected"
        
        return {
            "agreement_id": agreement_id,
            "reconciliation_status": status,
            "variance": variance,
            "variance_percent": round(variance_percent, 2),
            "grace_status": grace_status,
            "matched": matched,
            "notes": notes,
            "grace_days": grace_days,
            "expected_amount": expected_amount,
            "received_amount": received_amount,
            "payment_frequency": payment_frequency,
            "due_date": next_due_date.isoformat(),
            "grace_until": grace_until_date.isoformat(),
            "reconciled_at": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def is_duplicate(
        transfer_id: str,
        processed_transfers: list
    ) -> bool:
        """
        Check if a transfer has already been processed (detect duplicates from webhooks)
        
        Args:
            transfer_id: Nomba transfer ID
            processed_transfers: List of already-processed transfer IDs
        
        Returns:
            True if duplicate detected
        """
        return transfer_id in processed_transfers
    
    @staticmethod
    def detect_misdirected_payment(
        received_amount: int,
        expected_amount: int
    ) -> bool:
        """
        Detect if payment looks misdirected (e.g., transferred to wrong account)
        Uses heuristic: payment is >20% different from expected without matching a known pattern
        
        Args:
            received_amount: Actual received amount
            expected_amount: Expected payment amount
        
        Returns:
            True if payment looks misdirected
        """
        if expected_amount == 0:
            return False
        
        variance_percent = abs((received_amount - expected_amount) / expected_amount * 100)
        
        # If variance >20% and doesn't match common patterns, flag as misdirected
        if variance_percent > 20:
            # Check for common patterns (half payment, double payment, etc.)
            common_ratios = [0.5, 1.0, 2.0, 0.33, 0.67]  # 1/3, 2/3, etc.
            ratio = received_amount / expected_amount
            
            for pattern in common_ratios:
                if abs(ratio - pattern) < 0.05:  # Within 5% of pattern
                    return False  # Matches a known pattern
            
            return True  # Doesn't match a pattern, flag as misdirected
        
        return False
    
    @staticmethod
    def calculate_overpayment_carryforward(
        received_amount: int,
        expected_amount: int,
        next_payment_amount: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Handle overpayment carryforward to next payment period
        
        Args:
            received_amount: Actual received amount
            expected_amount: Expected payment amount
            next_payment_amount: Expected amount for next period (optional)
        
        Returns:
            {
                "current_status": "FULL_PAYMENT",
                "overpayment": 50000,
                "next_payment_expected": 150000,
                "next_payment_with_carryforward": 100000,
                "note": "NGN 50,000 credited to next period"
            }
        """
        
        if received_amount <= expected_amount:
            return {
                "current_status": "FULL_PAYMENT",
                "overpayment": 0,
                "note": "No overpayment"
            }
        
        overpayment = received_amount - expected_amount
        
        result = {
            "current_status": "OVERPAYMENT",
            "current_payment_expected": expected_amount,
            "current_payment_received": received_amount,
            "overpayment": overpayment,
            "note": f"NGN {overpayment:,} credited to next period"
        }
        
        if next_payment_amount:
            next_with_carryforward = max(0, next_payment_amount - overpayment)
            result["next_payment_expected"] = next_payment_amount
            result["next_payment_adjusted"] = next_with_carryforward
        
        return result
