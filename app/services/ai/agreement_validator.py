"""
Post-generation validation & repair for AI-generated tenancy agreements.

WHY THIS MODULE EXISTS:
The Groq prompt already instructs the model to use the exact frequency-based
period rent and a zero (waived) security deposit, but LLMs still hallucinate
occasionally: fabricated deposit/caution-fee amounts, wrong payment-frequency
wording, or invented figures. Prompt instructions alone cannot guarantee the
financial terms, so every generated agreement passes through this
deterministic validation/repair layer BEFORE it is persisted:

  1. validate_financial_terms() -- detect deviations from the expected figures
  2. repair_financial_terms()   -- fix deviations deterministically:
       a. neutralize fabricated non-zero deposit/caution-fee amounts inline
          (deposit is ALWAYS waived under NuloAfrica MVP policy)
       b. append an AUTHORITATIVE FINANCIAL TERMS schedule that prevails over
          any conflicting figures elsewhere in the document
  3. enforce_financial_terms()  -- validate -> repair (if needed) -> re-validate

Design rules:
- Pure functions, no I/O, no LLM calls -- fully unit-testable.
- Repairs are conservative: only deposit-adjacent amounts are rewritten
  inline; everything else is corrected via the prevailing schedule so the
  legal text is never mangled.
- Idempotent: running enforce_financial_terms() twice never appends the
  schedule twice and never modifies already-clean text.
"""

import re
from typing import Dict, List, Set, Tuple

# Must stay in sync with nomba_helpers.FREQUENCY_MULTIPLIERS
FREQUENCY_MULTIPLIERS: Dict[str, int] = {
    "MONTHLY": 1,
    "QUARTERLY": 3,
    "SEMI_ANNUAL": 6,
    "ANNUAL": 12,
}

FREQUENCY_LABELS: Dict[str, str] = {
    "MONTHLY": "monthly in advance",
    "QUARTERLY": "quarterly (every 3 months) in advance",
    "SEMI_ANNUAL": "semi-annually (every 6 months) in advance",
    "ANNUAL": "annually (every 12 months) in advance",
}

ADDENDUM_HEADER = "AUTHORITATIVE FINANCIAL TERMS (PREVAILING SCHEDULE)"

# ── Detection patterns ────────────────────────────────────────────────────────

# Any Naira amount (₦ or NGN), with or without thousands separators.
_AMOUNT_RE = re.compile(r"(?:₦|NGN)\s*(\d[\d,]*)", re.IGNORECASE)

# Phrases that reveal which frequency the document says rent is paid at.
# Deliberately anchored to payment verbs ("paid/payable/due ...") so that
# innocuous mentions like "Monthly Rent: ₦X" do NOT count as a payment
# frequency claim.
_PAYMENT_FREQ_PATTERNS: Dict[str, List[str]] = {
    "MONTHLY": [
        r"(?:paid|payable|due)\s+monthly\b",
        r"on\s+a\s+monthly\s+basis",
        r"every\s+month\b",
        r"per\s+month\b",
        r"monthly\s+in\s+advance",
        r"monthly\s+instal(?:l)?ments?",
    ],
    "QUARTERLY": [
        r"(?:paid|payable|due)\s+quarterly\b",
        r"quarterly\s+in\s+advance",
        r"every\s+3\s+months",
        r"per\s+quarter\b",
    ],
    "SEMI_ANNUAL": [
        r"(?:paid|payable|due)\s+semi[- ]?annually\b",
        r"semi[- ]?annually\s+in\s+advance",
        r"every\s+6\s+months",
    ],
    "ANNUAL": [
        r"(?:paid|payable|due)\s+annually\b",
        r"(?:paid|payable|due)\s+yearly\b",
        r"annually\s+in\s+advance",
        r"every\s+12\s+months",
        r"per\s+annum\b",
        r"once\s+(?:a|per)\s+year",
    ],
}

# A non-zero Naira amount tied to a deposit/caution-fee mention on the same
# line AND same sentence (the middle part stops at "." so that
# "The deposit shall be refunded. Rent: ₦250,000" never flags the rent).
# Multi-word terms ("security deposit", "caution fee") get a longer
# look-ahead than the bare word "deposit" to limit false positives.
_DEPOSIT_MULTIWORD_AMOUNT_RE = re.compile(
    r"\b(?:security\s+deposit|caution\s+fee|caution\s+deposit|tenancy\s+deposit)\b"
    r"(?P<middle>[^.\n]{0,120}?)"
    r"(?:₦|NGN)\s*(?P<amount>\d[\d,]*)",
    re.IGNORECASE,
)
_DEPOSIT_BARE_AMOUNT_RE = re.compile(
    r"\bdeposit\b"
    r"(?P<middle>[^.\n]{0,40}?)"
    r"(?:₦|NGN)\s*(?P<amount>\d[\d,]*)",
    re.IGNORECASE,
)

# Words that negate/waive a deposit mention. Checked both in the text between
# the deposit keyword and the amount AND in a short window before the keyword
# (so "no deposit is required, rent being ₦250,000" is not flagged).
_DEPOSIT_NEGATION_RE = re.compile(
    r"\b(?:waiv\w*|no|not|none|nil|zero|without)\b",
    re.IGNORECASE,
)

# Worded deposit hallucinations: "two months' rent as security deposit",
# "a deposit equivalent to 2 months' rent". These are flagged as WARNINGS
# (covered by the prevailing schedule) because rewriting prose inline is
# riskier than zeroing a numeric amount.
_WORD_DEPOSIT_RE = re.compile(
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})\s*(?:-|\s)\s*months?(?:'s)?\b"
    r"[^\n]{0,60}?\brent\b[^\n]{0,60}?\bdeposit\b"
    r"|\bdeposit\b[^\n]{0,60}?\b(?:of|equivalent\s+to|equal\s+to)\s+"
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|\d{1,2})\s*(?:-|\s)\s*months?",
    re.IGNORECASE,
)


# ── Internals ─────────────────────────────────────────────────────────────────

def _extract_amounts(text: str) -> Set[int]:
    """All ₦/NGN amounts in the text as integers (commas stripped)."""
    amounts: Set[int] = set()
    for raw in _AMOUNT_RE.findall(text or ""):
        try:
            amounts.add(int(raw.replace(",", "")))
        except ValueError:
            continue
    return amounts


def _detect_stated_frequencies(text: str) -> Set[str]:
    """Which payment frequencies the text actually claims."""
    found: Set[str] = set()
    t = text or ""
    for freq, patterns in _PAYMENT_FREQ_PATTERNS.items():
        for pat in patterns:
            if re.search(pat, t, re.IGNORECASE):
                found.add(freq)
                break
    return found


def _find_deposit_amount_violations(text: str) -> List[dict]:
    """
    Non-zero Naira amounts attached to a deposit/caution-fee mention on the
    same line/sentence, where the surrounding words do not waive/negate the
    charge. Returns dicts with the char span of the amount so repair can
    rewrite it.
    """
    violations: List[dict] = []
    seen_spans: Set[Tuple[int, int]] = set()
    t = text or ""
    for regex in (_DEPOSIT_MULTIWORD_AMOUNT_RE, _DEPOSIT_BARE_AMOUNT_RE):
        for m in regex.finditer(t):
            span = (m.start("amount"), m.end("amount"))
            if span in seen_spans:
                continue
            middle = m.group("middle")
            # Negation inside the sentence between keyword and amount...
            if _DEPOSIT_NEGATION_RE.search(middle):
                continue
            # ...or in a short window before the keyword ("no deposit ...").
            before = t[max(0, m.start() - 24):m.start()]
            if _DEPOSIT_NEGATION_RE.search(before):
                continue
            try:
                amount = int(m.group("amount").replace(",", ""))
            except ValueError:
                continue
            if amount > 0:
                seen_spans.add(span)
                violations.append({
                    "amount": amount,
                    "start": span[0],
                    "end": span[1],
                    "snippet": m.group(0)[:160],
                })
    violations.sort(key=lambda v: v["start"])
    return violations


def _find_word_deposit_warnings(text: str) -> List[str]:
    """Worded ('N months' rent as deposit') hallucinations — warnings only."""
    return [m.group(0)[:160] for m in _WORD_DEPOSIT_RE.finditer(text or "")]



# ── Public API ────────────────────────────────────────────────────────────────

def validate_financial_terms(
    text: str,
    expected_monthly_rent: int,
    payment_frequency: str = "MONTHLY",
) -> dict:
    """
    Detect deviations from the expected financial terms. Pure detection --
    never mutates the text.

    Returns:
        {
            "valid": bool,                 # True when no issues found
            "issues": [ {type, severity, detail}, ... ],
            "expected": {monthly_rent, period_rent, payment_frequency},
            "stated_frequencies": [...],   # frequencies the text claims
        }

    Issue types (severity "error" triggers repair, "warning" does not):
        missing_monthly_rent   -- expected monthly rent figure absent
        missing_period_rent    -- expected period rent figure absent
        wrong_frequency        -- text claims a different payment frequency
        unstated_frequency     -- text never states the payment frequency
        fabricated_deposit     -- non-zero deposit/caution-fee amount found
        worded_deposit       -- "N months' rent as deposit" phrasing found

    When the AUTHORITATIVE FINANCIAL TERMS schedule is present (i.e. the text
    was already repaired), its figures prevail: amounts are checked against
    the full text and conflicting frequency wording in the body is downgraded
    to a warning.
    """
    freq = (payment_frequency or "MONTHLY").upper()
    if freq not in FREQUENCY_MULTIPLIERS:
        freq = "MONTHLY"
    multiplier = FREQUENCY_MULTIPLIERS[freq]

    try:
        monthly_rent = int(expected_monthly_rent or 0)
    except (TypeError, ValueError):
        monthly_rent = 0
    period_rent = monthly_rent * multiplier

    t = text or ""
    has_addendum = ADDENDUM_HEADER in t
    body = t.split(ADDENDUM_HEADER, 1)[0] if has_addendum else t

    amounts = _extract_amounts(t)
    stated = _detect_stated_frequencies(body)

    issues: List[dict] = []

    if monthly_rent > 0 and monthly_rent not in amounts:
        issues.append({
            "type": "missing_monthly_rent",
            "severity": "error",
            "detail": f"Expected monthly rent ₦{monthly_rent:,} not found in the document.",
        })

    if period_rent > 0 and period_rent != monthly_rent and period_rent not in amounts:
        issues.append({
            "type": "missing_period_rent",
            "severity": "error",
            "detail": (
                f"Expected {freq.lower()} period rent ₦{period_rent:,} "
                f"(₦{monthly_rent:,} × {multiplier}) not found in the document."
            ),
        })

    conflicting = sorted(stated - {freq})
    if conflicting:
        issues.append({
            "type": "wrong_frequency",
            # Overridden by the prevailing schedule when it is present.
            "severity": "warning" if has_addendum else "error",
            "detail": (
                f"Document states payment frequency {', '.join(conflicting)} "
                f"but the agreed frequency is {freq}."
            ),
        })
    elif not stated and monthly_rent > 0 and not has_addendum:
        issues.append({
            "type": "unstated_frequency",
            "severity": "error",
            "detail": f"Document never states that rent is paid {FREQUENCY_LABELS[freq]}.",
        })

    deposit_violations = _find_deposit_amount_violations(t)
    for v in deposit_violations:
        issues.append({
            "type": "fabricated_deposit",
            "severity": "error",
            "detail": f"Fabricated deposit amount ₦{v['amount']:,}: \"{v['snippet']}\"",
        })

    worded = _find_word_deposit_warnings(body)
    for w in worded:
        issues.append({
            "type": "worded_deposit",
            "severity": "warning",
            "detail": f"Worded deposit clause: \"{w}\"",
        })

    return {
        "valid": not any(i["severity"] == "error" for i in issues),
        "issues": issues,
        "expected": {
            "monthly_rent": monthly_rent,
            "period_rent": period_rent,
            "payment_frequency": freq,
        },
        "stated_frequencies": sorted(stated),
    }


def _build_addendum(
    monthly_rent: int,
    period_rent: int,
    freq: str,
    has_worded_deposit_warning: bool,
) -> str:
    """The prevailing financial-terms schedule appended to repaired agreements."""
    freq_label = FREQUENCY_LABELS[freq]
    lines = [
        "",
        ADDENDUM_HEADER,
        "=" * len(ADDENDUM_HEADER),
        "The figures below are authoritative and prevail over any conflicting",
        "amounts or payment-frequency wording elsewhere in this agreement:",
        "",
        f"  - Monthly Rent: ₦{monthly_rent:,}",
        f"  - Period Rent ({freq}): ₦{period_rent:,} — payable {freq_label}",
        "  - Security Deposit / Caution Fee: ₦0 (WAIVED — NuloAfrica MVP policy;",
        "    no deposit or caution fee is required for this tenancy)",
        "  - Platform Fee: ₦0 (waived)",
        "  - Payment Method: Via the NuloAfrica platform (virtual account transfer)",
    ]
    if has_worded_deposit_warning:
        lines.append(
            "  - Any clause elsewhere in this agreement requiring a deposit of"
        )
        lines.append(
            "    'N months' rent' or similar is void and replaced by the ₦0"
        )
        lines.append(
            "    waived deposit stated above."
        )
    return "\n".join(lines) + "\n"


def repair_financial_terms(
    text: str,
    expected_monthly_rent: int,
    payment_frequency: str = "MONTHLY",
) -> dict:
    """
    Deterministically repair hallucinated financial terms.

    Repairs (conservative, in this order):
      1. Inline: rewrite every fabricated non-zero deposit/caution-fee amount
         to "0 (waived)" so the sentence still reads naturally.
      2. Append (or replace, if already present) the AUTHORITATIVE FINANCIAL
         TERMS schedule with the exact expected figures. This covers wrong
         frequency wording, missing figures, and worded deposit clauses
         without mangling legal prose.

    Idempotent: clean text is returned unchanged; running twice never
    duplicates the schedule.

    Returns:
        {
            "text": repaired text,
            "repaired": bool,          # True when any change was made
            "repairs": [str, ...],     # human-readable list of repairs
        }
    """
    freq = (payment_frequency or "MONTHLY").upper()
    if freq not in FREQUENCY_MULTIPLIERS:
        freq = "MONTHLY"
    multiplier = FREQUENCY_MULTIPLIERS[freq]

    try:
        monthly_rent = int(expected_monthly_rent or 0)
    except (TypeError, ValueError):
        monthly_rent = 0
    period_rent = monthly_rent * multiplier

    t = text or ""
    repairs: List[str] = []

    validation = validate_financial_terms(t, monthly_rent, freq)
    error_types = {i["type"] for i in validation["issues"] if i["severity"] == "error"}
    has_worded_warning = any(
        i["type"] == "worded_deposit" for i in validation["issues"]
    )

    # Nothing to repair: return unchanged (idempotent no-op).
    if not error_types and not has_worded_warning:
        return {"text": t, "repaired": False, "repairs": []}

    # 1. Neutralize fabricated deposit amounts inline.
    deposit_violations = _find_deposit_amount_violations(t)
    if deposit_violations:
        # Rewrite from the end so earlier spans stay valid.
        for v in reversed(deposit_violations):
            t = t[:v["start"]] + "0 (waived)" + t[v["end"]:]
        repairs.append(
            f"Neutralized {len(deposit_violations)} fabricated deposit amount(s) to ₦0 (waived)."
        )

    # 2. Append/replace the prevailing schedule.
    addendum = _build_addendum(monthly_rent, period_rent, freq, has_worded_warning)
    if ADDENDUM_HEADER in t:
        # Replace the previously appended block (idempotency).
        idx = t.index(ADDENDUM_HEADER)
        # Cut back to the blank line that precedes the header, if any.
        cut = t.rfind("\n\n", 0, idx)
        head = t[:cut] if cut != -1 else t[:idx]
        t = head.rstrip() + "\n" + addendum
        repairs.append("Replaced the existing authoritative financial-terms schedule.")
    else:
        t = t.rstrip() + "\n" + addendum
        repairs.append("Appended the authoritative financial-terms schedule.")

    return {"text": t, "repaired": True, "repairs": repairs}


def enforce_financial_terms(
    text: str,
    expected_monthly_rent: int,
    payment_frequency: str = "MONTHLY",
) -> dict:
    """
    Full pipeline: validate -> repair (if needed) -> re-validate.

    Returns:
        {
            "text": final text (repaired if necessary),
            "valid_before": bool,
            "valid_after": bool,
            "repaired": bool,
            "issues_before": [...],
            "issues_after": [...],
            "repairs": [...],
            "expected": {monthly_rent, period_rent, payment_frequency},
        }
    """
    before = validate_financial_terms(text, expected_monthly_rent, payment_frequency)

    if before["valid"] and not any(
        i["type"] == "worded_deposit" for i in before["issues"]
    ):
        return {
            "text": text or "",
            "valid_before": True,
            "valid_after": True,
            "repaired": False,
            "issues_before": [],
            "issues_after": [],
            "repairs": [],
            "expected": before["expected"],
        }

    repair = repair_financial_terms(text, expected_monthly_rent, payment_frequency)
    after = validate_financial_terms(
        repair["text"], expected_monthly_rent, payment_frequency
    )

    return {
        "text": repair["text"],
        "valid_before": before["valid"],
        "valid_after": after["valid"],
        "repaired": repair["repaired"],
        "issues_before": before["issues"],
        "issues_after": after["issues"],
        "repairs": repair["repairs"],
        "expected": before["expected"],
    }
