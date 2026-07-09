from app.services.agreement_service import AgreementService


def test_derive_effective_status_uses_tenant_signature_when_landlord_pending():
    agreement = {
        "status": "PENDING_TENANT",
        "tenant_signed_at": "2024-01-10T10:00:00",
        "landlord_signed_at": None,
    }

    assert AgreementService.derive_effective_status(agreement) == "PENDING_LANDLORD"


def test_derive_effective_status_returns_signed_when_both_signatures_exist():
    agreement = {
        "status": "PENDING_LANDLORD",
        "tenant_signed_at": "2024-01-10T10:00:00",
        "landlord_signed_at": "2024-01-10T11:00:00",
    }

    assert AgreementService.derive_effective_status(agreement) == "SIGNED"
