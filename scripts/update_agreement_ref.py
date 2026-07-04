"""
Update agreement.nomba_account_ref to match the sub-account VA we created.
This fixes the reconciliation for VA 3783622764 (accountRef ends in -SUB).
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv()

from app.database import supabase_admin

async def main():
    agreement_id = "8b565c14-79f7-4b0d-b84f-19cfbb2b18e8"
    new_ref = f"{agreement_id}-SUB"

    print(f"Updating agreement {agreement_id}")
    print(f"Setting nomba_account_ref to: {new_ref}")

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: supabase_admin
            .table("agreements")
            .update({"nomba_account_ref": new_ref})
            .eq("id", agreement_id)
            .execute(),
    )

    print(f"Done. Result: {result.data}")

if __name__ == "__main__":
    asyncio.run(main())