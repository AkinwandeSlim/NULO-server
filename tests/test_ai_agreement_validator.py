"""
AI agreement financial-terms validator tests.
Run: pytest test_ai_agreement_validator.py -v

Covers the deterministic post-generation validation/repair layer that guards
against LLM-hallucinated financial terms (fabricated deposits, wrong payment
frequency wording, missing rent figures).
"""
import os
import sys

import pytest

# Make the app package importable when running tests from the server dir
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.services.ai.agreement_validator import (
    ADDENDUM_HEADER,
    FREQUENCY_MULTIPLIERS,
    enforce_financial_terms,
    repair_financial_terms,
    validate_financial_terms,
)


MONTHLY_RENT = 250_000

# Adverb forms used in "payable <adverb> in advance" clauses.
_FREQ_ADVERB = {
    "MONTHLY": "monthly",
    "QUARTERLY": "quarterly",
    "SEMI_ANNUAL": "semi-annually",
    "ANNUAL": "annually",
}


def _clean_agreement(freq="MONTHLY"):
    """A well-formed agreement body that should pass validation untouched."""
    multiplier = FREQUENCY_MULTIPLIERS[freq]
    period = MONTHLY_RENT * multiplier
    adverb = _FREQ_ADVERB[freq]
    return (
        "TENANCY AGREEMENT\n"
        f"1.0 The monthly rent is NGN {MONTHLY_RENT:,}.\n"
        f"2.0 The period rent is NGN {period:,} payable {adverb} in advance.\n"
        "3.0 The security deposit is NGN 0 (waived by NuloAfrica policy).\n"
        "4.0 The tenant shall pay rent via the NuloAfrica platform.\n"
    )


# ============================================================
# validate_financial_terms — clean text
# ============================================================

def test_clean_monthly_agreement_is_valid():
    result = validate_financial_terms(_clean_agreement("MONTHLY"), MONTHLY_RENT, "MONTHLY")
    assert result["valid"] is True
    assert result["issues"] == []
    assert result["expected"]["monthly_rent"] == MONTHLY_RENT
    assert result["expected"]["period_rent"] == MONTHLY_RENT


def test_clean_quarterly_agreement_is_valid():
    result = validate_financial_terms(_clean_agreement("QUARTERLY"), MONTHLY_RENT, "QUARTERLY")
    assert result["valid"] is True
    assert result["expected"]["period_rent"] == MONTHLY_RENT * 3


def test_clean_annual_agreement_is_valid():
    result = validate_financial_terms(_clean_agreement("ANNUAL"), MONTHLY_RENT, "ANNUAL")
    assert result["valid"] is True
    assert result["expected"]["period_rent"] == MONTHLY_RENT * 12


# ============================================================
# validate_financial_terms — detection of hallucinations
# ============================================================

def test_detects_fabricated_deposit_amount():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "The tenant shall pay a security deposit of NGN 500,000."
    )
    result = validate_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    types = [i["type"] for i in result["issues"]]
    assert "fabricated_deposit" in types
    assert result["valid"] is False


def test_detects_wrong_payment_frequency():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,}. "
        "Rent is paid annually in advance."
    )
    result = validate_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    types = [i["type"] for i in result["issues"]]
    assert "wrong_frequency" in types


def test_detects_missing_period_rent():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,}. "
        "Rent is paid quarterly in advance."
    )
    result = validate_financial_terms(text, MONTHLY_RENT, "QUARTERLY")
    types = [i["type"] for i in result["issues"]]
    # Quarterly period rent (750,000) is absent from the text.
    assert "missing_period_rent" in types


def test_detects_worded_deposit_clause():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "Two months rent as deposit is required."
    )
    result = validate_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    types = [i["type"] for i in result["issues"]]
    assert "worded_deposit" in types


def test_negated_deposit_is_not_flagged():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "No security deposit or caution fee is required for this tenancy."
    )
    result = validate_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    types = [i["type"] for i in result["issues"]]
    assert "fabricated_deposit" not in types
    assert result["valid"] is True


def test_zero_deposit_is_not_flagged():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "The security deposit is NGN 0 (waived)."
    )


# ============================================================
# repair_financial_terms
# ============================================================

def test_repair_neutralizes_fabricated_deposit_inline():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "The tenant shall pay a security deposit of NGN 500,000."
    )
    result = repair_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    assert result["repaired"] is True
    assert "500,000" not in result["text"]
    assert "0 (waived)" in result["text"]
    assert ADDENDUM_HEADER in result["text"]


def test_repair_appends_prevailing_schedule():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,}. "
        "Rent is paid annually in advance. Deposit: NGN 100,000."
    )
    result = repair_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    assert ADDENDUM_HEADER in result["text"]
    assert f"₦{MONTHLY_RENT:,}" in result["text"]
    assert "₦0 (WAIVED" in result["text"]


def test_repair_is_idempotent():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,}. "
        "Rent is paid annually in advance. Deposit: NGN 100,000."
    )
    first = repair_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    second = repair_financial_terms(first["text"], MONTHLY_RENT, "MONTHLY")
    # Second pass must not duplicate the schedule.
    assert second["text"].count(ADDENDUM_HEADER) == 1
    assert second["repaired"] is False


def test_repair_clean_text_is_unchanged():
    clean = _clean_agreement("MONTHLY")
    result = repair_financial_terms(clean, MONTHLY_RENT, "MONTHLY")
    assert result["repaired"] is False
    assert result["text"] == clean
    assert result["repairs"] == []


# ============================================================
# enforce_financial_terms — full pipeline
# ============================================================

def test_enforce_repairs_hallucinated_terms():
    bad = (
        "TENANCY AGREEMENT\n"
        "The rent is NGN 250,000 paid annually. "
        "The tenant shall pay a security deposit of NGN 500,000. "
        "Two months rent as deposit is required."
    )
    result = enforce_financial_terms(bad, MONTHLY_RENT, "MONTHLY")
    assert result["repaired"] is True
    assert result["valid_before"] is False
    assert result["valid_after"] is True
    assert "500,000" not in result["text"]
    assert ADDENDUM_HEADER in result["text"]


def test_enforce_clean_text_passthrough():
    clean = _clean_agreement("MONTHLY")
    result = enforce_financial_terms(clean, MONTHLY_RENT, "MONTHLY")
    assert result["repaired"] is False
    assert result["valid_before"] is True
    assert result["valid_after"] is True
    assert result["text"] == clean


def test_enforce_is_idempotent():
    bad = f"Rent NGN {MONTHLY_RENT:,} paid quarterly. Deposit: NGN 100,000."
    first = enforce_financial_terms(bad, MONTHLY_RENT, "QUARTERLY")
    second = enforce_financial_terms(first["text"], MONTHLY_RENT, "QUARTERLY")
    assert second["repaired"] is False
    assert second["valid_after"] is True
    assert second["text"].count(ADDENDUM_HEADER) == 1


def test_enforce_handles_empty_text():
    result = enforce_financial_terms("", MONTHLY_RENT, "MONTHLY")
    # Empty text is missing everything -> repaired with the schedule.
    assert result["expected"]["monthly_rent"] == MONTHLY_RENT
    assert isinstance(result["text"], str)


def test_enforce_handles_zero_rent_gracefully():
    text = "TENANCY AGREEMENT. Rent to be agreed."
    result = enforce_financial_terms(text, 0, "MONTHLY")
    # With no expected rent, only deposit/frequency checks apply; must not raise.
    assert isinstance(result["text"], str)
    assert result["expected"]["monthly_rent"] == 0


def test_enforce_unknown_frequency_defaults_to_monthly():
    clean = _clean_agreement("MONTHLY")
    result = enforce_financial_terms(clean, MONTHLY_RENT, "BOGUS_FREQ")
    assert result["expected"]["payment_frequency"] == "MONTHLY"


def test_enforce_returns_issue_details():
    bad = f"Rent NGN {MONTHLY_RENT:,} paid annually. Deposit: NGN 100,000."
    result = enforce_financial_terms(bad, MONTHLY_RENT, "MONTHLY")
    before_types = [i["type"] for i in result["issues_before"]]
    assert "fabricated_deposit" in before_types
    assert "wrong_frequency" in before_types
    assert result["repairs"]  # non-empty list of human-readable repairs


# ============================================================
# Multiple fabricated deposits
# ============================================================

def test_repair_neutralizes_multiple_deposit_amounts():
    text = (
        f"Monthly rent NGN {MONTHLY_RENT:,} paid monthly in advance. "
        "Security deposit: NGN 300,000. Caution fee: NGN 200,000."
    )
    result = repair_financial_terms(text, MONTHLY_RENT, "MONTHLY")
    assert "300,000" not in result["text"]
    assert "200,000" not in result["text"]
    assert result["repaired"] is True

    # The repaired text must no longer flag fabricated deposits.
    revalidated = validate_financial_terms(result["text"], MONTHLY_RENT, "MONTHLY")
    types = [i["type"] for i in revalidated["issues"]]
    assert "fabricated_deposit" not in types
