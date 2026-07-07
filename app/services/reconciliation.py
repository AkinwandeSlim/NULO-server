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
    
    # Number of payment periods per year by frequency
    PAYMENT_PERIODS_PER_YEAR = {
        'ANNUAL': 1,
        'SEMI_ANNUAL': 2,
        'QUARTERLY': 4,
        'MONTHLY': 12
    }
    
    @staticmethod
    def calculate_per_payment_amount(
        total_rent: int,
        payment_frequency: str,
        lease_duration_months: int
    ) -> int:
        """
        Calculate the amount due per payment period based on total rent and frequency.
        
        Args:
            total_rent: Total rent for the entire lease (in kobo)
            payment_frequency: 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY', 'MONTHLY'
            lease_duration_months: Total lease duration in months
        
        Returns:
            Amount due per payment period (in kobo)
            
        Example:
            total_rent = 1,200,000 (₦1.2M)
            payment_frequency = 'MONTHLY'
            lease_duration_months = 12
            Returns: 100,000 (₦100K per month)
        """
        if payment_frequency not in ReconciliationEngine.PAYMENT_PERIODS_PER_YEAR:
            raise ValueError(
                f"Invalid frequency: {payment_frequency}. "
                f"Must be one of {list(ReconciliationEngine.PAYMENT_PERIODS_PER_YEAR.keys())}"
            )
        
        periods_per_year = ReconciliationEngine.PAYMENT_PERIODS_PER_YEAR[payment_frequency]
        total_periods = (lease_duration_months * periods_per_year) // 12
        
        if total_periods == 0:
            total_periods = 1  # Fallback for edge cases
        
        return total_rent // total_periods
    
    @staticmethod
    def calculate_cumulative_balance(
        total_rent: int,
        total_paid: int
    ) -> Dict[str, Any]:
        """
        Calculate cumulative payment status and outstanding balance.
        
        Args:
            total_rent: Total rent for the entire lease (in kobo)
            total_paid: Total amount paid so far (in kobo)
        
        Returns:
            {
                "total_rent": 1200000,
                "total_paid": 100000,
                "outstanding_balance": 1100000,
                "payment_percentage": 8.33,
                "is_fully_paid": false
            }
        """
        outstanding_balance = total_rent - total_paid
        payment_percentage = (total_paid / total_rent * 100) if total_rent > 0 else 0
        is_fully_paid = outstanding_balance <= 0
        
        return {
            "total_rent": total_rent,
            "total_paid": total_paid,
            "outstanding_balance": max(0, outstanding_balance),
            "payment_percentage": round(payment_percentage, 2),
            "is_fully_paid": is_fully_paid
        }
    
    @staticmethod
    def reconcile(
        agreement_id: str,
        total_rent: int,
        received_amount: int,
        payment_frequency: str,
        lease_duration_months: int,
        next_due_date: datetime,
        cumulative_paid: int = 0,
        current_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Reconcile a payment against expected per-payment amount (NOT total rent).
        
        Args:
            agreement_id: Agreement UUID
            total_rent: Total rent for entire lease (in kobo)
            received_amount: Actual received amount in kobo
            payment_frequency: 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY', 'MONTHLY'
            lease_duration_months: Total lease duration in months
            next_due_date: When payment was due (datetime or date object)
            cumulative_paid: Total amount paid so far (in kobo, for tracking balance)
            current_date: Current date (defaults to now)
        
        Returns:
            {
                "agreement_id": "uuid",
                "reconciliation_status": "FULL_PAYMENT|PARTIAL_PAYMENT|OVERPAYMENT|UNDERPAYMENT|PENDING",
                "per_payment_amount": 100000,  # Amount due per period
                "variance": -50000,  # negative = under, positive = over
                "variance_percent": -3.33,
                "grace_status": "EARLY|WITHIN_GRACE|AFTER_GRACE",
                "matched": true,
                "notes": "Payment within tolerance",
                "grace_days": 7,
                "cumulative_balance": {
                    "total_rent": 1200000,
                    "total_paid": 100000,
                    "outstanding_balance": 1100000,
                    "payment_percentage": 8.33
                }
            }
        
        Raises:
            ValueError: If frequency is invalid or amounts are negative
        
        Example:
            total_rent = 1,200,000 (₦1.2M annual)
            payment_frequency = 'MONTHLY'
            lease_duration_months = 12
            per_payment_amount = 100,000 (₦100K per month)
            received_amount = 100,000
            Result: FULL_PAYMENT (matched against per-payment, not total)
        """
        
        # Validate inputs
        if payment_frequency not in ReconciliationEngine.GRACE_DAYS:
            raise ValueError(
                f"Invalid frequency: {payment_frequency}. "
                f"Must be one of {list(ReconciliationEngine.GRACE_DAYS.keys())}"
            )
        
        if total_rent < 0 or received_amount < 0:
            raise ValueError("Amounts cannot be negative")
        
        # Calculate per-payment amount (THIS IS THE KEY FIX)
        per_payment_amount = ReconciliationEngine.calculate_per_payment_amount(
            total_rent, payment_frequency, lease_duration_months
        )
        
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
        
        # Calculate variance against PER-PAYMENT amount (not total rent)
        variance = received_amount - per_payment_amount
        variance_percent = (
            (variance / per_payment_amount * 100) if per_payment_amount > 0 else 0
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
                f"Expected NGN {per_payment_amount:,}, received NGN {received_amount:,}"
            )
        
        elif variance < 0 and abs(variance_percent) > ReconciliationEngine.TOLERANCE_PERCENT:
            # Underpayment exceeds tolerance
            status = "UNDERPAYMENT"
            matched = False
            shortfall = abs(variance)
            notes = (
                f"Underpayment of NGN {shortfall:,}. "
                f"Expected NGN {per_payment_amount:,}, received NGN {received_amount:,}. "
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
        
        # Calculate cumulative balance
        new_cumulative_paid = cumulative_paid + received_amount
        cumulative_balance = ReconciliationEngine.calculate_cumulative_balance(
            total_rent, new_cumulative_paid
        )
        
        return {
            "agreement_id": agreement_id,
            "reconciliation_status": status,
            "per_payment_amount": per_payment_amount,
            "total_rent": total_rent,
            "variance": variance,
            "variance_percent": round(variance_percent, 2),
            "grace_status": grace_status,
            "matched": matched,
            "notes": notes,
            "grace_days": grace_days,
            "expected_amount": per_payment_amount,  # Changed to per-payment amount
            "received_amount": received_amount,
            "payment_frequency": payment_frequency,
            "lease_duration_months": lease_duration_months,
            "due_date": next_due_date.isoformat(),
            "grace_until": grace_until_date.isoformat(),
            "reconciled_at": datetime.utcnow().isoformat(),
            "cumulative_balance": cumulative_balance
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
