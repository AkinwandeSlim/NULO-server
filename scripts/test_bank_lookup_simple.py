"""
Simple test for bank code derivation (no app imports required)
"""

# Nigerian bank codes mapping (copied from landlord_onboarding.py)
NIGERIAN_BANK_CODES = {
    "access bank": "044",
    "access bank plc": "044",
    "citibank": "023",
    "citibank nigeria": "023",
    "diamond bank": "063",
    "ecobank": "050",
    "ecobank nigeria": "050",
    "fidelity bank": "070",
    "fidelity bank plc": "070",
    "first bank": "011",
    "first bank of nigeria": "011",
    "first city monument bank": "214",
    "fcmb": "214",
    "guaranty trust bank": "058",
    "gtbank": "058",
    "gtco": "058",
    "heritage bank": "030",
    "jaiz bank": "301",
    "keystone bank": "082",
    "kuda bank": "50211",
    "polaris bank": "076",
    "providus bank": "101",
    "providus": "101",
    "rand merchant bank": "50201",
    "stanbic ibtc": "221",
    "stanbic ibtc bank": "221",
    "standard chartered": "068",
    "sterling bank": "232",
    "suntrust bank": "100",
    "titan trust bank": "102",
    "union bank": "033",
    "union bank of nigeria": "033",
    "united bank for africa": "033",
    "uba": "033",
    "unity bank": "215",
    "wema bank": "035",
    "zenith bank": "057",
    "zenith bank plc": "057",
}

def derive_bank_code(bank_name: str):
    """Derive Nomba bank code from bank name"""
    if not bank_name:
        return None
    
    normalized = bank_name.lower().strip()
    
    if normalized in NIGERIAN_BANK_CODES:
        return NIGERIAN_BANK_CODES[normalized]
    
    for bank, code in NIGERIAN_BANK_CODES.items():
        if bank in normalized or normalized in bank:
            return code
    
    return None

def test_bank_code_derivation():
    """Test bank code derivation"""
    print("=" * 60)
    print("BANK CODE DERIVATION TEST")
    print("=" * 60)
    
    test_cases = [
        ("Providus Bank", "101"),
        ("Providus", "101"),
        ("United Bank for Africa", "033"),
        ("UBA", "033"),
        ("Guaranty Trust Bank", "058"),
        ("GTBank", "058"),
        ("Zenith Bank", "057"),
        ("Access Bank", "044"),
        ("First Bank", "011"),
        ("Ecobank", "050"),
        ("Wema Bank", "035"),
        ("Kuda Bank", "50211"),
    ]
    
    passed = 0
    failed = 0
    
    for bank_name, expected_code in test_cases:
        result = derive_bank_code(bank_name)
        status = "✅" if result == expected_code else "❌"
        print(f"{status} {bank_name:30s} -> {result or 'None':5s} (expected {expected_code})")
        if result == expected_code:
            passed += 1
        else:
            failed += 1
    
    print(f"\nResult: {passed}/{len(test_cases)} passed")
    return failed == 0

def main():
    print("Nolo Africa - Bank Code Test")
    print("=" * 60)
    
    if test_bank_code_derivation():
        print("\n✅ All bank code derivations working correctly")
        print("\nDemo Account Details:")
        print("  Account: 1309895270")
        print("  Bank: Providus Bank")
        print("  Bank Code: 101")
        print("  Account Name: Nolo Africa Innovations Ltd")
        return 0
    else:
        print("\n❌ Some bank code derivations failed")
        return 1

if __name__ == "__main__":
    import sys
    sys.exit(main())
