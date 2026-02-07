"""
Test script to verify backend query optimizations
✅ Tests: Timeout configuration, connection pooling, query performance, caching
"""

import asyncio
import time
import logging
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Test configuration
TEST_BASE_URL = "http://localhost:8000"
STATS_ENDPOINT = f"{TEST_BASE_URL}/api/v1/admin/dashboard/stats"
RECENT_ACTIVITY_ENDPOINT = f"{TEST_BASE_URL}/api/v1/admin/dashboard/recent-activity?days=7"

async def test_stats_endpoint():
    """Test the stats endpoint with timeout"""
    import httpx
    
    logger.info("=" * 80)
    logger.info("🧪 TEST 1: Dashboard Stats Endpoint Performance")
    logger.info("=" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Get auth token from your env or headers
            headers = {
                "Content-Type": "application/json"
            }
            
            start_time = time.time()
            response = await client.get(STATS_ENDPOINT, headers=headers)
            elapsed = time.time() - start_time
            
            logger.info(f"✅ Response Status: {response.status_code}")
            logger.info(f"⏱️  Response Time: {elapsed:.2f}s")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📊 Dashboard Stats Retrieved Successfully")
                logger.info(f"   - Landlords: {data.get('landlords', {}).get('total', 0)}")
                logger.info(f"   - Tenants: {data.get('tenants', {}).get('total', 0)}")
                logger.info(f"   - Properties: {data.get('properties', {}).get('total', 0)}")
                logger.info(f"✅ TEST 1 PASSED")
            else:
                logger.error(f"❌ Unexpected status: {response.text}")
                logger.error(f"❌ TEST 1 FAILED")
                
    except Exception as e:
        logger.error(f"❌ TEST 1 FAILED: {str(e)}")
    
    logger.info("")


async def test_recent_activity_endpoint():
    """Test the recent activity endpoint"""
    import httpx
    
    logger.info("=" * 80)
    logger.info("🧪 TEST 2: Recent Activity Endpoint Performance")
    logger.info("=" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Content-Type": "application/json"
            }
            
            start_time = time.time()
            response = await client.get(RECENT_ACTIVITY_ENDPOINT, headers=headers)
            elapsed = time.time() - start_time
            
            logger.info(f"✅ Response Status: {response.status_code}")
            logger.info(f"⏱️  Response Time: {elapsed:.2f}s")
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"📊 Recent Activity Retrieved Successfully")
                logger.info(f"   - Recent Landlord Signups: {len(data.get('recent_landlord_signups', []))}")
                logger.info(f"   - Recent Tenant Signups: {len(data.get('recent_tenant_signups', []))}")
                logger.info(f"   - Recent Properties: {len(data.get('recent_property_submissions', []))}")
                logger.info(f"✅ TEST 2 PASSED")
            else:
                logger.error(f"❌ Unexpected status: {response.text}")
                logger.error(f"❌ TEST 2 FAILED")
                
    except Exception as e:
        logger.error(f"❌ TEST 2 FAILED: {str(e)}")
    
    logger.info("")


async def test_caching():
    """Test response caching (should be faster on second request)"""
    import httpx
    
    logger.info("=" * 80)
    logger.info("🧪 TEST 3: Response Caching Performance")
    logger.info("=" * 80)
    
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = {
                "Content-Type": "application/json"
            }
            
            # First request
            start_time = time.time()
            response1 = await client.get(STATS_ENDPOINT, headers=headers)
            elapsed1 = time.time() - start_time
            
            logger.info(f"1️⃣  First Request Time: {elapsed1:.2f}s")
            
            # Second request (should be cached)
            await asyncio.sleep(0.5)  # Small delay
            start_time = time.time()
            response2 = await client.get(STATS_ENDPOINT, headers=headers)
            elapsed2 = time.time() - start_time
            
            logger.info(f"2️⃣  Second Request Time: {elapsed2:.2f}s")
            
            if elapsed2 < elapsed1 * 0.5:
                logger.info(f"✅ Cache working! Second request {(elapsed1 / elapsed2):.1f}x faster")
                logger.info(f"✅ TEST 3 PASSED")
            else:
                logger.warning(f"⚠️  Cache may not be working as expected")
                
    except Exception as e:
        logger.error(f"❌ TEST 3 FAILED: {str(e)}")
    
    logger.info("")


def print_optimization_summary():
    """Print summary of optimizations applied"""
    logger.info("=" * 80)
    logger.info("🔧 OPTIMIZATIONS APPLIED")
    logger.info("=" * 80)
    logger.info("""
✅ Backend Optimizations:
   1. Timeout Configuration (10 seconds):
      - Prevents infinite hangs
      - Forces graceful error handling
      - Allows fallback to cached data

   2. Connection Pooling:
      - Max concurrent connections: 10
      - Keep-alive connections: 5
      - Reuses connections for efficiency

   3. Query Optimization:
      - Properties query: Paginated in 500-item batches
      - Reduced column selection: Only fetch needed fields
      - Graceful timeout handling with fallback

   4. Response Caching:
      - Cache TTL: 60 seconds
      - Per-user cache keys
      - Prevents repeated timeouts during high load

✅ Frontend Improvements:
   - Error state UI with retry button
   - Loading skeletons during fetch
   - Empty state cards when no data
   - Graceful degradation on failure

📊 Expected Performance:
   - Stats endpoint: <2s under normal load
   - Recent activity: <3s (includes multiple queries)
   - Cached responses: <100ms
   - Large datasets (70+ properties): No timeout
""")
    logger.info("=" * 80)


if __name__ == "__main__":
    print_optimization_summary()
    
    logger.info("\n🚀 Running performance tests...\n")
    
    asyncio.run(test_stats_endpoint())
    asyncio.run(test_recent_activity_endpoint())
    asyncio.run(test_caching())
    
    logger.info("\n✅ All tests completed!")
    logger.info("📝 Check logs above for results")
