"""
Unit tests for the deterministic landlord briefing format and the
viewing auto-complete (lazy expiry) helpers.

Covers:
  1. _build_landlord_briefing — newline/bullet structure, evidence-only,
     "Not provided by tenant:" gaps line, chat-compatible plain syntax.
  2. _parse_confirmed_time — 12h AM/PM edges (12 AM = midnight, 12 PM = noon),
     24h times, invalid inputs.
  3. _viewing_is_overdue — same-day viewings must NOT complete before their
     time; past dates complete; unparseable time on an arrived date completes.
"""

from datetime import datetime, time as dtime

import pytest

from app.propflow.nodes.enrich_qualify import (
    _build_landlord_briefing,
    _build_trust_line,
)
from app.routes.viewing_requests import (
    _parse_confirmed_time,
    _viewing_is_overdue,
)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

TENANT = {"full_name": "Ada Obi", "email": "ada@example.com"}
PROPERTY = {
    "title": "2-Bed Apartment",
    "location": "Lekki Phase 1",
    "price": 480000.0,
}
INTENT = {
    "bedrooms": 2,
    "property_type": "apartment",
    "location": "Lekki",
}
TRUST_FIELDS_FULL = {
    "employment_status": "full-time",
    "employer_name": "Acme Ltd",
    "monthly_income": 1200000,
    "move_in_date": "2026-09-01",
    "lease_duration": "1 year",
    "number_of_occupants": 2,
    "has_pets": False,
    "pet_details": None,
}
TRUST_STATUS_FULL = {
    "documents": {"id_card": "verified", "pay_slip": "provided"},
    "references": {"ref_1": "confirmed"},
}


def _briefing(trust_fields=None, trust_status=None, intent=None):
    return _build_landlord_briefing(
        tenant_data=TENANT,
        property_data=PROPERTY,
        intent=intent if intent is not None else INTENT,
        trust_fields=trust_fields if trust_fields is not None else TRUST_FIELDS_FULL,
        trust_status=trust_status if trust_status is not None else TRUST_STATUS_FULL,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. _build_landlord_briefing
# ─────────────────────────────────────────────────────────────────────────────

class TestBuildLandlordBriefing:
    def test_structure_header_then_bullets(self):
        text = _briefing()
        lines = text.split("\n")

        # Header sentence first, ends with a period.
        assert lines[0].startswith("Ada Obi applied for 2-Bed Apartment")
        assert lines[0].endswith(".")
        assert "Lekki Phase 1" in lines[0]
        assert "NGN 480,000/month" in lines[0]

        # "What we know:" label followed by one "- " bullet per fact.
        assert "What we know:" in lines
        idx = lines.index("What we know:")
        bullets = [l for l in lines[idx + 1:] if l.startswith("- ")]
        assert len(bullets) >= 4  # Requested, Employment, Income, Tenancy, Trust

    def test_evidence_only_facts_present(self):
        text = _briefing()
        assert "Requested: 2-bed apartment in Lekki" in text
        assert "Employment: Full Time at Acme Ltd" in text
        assert "Income: NGN 1,200,000" in text
        assert "2.5x monthly rent" in text
        assert "move-in 01 Sep 2026" in text
        assert "Trust status:" in text

    def test_gaps_line_when_trust_fields_missing(self):
        empty_fields = {k: None for k in TRUST_FIELDS_FULL}
        text = _briefing(trust_fields=empty_fields, trust_status={})
        assert "Not provided by tenant:" in text
        assert "employment status" in text
        assert "income" in text
        assert "move-in date" in text
        # No employment/income bullets should appear.
        assert "Employment:" not in text
        assert "Income:" not in text

    def test_no_gaps_line_when_all_provided(self):
        text = _briefing()
        assert "Not provided by tenant:" not in text

    def test_no_facts_fallback(self):
        text = _briefing(
            trust_fields={k: None for k in TRUST_FIELDS_FULL},
            trust_status={},
            intent={},
        )
        assert "No additional details were provided by the tenant." in text
        assert "What we know:" not in text

    def test_chat_compatible_plain_syntax(self):
        """Briefing is injected verbatim into the chat widget (whitespace-pre-wrap)
        and rendered via <Markdown> on the dashboard — so only newlines and
        '- ' bullets are allowed. No **bold**, no # headers, no JSON."""
        text = _briefing()
        assert "**" not in text
        assert "#" not in text
        assert "{" not in text and "}" not in text

    def test_never_invents_facts(self):
        """With only an employer provided, no income/tenancy lines may appear."""
        partial = {k: None for k in TRUST_FIELDS_FULL}
        partial["employment_status"] = "full-time"
        partial["employer_name"] = "Acme Ltd"
        text = _briefing(trust_fields=partial, trust_status={})
        assert "Employment: Full Time at Acme Ltd" in text
        assert "Income:" not in text
        assert "Tenancy:" not in text
        assert "income" in text  # listed as a gap
        assert "move-in date" in text  # listed as a gap


class TestBuildTrustLine:
    def test_empty_when_no_evidence(self):
        assert _build_trust_line({}) == ""
        assert _build_trust_line({"documents": {}, "references": {}}) == ""

    def test_counts_statuses(self):
        line = _build_trust_line(TRUST_STATUS_FULL)
        assert line.startswith("Trust status:")
        assert "1 provided" in line
        assert "1 verified" in line
        assert "References: 1 supplied, 1 confirmed" in line


# ─────────────────────────────────────────────────────────────────────────────
# 2. _parse_confirmed_time
# ─────────────────────────────────────────────────────────────────────────────

class TestParseConfirmedTime:
    @pytest.mark.parametrize("raw,expected", [
        ("12:00 AM", dtime(0, 0)),    # midnight
        ("12:00 PM", dtime(12, 0)),   # noon
        ("12:30 AM", dtime(0, 30)),
        ("12:30 PM", dtime(12, 30)),
        ("1:00 AM", dtime(1, 0)),
        ("1:00 PM", dtime(13, 0)),
        ("10:00 AM", dtime(10, 0)),
        ("10:00 PM", dtime(22, 0)),
        ("11:59 PM", dtime(23, 59)),
        ("10:00AM", dtime(10, 0)),    # no space before meridiem
        ("10:00 am", dtime(10, 0)),   # lowercase
        ("09:15", dtime(9, 15)),      # 24h
        ("22:30", dtime(22, 30)),     # 24h
        ("00:05", dtime(0, 5)),       # 24h midnight-ish
        ("23:59", dtime(23, 59)),     # 24h max
    ])
    def test_valid_times(self, raw, expected):
        assert _parse_confirmed_time(raw) == expected

    @pytest.mark.parametrize("raw", [
        None,
        "",
        "   ",
        "13:00 PM",      # hour out of 1-12 range for 12h
        "0:00 AM",       # hour 0 invalid in 12h
        "24:00",         # 24h hour out of range
        "25:30",
        "10:60",         # minute out of range (regex won't match)
        "10.00 AM",
        "ten o'clock",
        "morning",
    ])
    def test_invalid_times(self, raw):
        assert _parse_confirmed_time(raw) is None


# ─────────────────────────────────────────────────────────────────────────────
# 3. _viewing_is_overdue
# ─────────────────────────────────────────────────────────────────────────────

def _viewing(status="confirmed", confirmed_date=None, confirmed_time=None):
    return {
        "id": "v-1",
        "status": status,
        "confirmed_date": confirmed_date,
        "confirmed_time": confirmed_time,
    }


class TestViewingIsOverdue:
    NOW = datetime(2026, 8, 17, 14, 0, 0)  # 2:00 PM

    def test_past_date_is_overdue(self):
        v = _viewing(confirmed_date="2026-08-16", confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is True

    def test_future_date_is_not_overdue(self):
        v = _viewing(confirmed_date="2026-08-18", confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_same_day_before_time_not_overdue(self):
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="4:00 PM")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_same_day_after_time_is_overdue(self):
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is True

    def test_same_day_exact_time_not_overdue(self):
        """Boundary: appointment exactly now is not yet overdue (<, not <=)."""
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="2:00 PM")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_same_day_midnight_edge(self):
        """12:00 AM = midnight → already past by 2 PM same day."""
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="12:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is True

    def test_same_day_noon_edge(self):
        """12:00 PM = noon → already past by 2 PM same day."""
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="12:00 PM")
        assert _viewing_is_overdue(v, self.NOW) is True

    def test_unparseable_time_on_arrived_date_completes(self):
        """Intended behaviour: date has arrived, no valid time → don't leave stale."""
        v = _viewing(confirmed_date="2026-08-17", confirmed_time="sometime")
        assert _viewing_is_overdue(v, self.NOW) is True

    def test_unparseable_time_on_future_date_not_overdue(self):
        v = _viewing(confirmed_date="2026-08-18", confirmed_time="sometime")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_invalid_date_not_overdue(self):
        v = _viewing(confirmed_date="not-a-date", confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_missing_date_not_overdue(self):
        v = _viewing(confirmed_date=None, confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is False

    @pytest.mark.parametrize("status", ["pending", "reschedule_proposed", "cancelled", "completed", "no_show"])
    def test_non_confirmed_statuses_never_overdue(self, status):
        v = _viewing(status=status, confirmed_date="2026-08-16", confirmed_time="10:00 AM")
        assert _viewing_is_overdue(v, self.NOW) is False

    def test_iso_datetime_in_confirmed_date(self):
        """confirmed_date may arrive as a full ISO timestamp — only date part matters."""
        v = _viewing(confirmed_date="2026-08-16T10:00:00+01:00", confirmed_time=None)
        assert _viewing_is_overdue(v, self.NOW) is True
