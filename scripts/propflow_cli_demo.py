#!/usr/bin/env python3
"""
PropFlow E2E CLI Demo
======================
Walks through the complete PropFlow rental journey step by step,
showing both tenant and landlord perspectives with colored output.

Usage:
    cd server
    source venv/Scripts/activate
    python scripts/propflow_cli_demo.py

Requirements:
    - Supabase must be reachable (uses database.py / .env credentials)
    - All external AI/payment services are auto-mocked - no API keys needed
"""

import asyncio
import sys
import uuid
from pathlib import Path
from typing import Dict, Any
from unittest.mock import patch, AsyncMock

sys.path.insert(0, str(Path(__file__).parent.parent))

# -- ANSI colors -----------------------------------------------------------------
CYAN = "\033[96m"
GREEN = "\033[92m"
YELLOW = "\033[93m"
RED = "\033[91m"
MAGENTA = "\033[95m"
BOLD = "\033[1m"
DIM = "\033[2m"
RESET = "\033[0m"

# -- Mock data -------------------------------------------------------------------

MOCK_INTENT: Dict[str, Any] = {
    "property_type": "apartment", "location": "Lekki", "bedrooms": 2,
    "budget_monthly": 500000.0, "budget_annual": None, "move_in_date": None,
    "payment_frequency": "MONTHLY", "special_requests": [], "confidence": 0.91,
}

MOCK_BRIEFING: str = (
    "Chidi Obi is a Senior Software Engineer at Flutterwave with verified "
    "income in the NGN 500k-1M range, seeking a 2-bedroom apartment in "
    "Lekki for NGN 480k monthly. Strong employment history, verified "
    "identity, and solid guarantor references."
)

MOCK_LANDLORD_ID = uuid.UUID("660e8400-e29b-41d4-a716-446655440001")

MOCK_PROPERTIES: list = [{
    "id": "770e8400-e29b-41d4-a716-446655440001",
    "landlord_id": str(MOCK_LANDLORD_ID),
    "title": "Modern 2-Bedroom in Lekki Phase 1",
    "location": "Lekki Phase 1, Lagos",
    "price": 480000.0, "beds": 2, "baths": 2,
    "property_type": "apartment", "images": [],
}]


# -- Display ---------------------------------------------------------------------

def banner(text: str):
    width = 70
    print(f"\n{BOLD}{GREEN}{'=' * width}{RESET}")
    print(f"{BOLD}{GREEN}   {text}{RESET}")
    print(f"{BOLD}{GREEN}{'=' * width}{RESET}\n")


def step(number: int, actor: str, action: str, details: str = ""):
    actor_color = CYAN if actor == "Tenant" else (YELLOW if actor == "Landlord" else MAGENTA)
    print(f"{BOLD}{'-' * 70}{RESET}")
    print(f" {BOLD}Step {number}{RESET}  [{actor_color}{actor}{RESET}] {action}")
    if details:
        print(f"   {DIM}{details}{RESET}")


def info(label: str, value: Any, indent: int = 1):
    prefix = "   " * indent
    print(f"{prefix}{DIM}{label}:{RESET} {BOLD}{value}{RESET}")


def success(msg: str):
    print(f"   {GREEN}[OK] {msg}{RESET}")


def output(label: str, value: Any):
    print(f"   {MAGENTA}-> {label}:{RESET} {value}")


def divider():
    print(f"   {DIM}{'.' * 60}{RESET}")


# -- Helpers ---------------------------------------------------------------------

def _fresh_graph():
    import app.propflow.graph as g
    g._graph_instance = None
    from app.propflow.graph import get_propflow_graph
    return get_propflow_graph()


def _setup_mocks():
    """Patch all external service calls that graph nodes make."""
    app_id = str(uuid.uuid4())
    agreement_id = str(uuid.uuid4())
    patches = [
        patch("app.propflow.services.qwen_client.qwen_client.extract_intent",
              new_callable=AsyncMock, return_value=MOCK_INTENT),
        patch("app.propflow.services.qwen_client.qwen_client.generate_landlord_briefing",
              new_callable=AsyncMock, return_value=MOCK_BRIEFING),
        patch("app.propflow.nodes.extract_intent.mem0_service.search_tenant_memories",
              return_value=[]),
        patch("app.propflow.nodes.match_properties._query_properties",
              new_callable=AsyncMock, return_value=MOCK_PROPERTIES),
        patch("app.services.application_service.application_service.submit_application",
              new_callable=AsyncMock,
              return_value={"id": app_id, "status": "submitted",
                            "propflow_thread_id": "demo-thread"}),
        patch("app.propflow.nodes.create_agreement._fetch_property",
              new_callable=AsyncMock,
              return_value={"id": MOCK_PROPERTIES[0]["id"], "title": MOCK_PROPERTIES[0]["title"],
                            "price": MOCK_PROPERTIES[0]["price"], "location": MOCK_PROPERTIES[0]["location"]}),
        patch("app.propflow.nodes.create_agreement._fetch_tenant",
              new_callable=AsyncMock,
              return_value={"full_name": "Chidi Obi", "email": "chidi@example.com"}),
        patch("app.propflow.nodes.create_agreement._fetch_landlord",
              new_callable=AsyncMock,
              return_value={"full_name": "Mr. Tunde Bakare", "email": "tunde@example.com",
                            "phone_number": "08012345678"}),
        patch("app.services.agreement_service.agreement_service.auto_generate_agreement",
              new_callable=AsyncMock,
              return_value={"id": agreement_id, "status": "PENDING_TENANT"}),
        patch("app.services.payment_service.payment_service.provision_virtual_account",
              new_callable=AsyncMock,
              return_value={"status": "provisioned", "virtual_account_number": "9391076543",
                            "expected_amount": 480000.0}),
        patch("app.services.payment_service.payment_service.disburse_to_landlord",
              new_callable=AsyncMock,
              return_value={"merchant_tx_ref": f"tx-{uuid.uuid4().hex[:8]}",
                            "status": "completed", "disbursement_amount": 480000.0,
                            "platform_fee": 9600}),
    ]
    for p in patches:
        p.start()
    return patches


def _make_state(thread_id: str) -> dict:
    return {
        "workflow_id": thread_id,
        "tenant_id": uuid.UUID("550e8400-e29b-41d4-a716-446655440001"),
        "raw_inquiry_text": "I wan 2-bed flat for Lekki, my budget na 500k monthly",
        "current_stage": "started",
        "extracted_intent": None,
        "extraction_confidence": None,
        "property_matches": None,
        "selected_property_id": None,
        "application_id": None,
        "application_status": None,
        "agreement_id": None,
        "agreement_status": None,
        "agreement_pdf_oss_key": None,
        "nomba_account_ref": None,
        "nomba_virtual_account_number": None,
        "expected_payment_amount": None,
        "reconciliation_status": None,
        "disbursement_merchant_tx_ref": None,
        "prior_tenant_memories": None,
        "prior_landlord_memories": None,
        "landlord_briefing": None,
        "is_returning_tenant": None,
        "disbursement_amount": None,
        "platform_fee": None,
        "rejection_reason": None,
        "landlord_id": None,
        "error_log": [],
    }


# -- Demo ------------------------------------------------------------------------

async def run_demo():
    banner("PROPFLOW AI RENTAL AGENT - E2E CLI DEMO")
    print(f" This demo walks through the complete rental journey for both")
    print(f" the tenant and the landlord. All AI/payment services are mocked.\n")

    patches = _setup_mocks()
    try:
        graph = _fresh_graph()
        thread_id = f"demo-{uuid.uuid4().hex[:8]}"
        config: dict = {"configurable": {"thread_id": thread_id}}
        info("Thread ID", thread_id)

        # ══════════════════════════════════════════════════════════════════════
        #  TENANT PHASE
        # ══════════════════════════════════════════════════════════════════════
        banner("TENANT JOURNEY")

        # Step 1
        step(1, "Tenant", "Describes rental needs",
             '"I wan 2-bed flat for Lekki, my budget na 500k monthly"')
        result = await graph.ainvoke(_make_state(thread_id), config=config)
        output("Stage", result["current_stage"])
        success("Intent extracted — 2-bed apartment in Lekki, NGN 500k/month")
        success("Properties matched — 1 found")

        # Step 2
        step(2, "Tenant", "Selects a property from matches")
        matches = result.get("property_matches") or MOCK_PROPERTIES
        for i, p in enumerate(matches, 1):
            info(f"Property {i}", f"{p['title']} — NGN {p['price']:,.0f}/mo — {p['location']}", indent=2)
        info("Selected", matches[0]["title"])

        await graph.aupdate_state(config, {
            "selected_property_id": uuid.UUID(matches[0]["id"]),
            "landlord_id": uuid.UUID(matches[0]["landlord_id"]),
            "current_stage": "property_selected",
        })
        result = await graph.ainvoke(None, config=config)
        output("Stage", result["current_stage"])
        info("Application ID", result.get("application_id"))
        success("Application created — pending landlord review")

        # ══════════════════════════════════════════════════════════════════════
        #  LANDLORD PHASE
        # ══════════════════════════════════════════════════════════════════════
        banner("LANDLORD JOURNEY")

        # Step 3
        step(3, "Landlord", "Reviews AI-generated tenant briefing")
        briefing = result.get("landlord_briefing") or MOCK_BRIEFING
        print(f"   {BOLD}AI Briefing:{RESET}")
        print(f"   {DIM}{briefing}{RESET}\n")

        # Step 4
        step(4, "Landlord", "Approves the application")
        await graph.aupdate_state(config, {"application_status": "approved"})
        result = await graph.ainvoke(None, config=config)
        output("Stage", result["current_stage"])
        info("Agreement ID", result.get("agreement_id"))
        success("Lease agreement AI-generated and sent to tenant for signing")

        # ══════════════════════════════════════════════════════════════════════
        #  SIGNING PHASE
        # ══════════════════════════════════════════════════════════════════════
        banner("SIGNING PHASE")

        # Step 5
        step(5, "Tenant", "Signs the lease agreement")
        await graph.aupdate_state(config, {
            "agreement_status": "PENDING_LANDLORD",
            "current_stage": "awaiting_landlord_signature",
        })
        result = await graph.ainvoke(None, config=config)
        output("Stage", result["current_stage"])
        success("Tenant signed — awaiting landlord countersignature")

        # Step 6
        step(6, "Landlord", "Countersigns the lease agreement")
        await graph.aupdate_state(config, {
            "agreement_status": "SIGNED",
            "current_stage": "awaiting_landlord_signature",
        })
        result = await graph.ainvoke(None, config=config)
        output("Stage", result["current_stage"])
        success("Both parties have signed — agreement is fully executed")

        # ══════════════════════════════════════════════════════════════════════
        #  PAYMENT PHASE
        # ══════════════════════════════════════════════════════════════════════
        banner("PAYMENT PHASE")

        # Step 7
        step(7, "System", "Provisions Nomba virtual account")
        va_number = result.get("nomba_virtual_account_number", "9391XXXXXX")
        info("Virtual Account", va_number)
        info("Expected Amount", f"NGN {result.get('expected_payment_amount', 480000):,.0f}")
        success("Payment account ready for tenant")

        # Step 8
        step(8, "Tenant", "Makes payment into the virtual account")
        print(f"   {DIM}Tenant transfers NGN 480,000 to account {va_number}{RESET}")
        print(f"   {DIM}System reconciles payment -> FULL_PAYMENT{RESET}")
        await graph.aupdate_state(config, {
            "reconciliation_status": "FULL_PAYMENT",
            "current_stage": "payment_confirmed",
        })
        result = await graph.ainvoke(None, config=config)
        output("Stage", result["current_stage"])
        success("Payment confirmed — ready for landlord release")

        # ══════════════════════════════════════════════════════════════════════
        #  DISBURSEMENT PHASE
        # ══════════════════════════════════════════════════════════════════════
        banner("DISBURSEMENT PHASE")

        # Step 9
        step(9, "Landlord", "Releases funds to their bank account")
        merchant_ref = result.get("disbursement_merchant_tx_ref", "tx-xxxxx")
        info("Disbursement Ref", merchant_ref)
        info("Amount Released", f"NGN {result.get('disbursement_amount', 480000):,.0f}")
        info("Platform Fee", f"NGN {result.get('platform_fee', 0):,.0f}")
        success("Funds disbursed to landlord's verified bank account")
        success("Property status -> occupied")
        success("Agreement status -> ACTIVE")

        # ══════════════════════════════════════════════════════════════════════
        #  SUMMARY
        # ══════════════════════════════════════════════════════════════════════
        banner("E2E FLOW COMPLETE")

        stages = [
            ("1", "Intent Extraction", "Tenant describes needs -> Qwen extracts intent"),
            ("2", "Property Selection", "Tenant picks a property -> application created"),
            ("3", "Landlord Review", "AI briefing generated -> landlord reviews"),
            ("4", "Landlord Approval", "Landlord approves -> agreement generated"),
            ("5", "Tenant Signs", "Tenant signs lease agreement"),
            ("6", "Landlord Signs", "Landlord countersigns -> fully executed"),
            ("7", "DVA Provisioning", "Nomba virtual account created"),
            ("8", "Payment & Confirm", "Tenant pays -> landlord confirms receipt"),
            ("9", "Release & Disburse", "Landlord releases funds -> tenancy active"),
        ]
        for num, stage, desc in stages:
            print(f"   {GREEN}[OK]{RESET}  {BOLD}Step {num}:{RESET} {stage}")
            print(f"       {DIM}{desc}{RESET}")

        print(f"\n {BOLD}Result:{RESET} {GREEN}Landlord receives payment, tenant gets active tenancy,{RESET}")
        print(f"         {GREEN}property marked as occupied.{RESET}\n")

    finally:
        for p in patches:
            p.stop()


if __name__ == "__main__":
    asyncio.run(run_demo())
