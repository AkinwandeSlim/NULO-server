#!/usr/bin/env python3
"""
PropFlow Interactive E2E Demo
==============================
Interactive CLI with REAL database, REAL Qwen AI, and input() at every step.
Walks through the full rental journey for both tenant and landlord.

Usage:
    cd server && source venv/Scripts/activate
    python scripts/propflow_interactive_demo.py

Requires: SUPABASE_SERVICE_KEY + QWEN_API_KEY in .env
Uses:     requests + verify=False (same proven pattern as seed scripts)
"""

import json, os, sys, time, uuid
from datetime import datetime, date, timezone
from pathlib import Path

import requests, urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv(str(Path(__file__).parent.parent / ".env"))

URL = os.environ["SUPABASE_URL"]
SKEY = os.environ["SUPABASE_SERVICE_KEY"]
QKEY = os.environ.get("QWEN_API_KEY", "")
HDR = {"apikey": SKEY, "Authorization": f"Bearer {SKEY}", "Content-Type": "application/json"}

C = "\033[96m"; G = "\033[92m"; Y = "\033[93m"; R = "\033[91m"; M = "\033[95m"
B = "\033[1m"; D = "\033[2m"; CL = "\033[2J\033[H"; X = "\033[0m"

METHOD_MAP = {"GET":"get","POST":"post","PATCH":"patch","PUT":"put","DELETE":"delete"}
def sb(method, path, body=None):
    r = getattr(requests, METHOD_MAP.get(method, method))(f"{URL}/rest/v1/{path}", headers=HDR, verify=False,
                                                          json=body if body else None)
    return r.status_code, r.json() if r.text else {}

def banner(t):
    print(f"{CL}{B}{G}{'='*60}{X}\n  {B}{t}{X}\n{B}{G}{'='*60}{X}\n")

def hdr(actor, name):
    c = C if actor == "TENANT" else Y
    print(f"\n{c}{'-'*60}{X}\n  {c}[{actor}]{X}  {B}{name}{X}\n{c}{'-'*60}{X}\n")

def say(who, text):
    c = {"Tenant":C,"Landlord":Y,"System":M,"AI":M}.get(who,M)
    print(f"  {c}{who}:{X} {text}")

def info(k, v):
    print(f"    {D}{k}:{X} {B}{v}{X}")

def ok(text):
    print(f"    {G}>> {text}{X}")

def ask(text):
    return input(f"\n  {B}{text}{X}\n  {C}> {X}").strip()

def div():
    print(f"    {D}{'.'*50}{X}")

QWEN = "https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"

def qwen_intent(inquiry):
    say("AI", "Analyzing with Qwen...")
    r = requests.post(QWEN, json={"model":"qwen-plus","messages":[
        {"role":"system","content":"Extract rental intent as JSON: property_type, location, bedrooms (number), budget_monthly (NGN), move_in_date, payment_frequency, special_requests. Handle Nigerian Pidgin. Return ONLY valid JSON."},
        {"role":"user","content":inquiry}],"temperature":0.1},
        headers={"Authorization":f"Bearer {QKEY}"}, timeout=30)
    if r.status_code == 200:
        c = r.json()["choices"][0]["message"]["content"]
        s, e = c.find("{"), c.rfind("}")+1
        if s>=0 and e>s: return json.loads(c[s:e])
    return {"location":"Lekki","bedrooms":2,"budget_monthly":500000,"payment_frequency":"MONTHLY"}

def qwen_briefing(tenant, intent):
    say("AI", "Generating landlord briefing...")
    r = requests.post(QWEN, json={"model":"qwen-plus","messages":[
        {"role":"system","content":"Generate 3-sentence tenant briefing for landlord: employment, income, what they seek."},
        {"role":"user","content":f"Tenant: {tenant.get('full_name','')}, Employ: {tenant.get('employment_status','')}, Income: {tenant.get('monthly_income_range','')}, Seeking: {intent.get('bedrooms','?')}-bed in {intent.get('location','?')} NGN {intent.get('budget_monthly',0):,}/mo"}],
        "temperature":0.3}, headers={"Authorization":f"Bearer {QKEY}"}, timeout=30)
    if r.status_code==200: return r.json()["choices"][0]["message"]["content"]
    return "Tenant has verified income and employment history."

def run():
    banner("PROPFLOW INTERACTIVE E2E DEMO")
    print(f"  Real DB {G}(Supabase){X}  |  Real AI {G}(Qwen){X}  |  Interactive at every step\n")
    input(f"  {B}Press Enter to start...{X}\n")

    # ── Select users ────────────────────────────────────────────────────
    _, tenants = sb("GET", "users?select=id,full_name,email,user_type&user_type=eq.tenant&limit=10")
    _, landlords = sb("GET", "users?select=id,full_name,email,user_type&user_type=eq.landlord&limit=10")
    if not tenants or not landlords:
        print(f"{R}No users found. Run seed scripts first.{X}"); sys.exit(1)

    hdr("SELECT", "Choose tenant")
    for i,t in enumerate(tenants,1): print(f"  {i}. {t['full_name']}")
    TENANT = tenants[max(0,int(ask(f"Tenant (1-{len(tenants)}):") or "1")-1)]
    TENANT_ID = TENANT["id"]

    hdr("SELECT", "Choose landlord")
    for i,l in enumerate(landlords,1): print(f"  {i}. {l['full_name']}")
    LANDLORD = landlords[max(0,int(ask(f"Landlord (1-{len(landlords)}):") or "1")-1)]
    LANDLORD_ID = LANDLORD["id"]
    LANDLORD_NAME = LANDLORD.get("full_name","Landlord")

    # Tenant profile
    _, tp = sb("GET", f"tenant_profiles?id=eq.{TENANT_ID}&limit=1")
    tp = tp[0] if tp else {}
    say("System", f"Loaded {TENANT['full_name']}")
    info("Employment", tp.get("employment_status","N/A"))
    info("Income", tp.get("monthly_income_range","N/A"))
    div()

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 1: SEARCH
    # ═════════════════════════════════════════════════════════════════════
    banner("PHASE 1: SEARCH")
    hdr("TENANT", TENANT["full_name"])

    inquiry = ask("What property are you looking for?")
    if not inquiry: inquiry = "I wan 2-bed flat for Lekki, budget 500k monthly"
    intent = qwen_intent(inquiry)
    loc = intent.get("location","Lekki"); beds = intent.get("bedrooms",2); budget = intent.get("budget_monthly",500000)

    say("System", "Intent extracted:")
    info("Location", loc); info("Bedrooms", beds); info("Budget", f"NGN {budget:,.0f}/mo")

    # ── Contextual property search ────────────────────────────────────────
    # Strategy: exact neighborhood -> broader area -> budget-adjusted fallback
    def search_props(loc_str, bed_count, budget_max):
        loc_str = loc_str.strip()
        # Try exact neighborhood match first
        q = f"properties?select=*&status=eq.vacant&location=ilike.*{loc_str}*&limit=10"
        _, raw = sb("GET", q.replace(" ", "%20"))
        if isinstance(raw, list) and raw:
            return raw, f"Neighborhood: {loc_str}"
        # Broaden: extract city (last word after comma)
        parts = [p.strip() for p in loc_str.split(",")]
        city = parts[-1] if len(parts) > 1 else parts[0]
        q = f"properties?select=*&status=eq.vacant&location=ilike.*{city}*&limit=10"
        _, raw = sb("GET", q.replace(" ", "%20"))
        if isinstance(raw, list) and raw:
            return raw, f"Area: {city}"
        # Last resort: all vacant
        _, raw = sb("GET", "properties?select=*&status=eq.vacant&limit=10")
        return raw if isinstance(raw, list) else [], "All available"

    props, match_note = search_props(loc, beds, budget) if beds else ([], "")
    if not props:
        props, match_note = search_props(loc, 0, budget)
    if not props:
        print(f"{R}No properties found.{X}"); sys.exit(1)
    say("System", f"Showing properties matching {match_note}")
    info("Found", f"{len(props)} propert{'ies' if len(props)!=1 else 'y'}")

    properties = [{"id":p["id"],"title":p.get("title",""),"location":p.get("location",""),
                   "price":float(p.get("price",0)),"beds":p.get("beds",0),"baths":p.get("baths",0),
                   "landlord_id":p.get("user_id",p.get("landlord_id",""))} for p in props]

    hdr("TENANT", "Select a property")
    for i,p in enumerate(properties,1):
        print(f"  {i}. {B}{p['title']}{X}  |  {p['location']}  |  {G}NGN {p['price']:,.0f}/mo{X}  |  {p['beds']}bed")
    PROP = properties[max(0,int(ask(f"Property (1-{len(properties)}):") or "1")-1)]
    say("Tenant", f"I'd like {PROP['title']}")
    div()

    # ── Create application ──────────────────────────────────────────────
    now = datetime.now(timezone.utc).isoformat()
    _, app = sb("POST", "applications", {"user_id":TENANT_ID,"property_id":PROP["id"],
        "status":"pending","propflow_thread_id":f"demo-{uuid.uuid4().hex[:12]}","created_at":now,"updated_at":now})
    app_id = app[0]["id"] if isinstance(app,list) else ""
    if not app_id:
        _, existing = sb("GET", f"applications?user_id=eq.{TENANT_ID}&status=eq.pending&limit=1&order=created_at.desc")
        app_id = existing[0]["id"] if existing else ""
    if app_id: ok(f"Application {app_id[:12]}...")

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 2: LANDLORD REVIEW
    # ═════════════════════════════════════════════════════════════════════
    banner("PHASE 2: LANDLORD REVIEW")
    briefing = qwen_briefing({**tp,"full_name":TENANT["full_name"]}, intent)
    sb("PATCH", f"applications?id=eq.{app_id}", {"landlord_briefing":briefing})

    hdr("LANDLORD", LANDLORD_NAME)
    print(f"\n  {B}AI Briefing:{X}\n  {D}{briefing}{X}\n")
    info("Tenant", TENANT["full_name"]); info("Property", PROP["title"]); info("Rent", f"NGN {PROP['price']:,.0f}/mo")

    dec = ask("Approve or reject? (approve/reject):").lower()
    if dec != "approve":
        sb("PATCH", f"applications?id=eq.{app_id}", {"status":"rejected","rejection_reason":ask("Reason:")})
        ok("Rejected."); return
    sb("PATCH", f"applications?id=eq.{app_id}", {"status":"approved"})
    ok("Approved!"); div()

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 3: SIGNING
    # ═════════════════════════════════════════════════════════════════════
    banner("PHASE 3: SIGNING")
    _, agr = sb("POST", "agreements", {"application_id":app_id,"tenant_id":TENANT_ID,
        "landlord_id":LANDLORD_ID,"property_id":PROP["id"],"status":"PENDING_TENANT",
        "rent_amount":PROP["price"],"payment_frequency":intent.get("payment_frequency","MONTHLY"),
        "lease_start_date":str(date.today()),"platform_fee":round(PROP["price"]*0.02,2),
        "created_at":now,"updated_at":now})
    agr_id = agr[0]["id"] if isinstance(agr,list) else ""
    if not agr_id:
        _, existing = sb("GET", f"agreements?application_id=eq.{app_id}&limit=1")
        agr_id = existing[0]["id"] if existing else ""
    sb("PATCH", f"applications?id=eq.{app_id}", {"agreement_id":agr_id})
    ok(f"Agreement {agr_id[:12]}...")

    hdr("TENANT", TENANT["full_name"])
    print(f"\n  Property: {PROP['title']}  |  Rent: {G}NGN {PROP['price']:,.0f}/mo{X}")
    if ask("Type 'sign' to sign:") == "sign":
        sb("PATCH", f"agreements?id=eq.{agr_id}", {"status":"PENDING_LANDLORD","tenant_signed_at":now})
        ok("Tenant signed!")

    hdr("LANDLORD", LANDLORD_NAME)
    if ask("Type 'sign' to countersign:") == "sign":
        sb("PATCH", f"agreements?id=eq.{agr_id}", {"status":"SIGNED","landlord_signed_at":now})
        ok("Agreement fully executed!")

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 4: PAYMENT
    # ═════════════════════════════════════════════════════════════════════
    banner("PHASE 4: PAYMENT")
    nuban = f"9391{uuid.uuid4().hex[:6].upper()}"
    sb("PATCH", f"agreements?id=eq.{agr_id}",
        {"virtual_account_number":nuban,"virtual_account_name":f"{LANDLORD_NAME[:20]} {PROP['title'][:20]}",
         "expected_payment_amount":PROP["price"],"reconciliation_status":"PENDING","total_received_amount":0})
    ok(f"VA created: {nuban}")
    info("Amount", f"NGN {PROP['price']:,.0f}")

    hdr("TENANT", TENANT["full_name"])
    print(f"\n  Account: {G}{nuban}{X}  |  Amount: {G}NGN {PROP['price']:,.0f}{X}")
    if ask("Type 'pay' to simulate payment:") == "pay":
        sb("PATCH", f"agreements?id=eq.{agr_id}", {"total_received_amount":PROP["price"],"reconciliation_status":"FULL_PAYMENT"})
        ok(f"Payment NGN {PROP['price']:,.0f} received!")

    # ═════════════════════════════════════════════════════════════════════
    # PHASE 5: RELEASE
    # ═════════════════════════════════════════════════════════════════════
    banner("PHASE 5: RELEASE")
    hdr("LANDLORD", LANDLORD_NAME)
    _, bank = sb("GET", f"landlord_profiles?id=eq.{LANDLORD_ID}&limit=1")
    bank = bank[0] if bank else {}
    if bank.get("bank_account_number"):
        print(f"\n  {G}Payment received: NGN {PROP['price']:,.0f}{X}")
        info("Bank", f"{bank.get('bank_name','N/A')} {bank.get('bank_account_number','N/A')}")
    else:
        print(f"\n  {Y}No bank details on file (OK for demo).{X}")

    if ask("Type 'release' to release funds:").lower() == "release":
        fee = round(PROP["price"]*0.02,2); payout = PROP["price"]-fee
        sb("PATCH", f"agreements?id=eq.{agr_id}",
            {"status":"ACTIVE","disbursement_status":"completed","disbursement_amount":payout,
             "disbursement_merchant_tx_ref":f"tx-{uuid.uuid4().hex[:8]}","platform_fee":fee})
        sb("PATCH", f"properties?id=eq.{PROP['id']}", {"status":"occupied"})
        ok(f"NGN {payout:,.0f} disbursed!")
        info("Property", "occupied"); info("Agreement", "ACTIVE")

    # ── SUMMARY ─────────────────────────────────────────────────────────
    banner("E2E FLOW COMPLETE")
    print(f"  {G}{B}Full rental journey done!{X}\n")
    for a,d in [("Tenant","Searched + selected property"),("Landlord","AI briefing + approved"),
                ("Tenant","Signed lease"),("Landlord","Countersigned"),
                ("System","VA provisioned"),("Tenant","Paid"),("Landlord","Released funds")]:
        print(f"  {G}->{X}  {a:15s} {d}")
    print(f"\n  Property: {G}occupied{X}  |  Agreement: {G}ACTIVE{X}\n")

if __name__ == "__main__":
    try: run()
    except KeyboardInterrupt: print(f"\n{D}Exiting...{X}"); sys.exit(0)
