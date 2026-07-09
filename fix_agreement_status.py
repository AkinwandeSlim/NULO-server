"""
Quick script to fix agreement statuses where tenant has signed but status is still PENDING_TENANT
Run this from the server directory: python fix_agreement_status.py
"""

import sys
import os

# Add server to path
sys.path.insert(0, os.path.dirname(__file__))

from app.database import supabase_admin
from app.services.agreement_service import AgreementService
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def fix_agreement_statuses():
    """Normalize stale agreement statuses from signature timestamps."""

    result = supabase_admin.table('agreements').select('*').execute()

    fixed_count = 0

    for agr in result.data:
        expected_status = AgreementService.derive_effective_status(agr)
        current_status = str(agr.get('status') or '').upper()

        if current_status != expected_status:
            logger.info(
                "Fixing agreement %s: status %s -> %s | tenant_signed=%s landlord_signed=%s",
                agr['id'],
                current_status or 'None',
                expected_status,
                bool(agr.get('tenant_signed_at')),
                bool(agr.get('landlord_signed_at')),
            )

            update_result = supabase_admin.table('agreements').update({
                'status': expected_status
            }).eq('id', agr['id']).execute()

            if update_result.data:
                logger.info('  ✅ Updated successfully')
                fixed_count += 1
            else:
                logger.error('  ❌ Failed to update')

    logger.info(f"\nTotal agreements fixed: {fixed_count}")
    return fixed_count


if __name__ == '__main__':
    fix_agreement_statuses()
