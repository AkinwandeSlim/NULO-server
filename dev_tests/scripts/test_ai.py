import asyncio
from app.services.ai.ai_service import ai_service

async def test():
    print("🤖 Testing connection...")
    await ai_service.test_connection()

    print("\n📝 Generating tenancy agreement...")
    result = await ai_service.generate_agreement(
        tenant_name="John Doe",
        landlord_name="Jane Smith",
        property_address="123 Ikoyi, Lagos",
        monthly_rent=500000
    )

    if result["success"]:
        print("✅ Agreement Generated!\n")
        print("=" * 60)
        print(result["agreement"])
        print("=" * 60)
    else:
        print(f"❌ Failed: {result['error']}")

asyncio.run(test())