import os
import requests
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv('SUPABASE_URL')
SUPABASE_KEY = os.getenv('SUPABASE_SERVICE_KEY') or os.getenv('SUPABASE_SERVICE_ROLE_KEY')

headers = {
    'apikey': SUPABASE_KEY,
    'Authorization': f'Bearer {SUPABASE_KEY}'
}

AGREEMENT_ID = '57a6bc74-0d12-4336-830e-159ab3387dd3'
LANDLORD_ID = '070671cd-a779-4997-9046-771467394f53'

print('=== AGREEMENT ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/agreements',
    params={
        'id': f'eq.{AGREEMENT_ID}',
        'select': '*'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)

print('\n=== LANDLORD PROFILES (bank details) ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/landlord_profiles',
    params={
        'id': f'eq.{LANDLORD_ID}',
        'select': '*'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)

print('\n=== VIRTUAL ACCOUNT TRANSFERS (FULL_PAYMENT) ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/virtual_account_transfers',
    params={
        'agreement_id': f'eq.{AGREEMENT_ID}',
        'reconciliation_result': 'eq.FULL_PAYMENT',
        'select': '*',
        'order': 'created_at.desc',
        'limit': '1'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)

print('\n=== TRANSACTIONS (disbursements) ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/transactions',
    params={
        'agreement_id': f'eq.{AGREEMENT_ID}',
        'transaction_type': 'eq.nomba_disbursement',
        'select': '*',
        'order': 'created_at.desc',
        'limit': '5'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)
