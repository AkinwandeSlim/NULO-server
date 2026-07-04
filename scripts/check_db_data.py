
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

print('=== AGREEMENT ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/agreements',
    params={
        'id': 'eq.8b565c14-79f7-4b0d-b84f-19cfbb2b18e8',
        'select': '*'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)

print('\n=== LANDLORD USER ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/users',
    params={
        'id': 'eq.070671cd-a779-4997-9046-771467394f53',
        'select': '*'
    },
    headers=headers
)
print(resp.json() if resp.ok else resp.text)

print('\n=== PROPERTY ===')
resp = requests.get(
    f'{SUPABASE_URL}/rest/v1/agreements',
    params={
        'id': 'eq.8b565c14-79f7-4b0d-b84f-19cfbb2b18e8',
        'select': 'property_id'
    },
    headers=headers
)
agreement = resp.json()[0]
if agreement.get('property_id'):
    resp = requests.get(
        f'{SUPABASE_URL}/rest/v1/properties',
        params={
            'id': f'eq.{agreement["property_id"]}',
            'select': 'title'
        },
        headers=headers
    )
    print(resp.json() if resp.ok else resp.text)
