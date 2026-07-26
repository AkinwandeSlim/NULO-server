"""
Schema audit: extract exact columns and CHECK constraints from the DB CSV
and cross-reference against PropFlow node code.
Run: python scripts/schema_audit.py  (from server/ directory)
"""
import csv
import os
import sys

CSV_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "database", "newUpadatedDB.csv")

tables = {}
with open(CSV_PATH, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        if row["schema_name"] != "public":
            continue
        t = row["table_name"]
        if t not in tables:
            tables[t] = []
        tables[t].append(
            (row["column_name"], row["data_type"], row["constraint_type"], row["constraint_name"])
        )

TARGET_TABLES = [
    "properties", "applications", "agreements",
    "transactions", "tenant_profiles", "landlord_profiles", "users",
]

print("\n" + "=" * 70)
print("  DB SCHEMA AUDIT FOR PROPFLOW NODES")
print("=" * 70)

for t in TARGET_TABLES:
    rows = tables.get(t, [])
    # Deduplicate column names (same col can appear multiple times for FK/idx)
    seen = set()
    cols = []
    for r in rows:
        if r[0] not in seen:
            seen.add(r[0])
            cols.append(r)

    check_rows = [(c[0], c[3]) for c in rows if c[2] == "c"]
    # Deduplicate checks
    seen_checks = set()
    checks = []
    for c in check_rows:
        if c not in seen_checks:
            seen_checks.add(c)
            checks.append(c)

    col_names = sorted(c[0] for c in cols)
    print(f"\n{'─'*70}")
    print(f"  TABLE: {t}  ({len(col_names)} columns)")
    print(f"{'─'*70}")
    print("  COLUMNS:")
    for c in col_names:
        print(f"    {c}")
    if checks:
        print("  CHECK CONSTRAINTS:")
        for col, cname in checks:
            print(f"    {col}  =>  {cname}")

print("\n" + "=" * 70)
print("  PROPFLOW NODE CROSS-REFERENCE")
print("=" * 70)

findings = []

# ── 1. match_properties ───────────────────────────────────────────────────────
props_cols = {c[0] for c in tables.get("properties", [])}
prop_status_checks = [c for c in tables.get("properties", []) if c[0] == "status" and c[2] == "c"]
prop_vstatus_checks = [c for c in tables.get("properties", []) if c[0] == "verification_status" and c[2] == "c"]

print("\n[match_properties.py]")
# status filter
if "status" in props_cols:
    print(f"  properties.status      EXISTS  — CHECK: {[c[3] for c in prop_status_checks]}")
    # Code uses .eq("status", "available") — check if 'available' is in schema
    # The CHECK constraint name tells us allowed values
    status_cname = [c[3] for c in prop_status_checks]
    print(f"  Code uses: status='available'")
    # Check the constraint name for allowed values
    if any("available" in c.lower() for c in status_cname):
        print(f"  ✓ 'available' appears valid based on constraint name")
    else:
        findings.append("FAIL match_properties: status='available' — constraint name suggests different values")
        print(f"  ✗ ISSUE: constraint name {status_cname} does NOT contain 'available'")
else:
    findings.append("FAIL match_properties: properties.status column not found")

if "verification_status" in props_cols:
    vstatus_cname = [c[3] for c in prop_vstatus_checks]
    print(f"  properties.verification_status  EXISTS — CHECK: {vstatus_cname}")
    print(f"  Code uses: verification_status='approved'")
    if any("approved" in c.lower() for c in vstatus_cname):
        print(f"  ✓ 'approved' appears valid based on constraint name")
    else:
        findings.append("FAIL match_properties: verification_status='approved' — check constraint name")
        print(f"  ✗ ISSUE: constraint {vstatus_cname} may not allow 'approved'")

for col in ["id", "title", "location", "city", "state", "price", "beds",
            "baths", "property_type", "images", "landlord_id", "payment_frequency",
            "verification_status", "status", "deleted_at"]:
    if col in props_cols:
        print(f"  SELECT col '{col}' ✓")
    else:
        findings.append(f"FAIL match_properties: SELECT column '{col}' NOT in properties")
        print(f"  SELECT col '{col}' ✗ MISSING")

# ── 2. create_application ────────────────────────────────────────────────────
app_cols = {c[0] for c in tables.get("applications", [])}
print("\n[create_application.py]")

code_inserts = [
    "user_id", "property_id", "status", "employment_status",
    "employer_name", "monthly_income", "move_in_date", "lease_duration",
    "number_of_occupants", "has_pets", "pet_details", "message",
    "references", "documents", "emergency_contact_name",
    "emergency_contact_phone", "viewed_by_landlord",
]
for col in code_inserts:
    if col in app_cols:
        print(f"  INSERT col '{col}' ✓")
    else:
        findings.append(f"FAIL create_application: INSERT column '{col}' NOT in applications")
        print(f"  INSERT col '{col}' ✗ MISSING")

app_status_checks = [c for c in tables.get("applications", []) if c[0] == "status" and c[2] == "c"]
print(f"  applications.status CHECK: {[c[3] for c in app_status_checks]}")

# ── 3. disburse_landlord ──────────────────────────────────────────────────────
tx_cols = {c[0] for c in tables.get("transactions", [])}
agr_cols = {c[0] for c in tables.get("agreements", [])}
lp_cols = {c[0] for c in tables.get("landlord_profiles", [])}

print("\n[disburse_landlord.py]")

# transactions INSERT
tx_inserts = [
    "id", "agreement_id", "landlord_id", "amount", "currency",
    "status", "transaction_type", "payment_gateway", "nomba_transfer_ref", "notes",
]
for col in tx_inserts:
    if col in tx_cols:
        print(f"  transactions INSERT col '{col}' ✓")
    else:
        findings.append(f"FAIL disburse_landlord: transactions INSERT col '{col}' NOT in transactions")
        print(f"  transactions INSERT col '{col}' ✗ MISSING")

# agreements UPDATE
agr_updates = [
    "disbursement_amount", "disbursement_merchant_tx_ref",
    "disbursement_status", "platform_fee", "status",
]
for col in agr_updates:
    if col in agr_cols:
        print(f"  agreements UPDATE col '{col}' ✓")
    else:
        findings.append(f"FAIL disburse_landlord: agreements UPDATE col '{col}' NOT in agreements")
        print(f"  agreements UPDATE col '{col}' ✗ MISSING")

# landlord_profiles SELECT
lp_selects = ["bank_account_number", "bank_code", "bank_name", "account_name"]
for col in lp_selects:
    if col in lp_cols:
        print(f"  landlord_profiles SELECT col '{col}' ✓")
    else:
        findings.append(f"FAIL disburse_landlord: landlord_profiles SELECT col '{col}' NOT in landlord_profiles")
        print(f"  landlord_profiles SELECT col '{col}' ✗ MISSING")

# ── 4. provision_nomba ────────────────────────────────────────────────────────
print("\n[provision_nomba.py]")
provision_agr_selects = [
    "id", "rent_amount", "payment_frequency", "lease_duration",
    "property_id", "tenant_id", "landlord_id",
]
provision_agr_updates = [
    "virtual_account_number", "virtual_account_name",
    "nomba_account_ref", "expected_payment_amount",
]
for col in provision_agr_selects + provision_agr_updates:
    if col in agr_cols:
        print(f"  agreements col '{col}' ✓")
    else:
        findings.append(f"FAIL provision_nomba: agreements col '{col}' NOT in agreements")
        print(f"  agreements col '{col}' ✗ MISSING")

# ── 5. create_agreement ───────────────────────────────────────────────────────
print("\n[create_agreement.py]")
prop_selects_ca = [
    "id", "title", "location", "full_address", "address",
    "property_type", "price", "payment_frequency", "landlord_id",
]
for col in prop_selects_ca:
    if col in props_cols:
        print(f"  properties SELECT col '{col}' ✓")
    else:
        findings.append(f"FAIL create_agreement: properties SELECT col '{col}' NOT in properties")
        print(f"  properties SELECT col '{col}' ✗ MISSING")

users_cols = {c[0] for c in tables.get("users", [])}
user_selects = ["id", "full_name", "email", "phone_number"]
for col in user_selects:
    if col in users_cols:
        print(f"  users SELECT col '{col}' ✓")
    else:
        findings.append(f"FAIL create_agreement: users SELECT col '{col}' NOT in users")
        print(f"  users SELECT col '{col}' ✗ MISSING")

# ── Summary ───────────────────────────────────────────────────────────────────
print("\n" + "=" * 70)
if findings:
    print(f"  SCHEMA ISSUES FOUND: {len(findings)}")
    for f in findings:
        print(f"    ✗ {f}")
else:
    print("  ALL COLUMN/TABLE REFERENCES ARE VALID")
print("=" * 70 + "\n")
