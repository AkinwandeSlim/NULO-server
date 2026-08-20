# -*- coding: utf-8 -*-
"""
PropFlow Architecture + Schema Audit Script
Run: .\\venv\\Scripts\\python.exe scripts/check_propflow.py  (from server/)

Checks:
  1. graph.py  -- conditional edges, routing functions, interrupt nodes
  2. state.py  -- all required fields present
  3. nodes/    -- imports clean, DB column/value correctness
  4. services/ -- imports clean
  5. routes/   -- endpoints registered, auth import correct
  6. .env.example -- PropFlow keys documented
  7. eval_dataset -- TC-10 clarification gate, all cases have min_confidence
"""
import csv
import inspect
import os
import sys

# -- Bootstrap ----------------------------------------------------------------
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("SUPABASE_URL",        "https://placeholder.supabase.co")
os.environ.setdefault("SUPABASE_KEY",         "placeholder")
os.environ.setdefault("SUPABASE_SERVICE_KEY", "placeholder")
os.environ.setdefault("JWT_SECRET_KEY",       "placeholder")

# Windows consoles default to cp1252 and cannot print emoji/box-drawing chars —
# force UTF-8 on stdout/stderr so this script runs without PYTHONIOENCODING.
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

errors = []
passes = []


def ok(msg):
    passes.append(msg)
    print("  [OK]   " + msg)


def fail(msg):
    errors.append(msg)
    print("  [FAIL] " + msg)


# -- Load DB schema from CSV --------------------------------------------------
CSV_PATH = os.path.join(
    os.path.dirname(__file__), "..", "..", "database", "newUpadatedDB.csv"
)

_db_tables: dict = {}
try:
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["schema_name"] != "public":
                continue
            t = row["table_name"]
            _db_tables.setdefault(t, set()).add(row["column_name"])
except FileNotFoundError:
    print("  [WARN] DB CSV not found -- schema checks skipped")


def db_cols(table: str) -> set:
    return _db_tables.get(table, set())


def assert_col(table: str, col: str, ctx: str) -> None:
    if _db_tables and col not in db_cols(table):
        fail(ctx + ": column '" + col + "' NOT in " + table)
    else:
        ok(ctx + ": " + table + "." + col)


def assert_cols(table: str, cols: list, ctx: str) -> None:
    for col in cols:
        assert_col(table, col, ctx)


# =============================================================================
print("\n=== PropFlow Architecture + Schema Audit ===\n")

# -- 1. graph.py --------------------------------------------------------------
print("1. graph.py")
try:
    from app.propflow.graph import (
        get_propflow_graph,
        _route_after_intent,
        _route_after_match,
        _route_after_provision,
    )
    ok("imports cleanly")
    ok("conditional edge functions present")

    assert _route_after_intent({"current_stage": "needs_clarification"}) == "end_clarification"
    assert _route_after_intent({"current_stage": "intent_extracted"})    == "match_properties"
    assert _route_after_match({"current_stage": "no_properties_found"})  == "end_no_properties"
    assert _route_after_match({"current_stage": "property_matched"})     == "create_application"
    assert _route_after_provision({"current_stage": "dva_provisioning_failed"}) == "end_dva_failed"
    assert _route_after_provision({"current_stage": "nomba_provisioned"})       == "disburse_landlord"
    ok("all routing branches return correct destinations")
except Exception as e:
    fail("graph.py: " + str(e))

# -- 2. state.py --------------------------------------------------------------
print("\n2. state.py")
try:
    from app.propflow.state import PropFlowState
    fields = set(PropFlowState.__annotations__.keys())
    ok("PropFlowState has " + str(len(fields)) + " fields")

    required = [
        "workflow_id", "tenant_id", "current_stage", "error_log",
        "raw_inquiry_text", "extracted_intent", "extraction_confidence",
        "property_matches", "selected_property_id",
        "application_id", "application_status",
        "agreement_id", "agreement_status", "agreement_pdf_storage_key", "agreement_pdf_url",
        "nomba_account_ref", "nomba_virtual_account_number", "expected_payment_amount",
        "reconciliation_status", "disbursement_merchant_tx_ref",
        "prior_tenant_memories", "prior_landlord_memories",
        "landlord_briefing", "is_returning_tenant",
        "disbursement_amount", "platform_fee", "rejection_reason", "landlord_id",
    ]
    for field in required:
        if field in fields:
            ok("  field '" + field + "'")
        else:
            fail("  field '" + field + "' MISSING from PropFlowState")
except Exception as e:
    fail("state.py: " + str(e))

# -- 3. nodes/ ----------------------------------------------------------------
print("\n3. nodes/")
for node in [
    "extract_intent", "match_properties", "create_application",
    "enrich_qualify", "create_agreement", "provision_nomba", "disburse_landlord",
]:
    try:
        __import__("app.propflow.nodes." + node)
        ok("nodes/" + node + ".py imports")
    except Exception as e:
        fail("nodes/" + node + ".py: " + str(e))

# -- 3a. match_properties -----------------------------------------------------
print("\n3a. match_properties")
try:
    from app.propflow.nodes import match_properties
    src = inspect.getsource(match_properties._query_properties)

    assert_cols("properties",
        ["id", "title", "location", "city", "state", "price", "beds", "baths",
         "property_type", "images", "landlord_id", "payment_frequency",
         "verification_status", "status", "deleted_at"],
        "match_properties SELECT")

    if '"vacant"' in src:
        ok("match_properties: status='vacant' (matches marketplace route)")
    else:
        fail("match_properties: status value wrong -- expected 'vacant'")

    if '"approved"' in src and "verification_status" in src:
        ok("match_properties: verification_status='approved'")
    else:
        fail("match_properties: verification_status='approved' missing")

    if '"available"' in src:
        fail("match_properties: old value 'available' still present -- should be 'vacant'")
    else:
        ok("match_properties: 'available' not used")
except Exception as e:
    fail("match_properties check: " + str(e))

# -- 3b. create_application ---------------------------------------------------
print("\n3b. create_application")
try:
    assert_cols("applications",
        ["user_id", "property_id", "status", "employment_status",
         "employer_name", "monthly_income", "move_in_date", "lease_duration",
         "number_of_occupants", "has_pets", "pet_details", "message",
         "references", "documents", "emergency_contact_name",
         "emergency_contact_phone", "viewed_by_landlord", "propflow_thread_id"],
        "create_application")
    assert_cols("tenant_profiles",
        ["employment_status", "company_name", "job_title", "monthly_income_range"],
        "create_application tenant_profiles")
except Exception as e:
    fail("create_application check: " + str(e))

# -- 3c. enrich_qualify -------------------------------------------------------
print("\n3c. enrich_qualify")
try:
    from app.propflow.nodes import enrich_qualify
    src_profile = inspect.getsource(enrich_qualify._fetch_tenant_profile)
    src_prop    = inspect.getsource(enrich_qualify._fetch_property_details)

    for col in ["full_name", "email", "phone_number"]:
        if col in src_profile:
            ok("enrich_qualify: users." + col + " referenced")
        else:
            fail("enrich_qualify: users." + col + " NOT referenced")

    for col in ["employment_status", "company_name", "job_title", "monthly_income_range"]:
        if col in src_profile:
            ok("enrich_qualify: tenant_profiles." + col)
        else:
            fail("enrich_qualify: tenant_profiles." + col + " MISSING")

    # Wrong column names must not appear in .select() calls
    select_lines = [l for l in (src_profile + src_prop).splitlines() if ".select(" in l]
    select_src = " ".join(select_lines)
    for wrong in ["occupation", "employer", "monthly_income\""]:
        if wrong in select_src:
            fail("enrich_qualify: wrong DB column '" + wrong + "' in .select() call")
        else:
            ok("enrich_qualify: '" + wrong + "' not in .select()")

    if '"beds"' in src_prop:
        ok("enrich_qualify: properties.beds (correct DB column)")
    else:
        fail("enrich_qualify: 'beds' missing from _fetch_property_details")

    assert_col("applications", "landlord_briefing", "enrich_qualify briefing UPDATE")
except Exception as e:
    fail("enrich_qualify check: " + str(e))

# -- 3d. create_agreement -----------------------------------------------------
print("\n3d. create_agreement")
try:
    assert_cols("properties",
        ["id", "title", "location", "full_address", "address",
         "property_type", "price", "payment_frequency", "landlord_id"],
        "create_agreement properties SELECT")
    assert_cols("users",
        ["id", "full_name", "email", "phone_number"],
        "create_agreement users SELECT")
    assert_col("agreements", "generation_metadata", "create_agreement metadata UPDATE")
except Exception as e:
    fail("create_agreement check: " + str(e))

# -- 3e. provision_nomba ------------------------------------------------------
print("\n3e. provision_nomba")
try:
    from app.propflow.nodes import provision_nomba
    src = inspect.getsource(provision_nomba.provision_nomba_dva_node)

    assert_cols("agreements",
        ["id", "rent_amount", "payment_frequency", "lease_duration",
         "property_id", "tenant_id", "landlord_id",
         "virtual_account_number", "virtual_account_name",
         "nomba_account_ref", "expected_payment_amount"],
        "provision_nomba agreements")

    if ".upper()" in src and '"MONTHLY"' in src and '"QUARTERLY"' in src and '"ANNUAL"' in src:
        ok("provision_nomba: payment_frequency .upper() with uppercase DB values")
    else:
        fail("provision_nomba: payment_frequency comparison may use wrong case")
except Exception as e:
    fail("provision_nomba check: " + str(e))

# -- 3f. disburse_landlord ----------------------------------------------------
print("\n3f. disburse_landlord")
try:
    assert_cols("agreements",
        ["id", "rent_amount", "total_received_amount", "platform_fee",
         "landlord_id", "virtual_account_number", "nomba_account_ref",
         "disbursement_amount", "disbursement_merchant_tx_ref",
         "disbursement_status", "status"],
        "disburse_landlord agreements")
    assert_cols("landlord_profiles",
        ["bank_account_number", "bank_code", "bank_name", "account_name"],
        "disburse_landlord landlord_profiles SELECT")
    assert_cols("transactions",
        ["id", "agreement_id", "landlord_id", "amount", "currency",
         "status", "transaction_type", "payment_gateway",
         "nomba_transfer_ref", "notes"],
        "disburse_landlord transactions INSERT")
except Exception as e:
    fail("disburse_landlord check: " + str(e))

# -- 4. services/ -------------------------------------------------------------
print("\n4. services/")
for svc in ["qwen_client", "mem0_client", "supabase_storage_client"]:
    try:
        __import__("app.propflow.services." + svc)
        ok("services/" + svc + ".py")
    except Exception as e:
        fail("services/" + svc + ".py: " + str(e))

# -- 5. routes/propflow.py ----------------------------------------------------
print("\n5. routes/propflow.py")
try:
    from app.routes.propflow import router, _detect_interrupt, _INTERRUPT_NODES
    import app.routes.propflow as propflow_mod

    paths = [r.path for r in router.routes]
    ok("router: " + str(len(paths)) + " routes registered")

    for expected in [
        "/propflow/chat",
        "/propflow/resume/{thread_id}",
        "/propflow/status/{thread_id}",
        "/propflow/threads",
    ]:
        if expected in paths:
            ok("  route " + expected)
        else:
            fail("  route " + expected + " MISSING")

    if _INTERRUPT_NODES == {"create_agreement", "provision_nomba_dva"}:
        ok("_INTERRUPT_NODES = {create_agreement, provision_nomba_dva}")
    else:
        fail("_INTERRUPT_NODES wrong: " + str(_INTERRUPT_NODES))

    ok("_detect_interrupt present")

    src = inspect.getsource(propflow_mod)
    if "from app.middleware.auth import get_current_user" in src:
        ok("auth import: app.middleware.auth")
    else:
        fail("auth import should be 'from app.middleware.auth import get_current_user'")
except Exception as e:
    fail("routes/propflow.py: " + str(e))

# -- 6. .env.example ----------------------------------------------------------
print("\n6. .env.example")
try:
    env_path = os.path.join(os.path.dirname(__file__), "..", ".env.example")
    with open(env_path, encoding="utf-8") as f:
        content = f.read()
    for key in [
        "QWEN_API_KEY", "QWEN_API_URL", "QWEN_MODEL",
        "AGREEMENT_STORAGE_BUCKET",
        "MEM0_MODE", "MEM0_LOCAL_PATH",
        "ENABLE_PROPFLOW", "INTENT_CONFIDENCE_THRESHOLD",
    ]:
        if key in content:
            ok("  " + key + " documented")
        else:
            fail("  " + key + " MISSING from .env.example")
except Exception as e:
    fail(".env.example: " + str(e))

# -- 7. eval_dataset ----------------------------------------------------------
print("\n7. eval_dataset.py")
try:
    from app.propflow.tests.eval_dataset import EVAL_DATASET, BRIEFING_EVAL_CASES
    ok("eval_dataset: " + str(len(EVAL_DATASET)) + " intent + "
       + str(len(BRIEFING_EVAL_CASES)) + " briefing cases")

    tc10 = next((c for c in EVAL_DATASET if c["id"] == "TC-10"), None)
    if tc10 and tc10.get("max_confidence", 1.0) < 0.70:
        ok("TC-10 clarification gate: max_confidence < 0.70")
    else:
        fail("TC-10: max_confidence must be < 0.70 to test clarification gate")

    missing = [c["id"] for c in EVAL_DATASET if "min_confidence" not in c]
    if not missing:
        ok("All intent cases have min_confidence defined")
    else:
        fail("Cases missing min_confidence: " + str(missing))
except Exception as e:
    fail("eval_dataset: " + str(e))

# -- Summary ------------------------------------------------------------------
print("\n" + "=" * 60)
print("  Passed: " + str(len(passes)))
print("  Failed: " + str(len(errors)))
if errors:
    print("\n  FAILURES:")
    for e in errors:
        print("    X " + e)
    print()
    sys.exit(1)
else:
    print("\n  ALL CHECKS PASSED - schema + architecture aligned\n")
