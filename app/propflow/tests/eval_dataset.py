"""
PropFlow Evaluation Dataset
10 labeled tenant inquiry test cases for agent evaluation.

Coverage:
  - 5 Nigerian Pidgin inputs
  - 3 broken/informal English inputs
  - 2 formal English inputs
  - Edge cases: ambiguous budget, no bedrooms stated, mixed Pidgin+English,
    shorthand locations (VI, GRA, PH), million-naira budgets

Each case has:
  input:    raw tenant message (what the agent receives)
  expected: ground-truth extraction (what the agent SHOULD produce)
  notes:    what this case is specifically testing

'expected' uses None for genuinely unknown fields -- not for fields the
model should infer. If a field can be derived (e.g. annual from monthly),
it should appear in expected so we can test the derivation logic.
"""

EVAL_DATASET = [
    # ── Case 01: Classic Pidgin, VI, shorthand budget ────────────────────────
    {
        "id": "TC-01",
        "label": "Pidgin - VI self-contain 500k",
        "input": "I wan rent one self-contain for VI, 500k per month max, I fit move ASAP",
        "expected": {
            "property_type": "self-contain",
            "location": "VI",
            "bedrooms": None,        # self-contain implies 1 room, but not stated
            "budget_monthly": 500000.0,
            "budget_annual": 6000000.0,
            "payment_frequency": None,
            "move_in_date": None,    # "ASAP" -- accept None or today's date
            "special_requests": None,
        },
        "notes": "Tests: Pidgin 'wan', 'self-contain', 'fit move', shorthand '500k', 'ASAP' handling",
        "min_confidence": 0.80,
    },

    # ── Case 02: Pidgin, Lekki, annual budget stated ─────────────────────────
    {
        "id": "TC-02",
        "label": "Pidgin - Lekki 2-bed 1.2m annual",
        "input": "E get 2 bedroom flat for Lekki wey dey available? My budget na 1.2m per year, I wan pay quarterly",
        "expected": {
            "property_type": "flat",
            "location": "Lekki",
            "bedrooms": 2,
            "budget_monthly": 100000.0,   # derived: 1.2m / 12
            "budget_annual": 1200000.0,
            "payment_frequency": "QUARTERLY",
            "move_in_date": None,
            "special_requests": None,
        },
        "notes": "Tests: 'E get...wey dey', million-naira budget, quarterly preference, monthly derivation",
        "min_confidence": 0.80,
    },

    # ── Case 03: Pidgin, GRA Abuja, high budget ──────────────────────────────
    {
        "id": "TC-03",
        "label": "Pidgin - GRA Abuja duplex 3.5m",
        "input": "Bros I dey find 3 bedroom duplex around GRA Abuja area. Budget fit reach 3.5m annual. I wan move next month",
        "expected": {
            "property_type": "duplex",
            "location": "GRA Abuja",
            "bedrooms": 3,
            "budget_monthly": 291666.67,  # 3.5m / 12, accept ~291k-292k
            "budget_annual": 3500000.0,
            "payment_frequency": None,
            "move_in_date": None,   # "next month" -- accept None or first of next month
            "special_requests": None,
        },
        "notes": "Tests: 'dey find', GRA compound location, 3.5m budget, 'next month' date handling",
        "min_confidence": 0.75,
    },

    # ── Case 04: Pidgin, face-me-I-face-you edge case ───────────────────────
    {
        "id": "TC-04",
        "label": "Pidgin - room-and-parlour Yaba 80k",
        "input": "I need room and parlour for Yaba self contain, 80k per month. I be student",
        "expected": {
            "property_type": "self-contain",
            "location": "Yaba",
            "bedrooms": 1,
            "budget_monthly": 80000.0,
            "budget_annual": 960000.0,
            "payment_frequency": None,
            "move_in_date": None,
            "special_requests": "student",
        },
        "notes": "Tests: 'room and parlour self contain' disambiguation, student context as special_request",
        "min_confidence": 0.70,
    },

    # ── Case 05: Pidgin mixed with English, PH ───────────────────────────────
    {
        "id": "TC-05",
        "label": "Mixed Pidgin-English - PH 2-bed 150k",
        "input": "Looking for 2 bedroom apartment in Port Harcourt, preferably GRA. Max 150k monthly, I can do semi-annual payment",
        "expected": {
            "property_type": "flat",
            "location": "Port Harcourt",
            "bedrooms": 2,
            "budget_monthly": 150000.0,
            "budget_annual": 1800000.0,
            "payment_frequency": "SEMI_ANNUAL",
            "move_in_date": None,
            "special_requests": "GRA preferred",
        },
        "notes": "Tests: PH location, semi-annual frequency, GRA as special_request",
        "min_confidence": 0.85,
    },

    # ── Case 06: Informal English, Ikeja, studio ─────────────────────────────
    {
        "id": "TC-06",
        "label": "Informal English - Ikeja studio 120k",
        "input": "hi pls do u have any studio or mini flat in ikeja or surulere? budget 120k/month. need it urgently for August",
        "expected": {
            "property_type": "self-contain",  # studio/mini-flat maps to self-contain
            "location": "Ikeja",              # first location mentioned
            "bedrooms": 1,
            "budget_monthly": 120000.0,
            "budget_annual": 1440000.0,
            "payment_frequency": None,
            "move_in_date": None,             # "August" without year -- accept None or 2026-08-01
            "special_requests": "or Surulere also acceptable",
        },
        "notes": "Tests: 'studio/mini flat' -> self-contain, multiple locations, urgency signal",
        "min_confidence": 0.75,
    },

    # ── Case 07: Informal English, missing location ───────────────────────────
    {
        "id": "TC-07",
        "label": "Informal English - missing location low confidence",
        "input": "need 3bed house, budget around 2m, want to move in 2 weeks",
        "expected": {
            "property_type": "flat",          # generic "house" -> flat
            "location": None,                 # no location -- should be None
            "bedrooms": 3,
            "budget_monthly": 166666.67,      # 2m / 12
            "budget_annual": 2000000.0,
            "payment_frequency": None,
            "move_in_date": None,             # "2 weeks" -- relative date
            "special_requests": None,
        },
        "notes": "Tests: missing location -> confidence should drop below 0.80, not below 0.70",
        "min_confidence": 0.60,   # lower threshold -- incomplete input is valid
        "max_confidence": 0.82,   # confidence should NOT be high with no location
    },

    # ── Case 08: Formal English, complete input ───────────────────────────────
    {
        "id": "TC-08",
        "label": "Formal English - complete Lekki Phase 1",
        "input": "I am looking for a 3-bedroom flat in Lekki Phase 1. My annual budget is NGN 2,400,000 and I prefer to pay annually. I intend to move in on 1st September 2026.",
        "expected": {
            "property_type": "flat",
            "location": "Lekki Phase 1",
            "bedrooms": 3,
            "budget_monthly": 200000.0,
            "budget_annual": 2400000.0,
            "payment_frequency": "ANNUAL",
            "move_in_date": "2026-09-01",
            "special_requests": None,
        },
        "notes": "Tests: formal English, comma-formatted NGN amount, explicit ANNUAL frequency, exact date",
        "min_confidence": 0.90,   # formal complete input should score high
    },

    # ── Case 09: Formal English, BQ request ──────────────────────────────────
    {
        "id": "TC-09",
        "label": "Formal English - Ikoyi 4-bed + BQ",
        "input": "We require a 4-bedroom detached house with BQ in Ikoyi or Banana Island. Budget is flexible up to NGN 8,000,000 per annum. Payment can be made annually.",
        "expected": {
            "property_type": "duplex",        # detached house -> duplex
            "location": "Ikoyi",              # first location
            "bedrooms": 4,
            "budget_monthly": 666666.67,
            "budget_annual": 8000000.0,
            "payment_frequency": "ANNUAL",
            "move_in_date": None,
            "special_requests": "BQ required, Banana Island also acceptable",
        },
        "notes": "Tests: 'per annum', detached->duplex, BQ and alternative location as special_request",
        "min_confidence": 0.88,
    },

    # ── Case 10: Ambiguous / stress test ─────────────────────────────────────
    {
        "id": "TC-10",
        "label": "Ambiguous - very short Pidgin",
        "input": "I need house for Lagos cheap cheap",
        "expected": {
            "property_type": None,            # too vague
            "location": "Lagos",
            "bedrooms": None,
            "budget_monthly": None,           # "cheap cheap" not a number
            "budget_annual": None,
            "payment_frequency": None,
            "move_in_date": None,
            "special_requests": "affordable / budget-friendly",
        },
        "notes": "Stress test: very vague input. Confidence MUST be < 0.70 (triggers clarification gate)",
        "min_confidence": 0.0,
        "max_confidence": 0.69,   # MUST route to needs_clarification
    },
]


# ── Briefing evaluation cases ─────────────────────────────────────────────────
# Used to evaluate generate_landlord_briefing quality.
# 'grounding_facts' are the ONLY facts allowed in the briefing output --
# any other specific claim = hallucination.

BRIEFING_EVAL_CASES = [
    {
        "id": "BC-01",
        "label": "Software engineer, quarterly preference",
        "tenant_data": {
            "full_name": "Chidi Obi",
            "occupation": "Software Engineer",
            "employer": "Flutterwave",
            "monthly_income": 450000,
            "email": "chidi@example.com",
        },
        "property_data": {
            "title": "2-Bedroom Flat, Lekki Phase 1",
            "location": "Lekki Phase 1",
            "price": 1200000,
        },
        "extracted_intent": {
            "bedrooms": 2,
            "property_type": "flat",
            "location": "Lekki Phase 1",
            "budget_monthly": 100000,
            "payment_frequency": "QUARTERLY",
        },
        "grounding_facts": [
            "Chidi Obi", "Software Engineer", "Flutterwave",
            "450,000", "2-Bedroom", "Lekki", "quarterly", "QUARTERLY",
        ],
        "must_contain_sentences": 3,
    },
    {
        "id": "BC-02",
        "label": "Teacher, annual preference, no employer",
        "tenant_data": {
            "full_name": "Adaeze Nwosu",
            "occupation": "Secondary School Teacher",
            "employer": None,
            "monthly_income": 120000,
            "email": "adaeze@example.com",
        },
        "property_data": {
            "title": "Self-Contain, Yaba",
            "location": "Yaba",
            "price": 600000,
        },
        "extracted_intent": {
            "bedrooms": 1,
            "property_type": "self-contain",
            "location": "Yaba",
            "budget_monthly": 50000,
            "payment_frequency": "ANNUAL",
        },
        "grounding_facts": [
            "Adaeze Nwosu", "Teacher", "120,000",
            "Self-Contain", "Yaba", "annual", "ANNUAL",
        ],
        "must_contain_sentences": 3,
    },
]
