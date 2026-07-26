"""
Seed PropFlow Demo Tenant
=========================
Fills in profile data for the existing demo tenant:
  slimmedia0705@gmail.com  (Akinwande Alexander)
  ID: 56793d3d-820a-4430-82fd-58f37fd98a1b

What the application form actually collects (traced from apply/page.tsx):
  Step 1  firstName/lastName/email/phone/dob/nationality/marital/dependents
          → NONE of these go to applications table (only exist in users row)
  Step 2  employment_status, employer_name, monthly_income (int)
          → applications.employment_status / employer_name / monthly_income
          jobTitle NOT saved (no column in applications)
  Step 3  reference1/2 name+phone+relationship → applications.references (JSONB)
          emergencyContactName/Phone → applications.emergency_contact_name/phone
  Step 4  uploaded file paths → applications.documents (text[])
  Step 5  move_in_date, lease_duration, number_of_occupants, has_pets,
          pet_details, message → corresponding applications columns

What this script seeds:
  1. public.users          — fill phone, first/last name, location
  2. tenant_profiles       — fill employment, income, preferences
  3. tenants               — INSERT row (budget, location, preferences)

What this script does NOT seed:
  - An application row — PropFlow creates that at runtime. Creating one here
    would trigger the "already applied" duplicate check and block the demo.
  - Auth users (must exist already in Supabase Auth)

Usage:
  python scripts/seed_propflow_demo.py
"""

import os
import json
import sys
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

SUPABASE_URL = "https://tqmjcygeykmbdjcfdbga.supabase.co"
# Falls back to hardcoded service key so the script works without .env
SUPABASE_KEY = (
    os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    or os.environ.get("SUPABASE_SERVICE_KEY")
    or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InRxbWpjeWdleWttYmRqY2ZkYmdhIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImlhdCI6MTc2MDExMzQzNCwiZXhwIjoyMDc1Njg5NDM0fQ.7useaWdWgZ6VVDzCfwFbcu9pubZ9_8SycyMvAkkJqAg"
)

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation",
}

# ── Real tenant (fetched 2026-07-15) ─────────────────────────────────────────
# TENANT_ID    = "56793d3d-820a-4430-82fd-58f37fd98a1b"
# TENANT_EMAIL = "slimmedia0705@gmail.com"
# TENANT_NAME  = "Akinwande Alexander"





TENANT_ID    = "97d702c7-e439-4b40-aaed-0b2104fac061"
TENANT_EMAIL = "akinalex21@gmail.com"
TENANT_NAME  = "Akinwande Alexander"


def req(method: str, path: str, body: dict = None) -> tuple[int, any]:
    url = f"{SUPABASE_URL}/rest/v1/{path}"
    fn = getattr(requests, method)
    kwargs = dict(headers=HEADERS, verify=False)
    if body is not None:
        kwargs["json"] = body
    r = fn(url, **kwargs)
    try:
        data = r.json()
    except Exception:
        data = r.text
    return r.status_code, data


def ok(label: str, status: int, data: any) -> bool:
    if status in (200, 201, 204):
        print(f"  [OK]   {label}")
        return True
    print(f"  [FAIL] {label} — HTTP {status}: {str(data)[:200]}")
    return False


def main():
    print("=" * 65)
    print(f" SEED PROPFLOW DEMO TENANT")
    print(f" {TENANT_NAME} <{TENANT_EMAIL}>")
    print(f" ID: {TENANT_ID}")
    print("=" * 65)

    # ── Step 1: Patch public.users ────────────────────────────────────────────
    # These fields exist in users but were blank per the live fetch:
    #   first_name, last_name, phone_number, location
    # The application form pre-populates from user.full_name and user.phone_number
    # (see apply/page.tsx line: phone: user?.phone_number || "")
    # so filling them here means Step 1 of the form auto-fills correctly.
    print("\n[1/3] Patching public.users ...")
    status, data = req(
        "patch",
        f"users?id=eq.{TENANT_ID}",
        {
            "first_name":    "Akinwande",
            "last_name":     "Alexander",
            "phone_number":  "+2348012345678",
            "location":      "Lagos",
            "trust_score":   75,
        },
    )
    ok("users — first_name, last_name, phone_number, location, trust_score", status, data)

    # ── Step 2: Patch tenant_profiles ────────────────────────────────────────
    # These map to what Step 2 (Employment) of the application form sends:
    #   employment_status → applications.employment_status
    #   company_name      → applications.employer_name  (form field: employer_name)
    #   monthly_income_range is display-only; monthly_income (int) goes in applications
    #
    # We seed the profile so enrich_and_qualify can fetch a rich profile
    # when generating the landlord briefing.
    print("\n[2/3] Patching tenant_profiles ...")
    status, data = req(
        "patch",
        f"tenant_profiles?id=eq.{TENANT_ID}",
        {
            # maps to applications.employment_status
            "employment_status":        "employed",
            # maps to applications.employer_name (Step 2 form field)
            "company_name":             "Slim Media",
            # not saved to applications (no jobTitle column) but used in briefing
            "job_title":                "Creative Director",
            # display range — actual integer goes in applications.monthly_income
            "monthly_income_range":     "200k-400k",
            # proof uploaded during Step 4 as proofOfIncome file
            "income_proof_url":         "demo/income_proof.pdf",
            "income_proof_verified":    True,
            # preferred_property_types / preferred_locations used by
            # PropFlow match_properties node to rank results
            "preferred_property_types": ["flat", "self-contain"],
            "preferred_locations":      ["Lagos", "Lekki", "VI", "Yaba", "Ikeja"],
            "budget_range": {
                "min":      150000,
                "max":      500000,
                "currency": "NGN",
            },
        },
    )
    ok("tenant_profiles — employment, income, property preferences", status, data)

    # ── Step 3: Insert tenants row (currently missing entirely) ───────────────
    # The tenants table holds the budget and onboarding state.
    # The 'preferences' JSONB mirrors what the application form Step 5 collects:
    #   property_type, bedrooms, payment_frequency
    # 'documents' JSONB mirrors what Step 4 uploads (stored as named paths).
    print("\n[3/3] Inserting tenants row ...")
    tenants_body = {
        "id":                    TENANT_ID,
        "budget":                400000.00,     # matches monthly_income in applications
        "preferred_location":    "Lekki",
        "move_in_date":          "2026-08-01",  # maps to applications.move_in_date
        "onboarding_completed":  True,
        "profile_completion":    85,
        "documents": {
            # These are the same 4 upload slots from Step 4 of the application form:
            # idDocument, proofOfIncome, bankStatement, employmentLetter
            "idDocument":        "demo/nin_document.pdf",
            "proofOfIncome":     "demo/payslip.pdf",
            "bankStatement":     "demo/bank_statement.pdf",
            "employmentLetter":  "demo/offer_letter.pdf",
        },
        "preferences": {
            # Mirrors application form Step 5 + Step 2
            "property_type":      "flat",
            "bedrooms":           2,
            "lease_duration":     "12",             # applications.lease_duration
            "number_of_occupants": 1,               # applications.number_of_occupants
            "has_pets":           False,             # applications.has_pets
            "payment_frequency":  "QUARTERLY",
        },
    }
    status, data = req("post", "tenants", tenants_body)
    if status == 409:
        # Row already exists — patch instead (safe to re-run)
        status, data = req(
            "patch",
            f"tenants?id=eq.{TENANT_ID}",
            {k: v for k, v in tenants_body.items() if k != "id"},
        )
        ok("tenants (already existed — patched)", status, data)
    else:
        ok("tenants (inserted)", status, data)

    # ── Verification pass ─────────────────────────────────────────────────────
    print("\n─── Verification ─────────────────────────────────────────────")

    s, d = req("get", f"users?id=eq.{TENANT_ID}&select=full_name,first_name,phone_number,location,trust_score")
    if s == 200 and d:
        u = d[0]
        print(f"  users:           full_name={u.get('full_name')}  phone={u.get('phone_number')}  loc={u.get('location')}  trust={u.get('trust_score')}")

    s, d = req("get", f"tenant_profiles?id=eq.{TENANT_ID}&select=employment_status,job_title,company_name,monthly_income_range,income_proof_verified,budget_range")
    if s == 200 and d:
        tp = d[0]
        print(f"  tenant_profiles: {tp.get('employment_status')} at {tp.get('company_name')} ({tp.get('job_title')})")
        print(f"                   income={tp.get('monthly_income_range')}  verified={tp.get('income_proof_verified')}  budget={tp.get('budget_range')}")

    s, d = req("get", f"tenants?id=eq.{TENANT_ID}&select=budget,preferred_location,profile_completion,onboarding_completed")
    if s == 200 and d:
        t = d[0]
        print(f"  tenants:         budget=NGN {t.get('budget'):,.0f}  loc={t.get('preferred_location')}  completion={t.get('profile_completion')}%  onboarded={t.get('onboarding_completed')}")
    else:
        print("  tenants:         [NOT FOUND — insert may have failed, check error above]")

    # Check propflow migration column
    s, d = req("get", f"applications?select=landlord_briefing&limit=0")
    if s == 200:
        print("  migration 004:   [OK] applications.landlord_briefing column exists")
    else:
        print("  migration 004:   [WARN] landlord_briefing column missing — run:")
        print("                   docs/sql/migrations/004_propflow_columns.sql")

    print()
    print("=" * 65)
    print(" SEED COMPLETE")
    print("=" * 65)
    print()
    print(f"  Tenant ID:    {TENANT_ID}")
    print(f"  Name:         {TENANT_NAME}")
    print(f"  Email:        {TENANT_EMAIL}")
    print(f"  Occupation:   Creative Director at Slim Media")
    print(f"  Income:       200k–400k NGN/month")
    print(f"  Budget:       NGN 400,000/month")
    print(f"  Preferred:    Lekki, Lagos — 2-bed flat — quarterly pay")
    print()
    print("  PropFlow demo test message:")
    print('  "I need 2 bedroom flat in Lekki, max 400k per month, quarterly"')
    print()


if __name__ == "__main__":
    main()
