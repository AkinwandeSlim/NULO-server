# NuloAfrica Nomba helper functions
# Rule 17: ASCII only -- no Unicode in .py files

from datetime import date, timedelta
from dateutil.relativedelta import relativedelta

GRACE_PERIODS = {
    "ANNUAL": 7,
    "SEMI_ANNUAL": 5,
    "QUARTERLY": 3,
    "MONTHLY": 1,
}

FREQUENCY_MULTIPLIERS = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMI_ANNUAL": 6,
    "ANNUAL": 12,
}

TOLERANCE_PCT = 0.02  # +/- 2% variance treated as full payment


def calculate_expected_amount(monthly_rent: float, frequency: str) -> float:
    """Return the lump-sum amount expected per payment cycle."""
    multiplier = FREQUENCY_MULTIPLIERS.get(frequency, 1)
    return round(monthly_rent * multiplier, 2)


def calculate_next_due_date(lease_start_date: date, frequency: str) -> date:
    """Return the first payment due date from lease start."""
    deltas = {
        "MONTHLY": relativedelta(months=1),
        "QUARTERLY": relativedelta(months=3),
        "SEMI_ANNUAL": relativedelta(months=6),
        "ANNUAL": relativedelta(years=1),
    }
    return lease_start_date + deltas.get(frequency, relativedelta(months=1))


def is_within_grace_period(due_date: date, frequency: str) -> bool:
    """True if today is still within grace period for this frequency."""
    grace_days = GRACE_PERIODS.get(frequency, 1)
    return date.today() <= due_date + timedelta(days=grace_days)


def classify_payment(received: float, expected: float) -> str:
    """
    Return reconciliation status.
    FULL_PAYMENT: within +/-2% tolerance
    UNDERPAYMENT: below tolerance
    OVERPAYMENT: above tolerance
    """
    if expected <= 0:
        return "PENDING"
    variance = (received - expected) / expected
    if abs(variance) <= TOLERANCE_PCT:
        return "FULL_PAYMENT"
    elif variance < 0:
        return "UNDERPAYMENT"
    else:
        return "OVERPAYMENT"


def calculate_landlord_payout(received: float, platform_fee: float) -> float:
    """
    Phase 3 (disbursement) helper.

    Split calculation: platform_fee stays in the parent account as revenue,
    landlord_share = received - platform_fee is paid out via /v2/transfers/bank.
    Round to 2dp because this feeds directly into Nomba's decimal-Naira
    amount field. Never return a negative payout.

    PRD Part 5 (Nomba Integration PRD v2).
    """
    return round(max(received - platform_fee, 0), 2)


def build_merchant_tx_ref(transfer_id: str, retry_count: int = 0) -> str:
    """
    Build the idempotency key for transfer_to_bank().

    Convention: f"NULO-DISB-{transfer_id[:8].upper()}" for the first attempt.
    On retry after a REFUND status, append -R{retry_count}.

    The merchantTxRef is critical -- same key MUST be used on retries for
    the same logical transfer, and a NEW key MUST be generated only after
    a REFUND. See nomba_client.transfer_to_bank docstring.
    PRD Part 1.6.
    """
    base = f"NULO-DISB-{str(transfer_id)[:8].upper()}"
    if retry_count > 0:
        return f"{base}-R{retry_count}"
    return base


# Bank code cache TTL -- 1 day. Codes rarely change per PRD Part 1.5.
BANK_LIST_CACHE_TTL_SECONDS = 86400
