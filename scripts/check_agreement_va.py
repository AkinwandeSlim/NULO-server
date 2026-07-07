import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from dotenv import load_dotenv
load_dotenv()

from app.database import supabase_admin

agreement_id = "57a6bc74-0d12-4336-830e-159ab3387dd3"
r = supabase_admin.table('agreements').select('id,nomba_account_ref,virtual_account_number,virtual_account_name').eq('id', agreement_id).execute()
print(r.data if r.data else 'No data')
