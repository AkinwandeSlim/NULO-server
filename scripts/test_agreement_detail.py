import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.database import supabase_admin

agreement_id = "57a6bc74-0d12-4336-830e-159ab3387dd3"

# Check agreement
r = supabase_admin.table('agreements').select('*').eq('id', agreement_id).execute()
print("Agreement:", r.data[0] if r.data else 'Not found')

# Check virtual_account_transfers
import re
uuid_match = re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", agreement_id, re.IGNORECASE)
clean_agreement_id = uuid_match.group(0) if uuid_match else agreement_id
suffixed_account_ref = f"{clean_agreement_id}-SUB"

transfers = supabase_admin.table('virtual_account_transfers').select('*').eq('account_ref', suffixed_account_ref).execute()
print(f"\nTransfers for {suffixed_account_ref}:")
print(f"Count: {len(transfers.data)}")
for t in transfers.data:
    print(f"  - {t['id']}: {t['amount_received']} ({t['reconciliation_result']})")
