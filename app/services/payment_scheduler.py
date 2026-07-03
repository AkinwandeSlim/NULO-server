"""
PaymentScheduler - Generate payment schedules for different frequencies
Purpose: Create payment calendars for ANNUAL, SEMI_ANNUAL, QUARTERLY, MONTHLY frequencies
Reference: MASTER_PRD_NOMBA_INTEGRATION.md Section 6.2

⚠️  IMPLEMENTATION STATUS: ACTIVE — DEFERRED START
─────────────────────────────────────────────────
Status:        Active development, NOT YET INTEGRATED into main routes
Target Start:  June 24, 2026
Prerequisites:
  1. `nomba_client.py` integration completed first
  2. Wire scheduler into agreement creation flow
  3. Connect to reconciliation engine for payment matching
Do NOT delete — needed for upcoming hackathon integration.
"""

from datetime import datetime, timedelta
from typing import List, Dict, Any
from dateutil.relativedelta import relativedelta


class PaymentScheduler:
    """Generate payment schedules for different rental payment frequencies"""
    
    # Grace periods in days for each frequency (Nigerian market standard)
    GRACE_DAYS = {
        'ANNUAL': 7,           # 7 days grace for annual payments (traditional landlords)
        'SEMI_ANNUAL': 5,      # 5 days grace for bi-annual payments
        'QUARTERLY': 3,        # 3 days grace for quarterly payments
        'MONTHLY': 1           # 1 day grace for monthly payments (modern tenants)
    }
    
    # Payment amount multipliers (how many months of rent per payment)
    FREQUENCY_MULTIPLIERS = {
        'ANNUAL': 12,
        'SEMI_ANNUAL': 6,
        'QUARTERLY': 3,
        'MONTHLY': 1
    }
    
    @staticmethod
    def calculate_expected_amount(
        monthly_rent: int,
        frequency: str
    ) -> int:
        """
        Calculate expected payment amount for a frequency
        
        Args:
            monthly_rent: Monthly rent in kobo
            frequency: 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY', 'MONTHLY'
        
        Returns:
            Expected payment amount in kobo
        """
        multiplier = PaymentScheduler.FREQUENCY_MULTIPLIERS.get(frequency, 1)
        return monthly_rent * multiplier
    
    @staticmethod
    def get_grace_days(frequency: str) -> int:
        """
        Get grace period in days for a frequency
        
        Args:
            frequency: Payment frequency
        
        Returns:
            Grace days
        """
        return PaymentScheduler.GRACE_DAYS.get(frequency, 1)
    
    @staticmethod
    def generate_schedule(
        lease_start: datetime,
        lease_end: datetime,
        monthly_rent: int,
        frequency: str
    ) -> List[Dict[str, Any]]:
        """
        Generate payment schedule for an agreement
        
        Args:
            lease_start: Start date of lease
            lease_end: End date of lease
            monthly_rent: Monthly rent amount in kobo
            frequency: 'ANNUAL', 'SEMI_ANNUAL', 'QUARTERLY', 'MONTHLY'
        
        Returns:
            List of payment schedule items:
            [
                {
                    "date": "2026-06-30",
                    "amount": 1800000,
                    "period": "1 of 1",
                    "status": "PENDING",
                    "grace_until": "2026-07-07"
                },
                ...
            ]
        
        Raises:
            ValueError: If frequency is invalid or dates are invalid
        """
        
        if frequency not in PaymentScheduler.FREQUENCY_MULTIPLIERS:
            raise ValueError(f"Invalid frequency: {frequency}. Must be one of {list(PaymentScheduler.FREQUENCY_MULTIPLIERS.keys())}")
        
        if lease_start >= lease_end:
            raise ValueError("lease_start must be before lease_end")
        
        schedule = []
        current_date = lease_start
        payment_num = 0
        
        # Calculate expected amount per payment
        multiplier = PaymentScheduler.FREQUENCY_MULTIPLIERS.get(frequency, 1)
        expected_amount = monthly_rent * multiplier
        
        # Get grace period
        grace_days = PaymentScheduler.GRACE_DAYS.get(frequency, 1)
        
        # Generate payment schedule based on frequency
        if frequency == 'ANNUAL':
            # One payment per year
            while current_date <= lease_end:
                payment_num += 1
                grace_until = current_date + timedelta(days=grace_days)
                schedule.append({
                    "date": current_date.isoformat()[:10],  # YYYY-MM-DD
                    "amount": expected_amount,
                    "period": f"1 of 1",
                    "status": "PENDING",
                    "grace_until": grace_until.isoformat()[:10],
                    "frequency": "ANNUAL"
                })
                current_date = current_date + relativedelta(years=1)
        
        elif frequency == 'SEMI_ANNUAL':
            # Two payments per year (every 6 months)
            num_payments = PaymentScheduler._calculate_num_payments(lease_start, lease_end, 'SEMI_ANNUAL')
            while current_date <= lease_end:
                for i in range(2):
                    payment_num += 1
                    grace_until = current_date + timedelta(days=grace_days)
                    schedule.append({
                        "date": current_date.isoformat()[:10],
                        "amount": expected_amount,
                        "period": f"{payment_num} of {num_payments}",
                        "status": "PENDING",
                        "grace_until": grace_until.isoformat()[:10],
                        "frequency": "SEMI_ANNUAL"
                    })
                    current_date = current_date + relativedelta(months=6)
                    if current_date > lease_end:
                        break
                break
        
        elif frequency == 'QUARTERLY':
            # Four payments per year (every 3 months)
            num_payments = PaymentScheduler._calculate_num_payments(lease_start, lease_end, 'QUARTERLY')
            while current_date <= lease_end:
                for i in range(4):
                    payment_num += 1
                    grace_until = current_date + timedelta(days=grace_days)
                    schedule.append({
                        "date": current_date.isoformat()[:10],
                        "amount": expected_amount,
                        "period": f"{payment_num} of {num_payments}",
                        "status": "PENDING",
                        "grace_until": grace_until.isoformat()[:10],
                        "frequency": "QUARTERLY"
                    })
                    current_date = current_date + relativedelta(months=3)
                    if current_date > lease_end:
                        break
                break
        
        elif frequency == 'MONTHLY':
            # Monthly payments
            num_payments = PaymentScheduler._calculate_num_payments(lease_start, lease_end, 'MONTHLY')
            while current_date <= lease_end:
                payment_num += 1
                grace_until = current_date + timedelta(days=grace_days)
                schedule.append({
                    "date": current_date.isoformat()[:10],
                    "amount": expected_amount,
                    "period": f"{payment_num} of {num_payments}",
                    "status": "PENDING",
                    "grace_until": grace_until.isoformat()[:10],
                    "frequency": "MONTHLY"
                })
                current_date = current_date + relativedelta(months=1)
        
        return schedule
    
    @staticmethod
    def _calculate_num_payments(
        lease_start: datetime,
        lease_end: datetime,
        frequency: str
    ) -> int:
        """
        Calculate total number of payments for a lease
        
        Args:
            lease_start: Start date
            lease_end: End date
            frequency: Payment frequency
        
        Returns:
            Number of payments
        """
        
        days_diff = (lease_end - lease_start).days
        
        if frequency == 'ANNUAL':
            # At least 1 payment, +1 for each full year
            return max(1, days_diff // 365 + 1)
        
        elif frequency == 'SEMI_ANNUAL':
            # 2 payments per year
            return max(1, (days_diff // 180) + 1)
        
        elif frequency == 'QUARTERLY':
            # 4 payments per year
            return max(1, (days_diff // 90) + 1)
        
        elif frequency == 'MONTHLY':
            # Calculate months between dates
            months = (lease_end.year - lease_start.year) * 12 + (lease_end.month - lease_start.month) + 1
            return max(1, months)
        
        return 1
    
    @staticmethod
    def get_next_payment_date(
        lease_start: datetime,
        frequency: str
    ) -> datetime:
        """
        Get the first payment due date based on lease start and frequency
        
        Args:
            lease_start: Start date of lease
            frequency: Payment frequency
        
        Returns:
            First payment due date
        """
        
        if frequency == 'ANNUAL':
            return lease_start + relativedelta(years=1)
        elif frequency == 'SEMI_ANNUAL':
            return lease_start + relativedelta(months=6)
        elif frequency == 'QUARTERLY':
            return lease_start + relativedelta(months=3)
        else:  # MONTHLY
            return lease_start + relativedelta(months=1)
