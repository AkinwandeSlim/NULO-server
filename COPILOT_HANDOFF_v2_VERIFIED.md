# Copilot Handoff v2 — Landlord Dashboard Data Fix
**Project:** NuloAfrica — Zero agency-fee rental platform (Lagos / Abuja / Port Harcourt)  
**Stack:** Next.js 14 (App Router) + TypeScript / FastAPI (Python) / Supabase (PostgreSQL)  
**Scope:** Fix landlord dashboard data flickering, zero-value stat cards, missing data  
**Files to edit:** `landlord_dashboard.py` · `page.tsx` (landlord dashboard overview)  
**Files NOT to change:** `DashboardContext.tsx` · `payments.ts` · `dashboardCache.ts`

---

## CRITICAL — Read Before Writing Any Code

These rules are derived from the live DB schema and the project architecture guide.
Breaking any of these will cause silent query failures or runtime errors.

| # | Rule |
|---|------|
| 1 | **`applications` has NO `landlord_id` column.** To get a landlord's applications, first get their `property_ids`, then query `applications` with `.in_("property_id", property_ids)`. Tenant FK is `user_id`, never `tenant_id`. |
| 2 | **`agreements` field names.** In the DB: `rent_amount` (not `monthly_rent`), `lease_start_date` (not `start_date`), `lease_end_date` (not `end_date`). |
| 3 | **`viewing_requests.viewing_type`** is stored UPPERCASE: `PHYSICAL`, `VIRTUAL`, `LIVE_VIDEO` — never lowercase. |
| 4 | **`viewing_requests.status`** — only 4 valid values: `pending`, `confirmed`, `cancelled`, `completed`. Never use `rejected`. |
| 5 | **Shared PK pattern.** `landlord_profiles.id = users.id`. Query `landlord_profiles` with `.eq("id", landlord_id)`, never `.eq("user_id", landlord_id)`. |
| 6 | **Always `supabase_admin`** (service role) for all backend queries, never anon key. |
| 7 | **No Unicode in Python files** — ASCII comments only. No arrows (`->`), em-dashes, or curly quotes in `.py` files. |
| 8 | **All sync Supabase calls inside `async` FastAPI routes must use `run_in_executor`** — already handled by the thread pool pattern used in this file. |
| 9 | **Payments table is named `transactions`** (not `payments`) in the DB. The frontend `paymentsAPI` calls `/api/v1/payments/received` which maps to the `transactions` table on the backend. Do not rename anything. |

---

## Context & Root Cause

The landlord dashboard currently fires **6 separate API calls** when the page loads:

1. `DashboardContext` → `GET /api/v1/landlord/dashboard` (main call — returns profile, stats, properties, activity, notifications)
2. `page.tsx` → separate viewings API call
3. `page.tsx` → separate applications API call
4. `page.tsx` → separate agreements API call
5. `page.tsx` → separate engagement metrics API call
6. `page.tsx` → `GET /api/v1/payments/received`

The main spinner hides after call #1 completes. Calls #2–#6 haven't finished yet, so **all their stat cards flash zero** then snap to real values seconds later.

**Fix strategy:**
- Bundle calls #2, #3, #4 into the `/dashboard` backend response (fast Supabase queries, run in the existing thread pool)
- Remove those 3 calls from the frontend — read directly from `landlordData`
- Keep call #6 (payments) separate — it is a separate service
- Hold the full-page spinner until payments also resolves
- Fix payments response shape normalisation (currently ignores `{ payments: [...] }` wrapper)
- Add `total_conversations` to stats so the Messages card shows real data

---

## FILE 1 — `landlord_dashboard.py`

### Change 1a — Add `total_conversations` to `LandlordStats` Pydantic model

Find this class (around line 49):
```python
class LandlordStats(BaseModel):
    total_properties: int
    active_listings: int
    pending_viewings: int
    unread_messages: int
    total_views: int
    occupancy_rate: float
    monthly_revenue: float
    avg_response_time: str
    applications_pending: int
    applications_approved: int
    properties_vacant: int
    properties_occupied: int
```

Replace with:
```python
class LandlordStats(BaseModel):
    total_properties: int
    active_listings: int
    pending_viewings: int
    unread_messages: int
    total_conversations: int
    total_views: int
    occupancy_rate: float
    monthly_revenue: float
    avg_response_time: str
    applications_pending: int
    applications_approved: int
    properties_vacant: int
    properties_occupied: int
```

---

### Change 1b — Initialise `total_conversations` in `calculate_landlord_stats()` and add its query

Find the `stats = { ... }` dict inside `calculate_landlord_stats()` (around line 215).
Add `"total_conversations": 0,` to the dict:

```python
stats = {
    "total_properties": 0,
    "properties_vacant": 0,
    "properties_occupied": 0,
    "active_listings": 0,
    "pending_viewings": 0,
    "unread_messages": 0,
    "total_conversations": 0,
    "applications_pending": 0,
    "applications_approved": 0,
    "total_views": 0,
    "monthly_revenue": 0.0,
    "occupancy_rate": 0.0,
    "avg_response_time": "0 hours",
    "_fetch_failed": False,
}
```

Then, after the existing Query 4 block (applications) and before `return stats`, add:

```python
    # -- Query 5: Total conversations ----------------------------------------
    # conversations table has landlord_id directly
    try:
        convos = supabase_admin.table("conversations") \
            .select("id") \
            .eq("landlord_id", landlord_id).execute()
        stats["total_conversations"] = len(convos.data or [])
    except Exception as e:
        logger.error("Stats query failed (conversations): %s", str(e))
        # Non-fatal -- do not set _fetch_failed

    return stats
```

> Make sure `return stats` stays as the final line of `calculate_landlord_stats()`.

---

### Change 1c — Add three new fields to `DashboardResponse` Pydantic model

Find (around line 107):
```python
class DashboardResponse(BaseModel):
    profile: LandlordProfile
    onboarding: Optional[LandlordOnboardingResponse]
    stats: LandlordStats
    properties: List[LandlordProperty]
    recent_activity: List[RecentActivity]
    notifications: List[Notification]
```

Replace with:
```python
class DashboardResponse(BaseModel):
    profile: LandlordProfile
    onboarding: Optional[LandlordOnboardingResponse]
    stats: LandlordStats
    properties: List[LandlordProperty]
    recent_activity: List[RecentActivity]
    notifications: List[Notification]
    viewing_requests: List[dict] = []
    received_applications: List[dict] = []
    agreements: List[dict] = []
```

---

### Change 1d — Add three new inner fetch functions inside `get_landlord_dashboard()`

Inside the async route handler `get_landlord_dashboard()`, after `def fetch_notifications():` and **before** `loop = asyncio.get_event_loop()`, add:

```python
        def fetch_viewing_requests():
            # viewing_requests has landlord_id directly
            try:
                result = supabase_admin.table("viewing_requests") \
                    .select(
                        "id, property_id, tenant_id, status, preferred_date, "
                        "confirmed_date, confirmed_time, time_slot, viewing_type, created_at"
                    ) \
                    .eq("landlord_id", landlord_id) \
                    .in_("status", ["pending", "confirmed"]) \
                    .order("created_at", desc=True) \
                    .limit(50) \
                    .execute()
                rows = result.data or []

                # Batch-fetch names -- one query per table, not one per row
                tenant_ids = list({r["tenant_id"] for r in rows if r.get("tenant_id")})
                property_ids = list({r["property_id"] for r in rows if r.get("property_id")})

                tenants_map = {}
                props_map = {}
                if tenant_ids:
                    t_res = supabase_admin.table("users") \
                        .select("id, full_name, first_name") \
                        .in_("id", tenant_ids).execute()
                    tenants_map = {t["id"]: t for t in (t_res.data or [])}
                if property_ids:
                    p_res = supabase_admin.table("properties") \
                        .select("id, title") \
                        .in_("id", property_ids).execute()
                    props_map = {p["id"]: p for p in (p_res.data or [])}

                for row in rows:
                    row["tenant"] = tenants_map.get(row.get("tenant_id"), {})
                    row["property"] = props_map.get(row.get("property_id"), {})
                return rows
            except Exception as e:
                logger.error("Failed to get viewing requests: %s", str(e))
                return []

        def fetch_received_applications():
            # IMPORTANT: applications table has NO landlord_id column.
            # Must get property_ids for this landlord first, then filter by them.
            try:
                # Step 1: get this landlord's property IDs
                props_res = supabase_admin.table("properties") \
                    .select("id") \
                    .eq("landlord_id", landlord_id).execute()
                property_ids = [p["id"] for p in (props_res.data or [])]

                if not property_ids:
                    return []

                # Step 2: get applications for those properties
                # Tenant FK is user_id -- there is no tenant_id column on applications
                result = supabase_admin.table("applications") \
                    .select(
                        "id, property_id, user_id, status, "
                        "created_at, viewed_by_landlord"
                    ) \
                    .in_("property_id", property_ids) \
                    .neq("status", "withdrawn") \
                    .order("created_at", desc=True) \
                    .limit(50) \
                    .execute()
                rows = result.data or []

                # Batch-fetch tenant names and property titles
                tenant_ids = list({r["user_id"] for r in rows if r.get("user_id")})
                props_to_fetch = list({r["property_id"] for r in rows if r.get("property_id")})

                tenants_map = {}
                props_map = {}
                if tenant_ids:
                    t_res = supabase_admin.table("users") \
                        .select("id, full_name") \
                        .in_("id", tenant_ids).execute()
                    tenants_map = {t["id"]: t for t in (t_res.data or [])}
                if props_to_fetch:
                    p_res = supabase_admin.table("properties") \
                        .select("id, title, price") \
                        .in_("id", props_to_fetch).execute()
                    props_map = {p["id"]: p for p in (p_res.data or [])}

                for row in rows:
                    row["user"] = tenants_map.get(row.get("user_id"), {})
                    row["property"] = props_map.get(row.get("property_id"), {})
                    # Expose as tenant_id too so the frontend can use either key
                    row["tenant_id"] = row.get("user_id")
                return rows
            except Exception as e:
                logger.error("Failed to get received applications: %s", str(e))
                return []

        def fetch_agreements():
            # agreements table has landlord_id directly
            # DB field names: rent_amount, lease_start_date, lease_end_date
            try:
                result = supabase_admin.table("agreements") \
                    .select(
                        "id, tenant_id, property_id, status, "
                        "lease_start_date, lease_end_date, rent_amount, "
                        "deposit_amount, created_at, updated_at"
                    ) \
                    .eq("landlord_id", landlord_id) \
                    .in_("status", ["ACTIVE", "SIGNED", "PENDING_LANDLORD", "PENDING_TENANT", "EXPIRED"]) \
                    .order("created_at", desc=True) \
                    .limit(50) \
                    .execute()
                rows = result.data or []

                tenant_ids = list({r["tenant_id"] for r in rows if r.get("tenant_id")})
                property_ids = list({r["property_id"] for r in rows if r.get("property_id")})

                tenants_map = {}
                props_map = {}
                if tenant_ids:
                    t_res = supabase_admin.table("users") \
                        .select("id, full_name") \
                        .in_("id", tenant_ids).execute()
                    tenants_map = {t["id"]: t for t in (t_res.data or [])}
                if property_ids:
                    p_res = supabase_admin.table("properties") \
                        .select("id, title") \
                        .in_("id", property_ids).execute()
                    props_map = {p["id"]: p for p in (p_res.data or [])}

                for row in rows:
                    row["tenant"] = tenants_map.get(row.get("tenant_id"), {})
                    row["property"] = props_map.get(row.get("property_id"), {})
                return rows
            except Exception as e:
                logger.error("Failed to get agreements: %s", str(e))
                return []
```

---

### Change 1e — Expand the parallel executor to include the three new functions

Find the existing `with ThreadPoolExecutor(...)` block:
```python
        with ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                loop.run_in_executor(executor, fetch_onboarding),
                loop.run_in_executor(executor, fetch_stats),
                loop.run_in_executor(executor, fetch_properties),
                loop.run_in_executor(executor, fetch_activity),
                loop.run_in_executor(executor, fetch_notifications),
            ]
            results = await asyncio.gather(*futures)

        onboarding_data, stats_data, properties_data, activity_data, notifications_data = results
```

Replace the entire block with:
```python
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [
                loop.run_in_executor(executor, fetch_onboarding),
                loop.run_in_executor(executor, fetch_stats),
                loop.run_in_executor(executor, fetch_properties),
                loop.run_in_executor(executor, fetch_activity),
                loop.run_in_executor(executor, fetch_notifications),
                loop.run_in_executor(executor, fetch_viewing_requests),
                loop.run_in_executor(executor, fetch_received_applications),
                loop.run_in_executor(executor, fetch_agreements),
            ]
            results = await asyncio.gather(*futures)

        (onboarding_data, stats_data, properties_data, activity_data,
         notifications_data, viewing_requests_data,
         received_applications_data, agreements_data) = results
```

---

### Change 1f — Add new fields to the `dashboard_data` dict

Find:
```python
        dashboard_data = {
            "profile": profile_data,
            "onboarding": onboarding_data,
            "stats": stats_data,
            "properties": properties_data,
            "recent_activity": activity_data,
            "notifications": notifications_data
        }
```

Replace with:
```python
        dashboard_data = {
            "profile": profile_data,
            "onboarding": onboarding_data,
            "stats": stats_data,
            "properties": properties_data,
            "recent_activity": activity_data,
            "notifications": notifications_data,
            "viewing_requests": viewing_requests_data,
            "received_applications": received_applications_data,
            "agreements": agreements_data,
        }
```

---

## FILE 2 — `page.tsx` (landlord dashboard overview)

### Change 2a — Fix the `LandlordAgreement` TypeScript interface field names

The frontend interface in `landlordDashboard.ts` uses wrong DB field names.
Find the `LandlordAgreement` interface and update these three fields:

```tsx
// WRONG field names (do not use):
//   monthly_rent  →  DB column is rent_amount
//   start_date    →  DB column is lease_start_date
//   end_date      →  DB column is lease_end_date

export interface LandlordAgreement {
  id: string
  tenant_id?: string
  property_id?: string
  status: 'ACTIVE' | 'SIGNED' | 'PENDING_LANDLORD' | 'PENDING_TENANT' | 'EXPIRED' | 'TERMINATED'
  lease_start_date?: string    // was start_date
  lease_end_date?: string      // was end_date
  rent_amount?: number         // was monthly_rent
  deposit_amount?: number
  tenant?: { full_name?: string }
  property?: { title?: string }
  created_at: string
  updated_at?: string
}
```

> Also search the whole file for any references to `a.monthly_rent`, `a.start_date`, `a.end_date` on agreement objects and update them to the correct field names.

---

### Change 2b — Remove four state declarations that are no longer needed

Find and delete these four `useState` lines near the top of the `LandlordDashboard` component:
```tsx
const [viewingRequests, setViewingRequests] = useState<any[]>([])
const [applications, setApplications] = useState<Application[]>([])
const [engagementMetrics, setEngagementMetrics] = useState<any>(null)
const [agreements, setAgreements] = useState<any[]>([])
```

Keep only:
```tsx
const [receivedPayments, setReceivedPayments] = useState<any[]>([])
```

---

### Change 2c — Replace the entire secondary `useEffect` with a payments-only fetch

Find the comment `// Unified data fetching - fetch all additional data at once` and the entire `useEffect` block below it (it runs ~115 lines and uses `Promise.allSettled` to fetch viewings, applications, agreements, engagement, and payments).

**Delete the entire block** and replace it with:

```tsx
// Secondary fetch: payments only.
// Viewings, applications, agreements, and engagement now come from landlordData
// (bundled into the main /api/v1/landlord/dashboard response).
useEffect(() => {
  if (!landlordData) return

  const fetchPayments = async () => {
    try {
      setAllDataLoading(true)
      const data = await paymentsAPI.getReceivedPayments()
      // API wraps the array: { success: true, payments: [...] }
      // Normalise all possible response shapes
      const list = Array.isArray(data)
        ? data
        : Array.isArray((data as any)?.payments)
        ? (data as any).payments
        : Array.isArray((data as any)?.data)
        ? (data as any).data
        : []
      setReceivedPayments(list)
    } catch (err) {
      console.error('Failed to fetch payments:', err)
      setReceivedPayments([])
    } finally {
      setAllDataLoading(false)
    }
  }

  fetchPayments()
}, [landlordData])
```

---

### Change 2d — Read bundled data directly from `landlordData`

Find the destructure block near line 642 where `profile`, `stats`, `properties`, `recentActivity` are read from `landlordData`. Immediately after that block, add:

```tsx
// These were previously fetched separately. They now come from landlordData
// because the backend bundles them in the /dashboard response.
const viewingRequests: any[]  = landlordData?.viewingRequests  ?? []
const applications: any[]     = landlordData?.receivedApplications ?? []
const agreements: any[]       = landlordData?.agreements ?? []
const engagementMetrics: any  = landlordData?.engagementMetrics ?? null
```

---

### Change 2e — Hold the spinner until payments also resolves

Find (around line 602):
```tsx
if (!mounted || loading) {
```

Replace with:
```tsx
if (!mounted || loading || allDataLoading) {
```

This keeps the full-page spinner visible until both the main dashboard data AND payments have loaded, preventing any zero-flash on stat cards.

---

### Change 2f — Fix the Messages stat card to use nullish coalescing

Find the messages card number (around line 906) and its sub-label (around line 911).
Replace `||` with `??` so the value `0` is treated as valid data, not as falsy:

```tsx
// Before:
{stats.total_conversations || stats.unread_messages || 0}

// After:
{stats.total_conversations ?? stats.unread_messages ?? 0}
```

Apply the same `??` replacement on the sub-label line that reads the same expression inside the conversations badge text.

---

### Change 2g — Fix the `agreementStats` memo to use correct field names

Find the `agreementStats` useMemo (it filters agreements by status).
Make sure any access to date or rent fields uses the corrected names:

```tsx
// If this memo or any nearby code references these fields, update them:
// a.monthly_rent  →  a.rent_amount
// a.start_date    →  a.lease_start_date
// a.end_date      →  a.lease_end_date
```

---

### Change 2h — Clean up now-unused imports

After the useEffect replacement, these imports may no longer be used in the file.
Check each one — if it is only referenced in the deleted `useEffect` block, remove it:

```tsx
// Possibly safe to remove (verify each is not used elsewhere in the file):
import { viewingRequestsAPI as landlordViewingRequestsAPI } from "@/lib/api/viewingRequestsLandlord"
import { applicationsAPI, type Application } from "@/lib/api/applications"
import { agreementsAPI } from "@/lib/api/agreements"
```

For the engagement import — keep it because the engagement section JSX uses the helper functions:
```tsx
// KEEP this import — helper functions are used in JSX below:
import { engagementAPI, getEngagementLevelColor, ... , trackEngagement } from "@/lib/api/engagement"
```

---

## Summary Table

| # | File | What changes | Why |
|---|------|-------------|-----|
| 1a | `landlord_dashboard.py` | Add `total_conversations` to `LandlordStats` model | Messages stat card field |
| 1b | `landlord_dashboard.py` | Init + Query 5 for conversations count | Populate the field |
| 1c | `landlord_dashboard.py` | Add 3 new fields to `DashboardResponse` model | FastAPI can serialise them |
| 1d | `landlord_dashboard.py` | Add 3 new inner fetch functions | Bundle viewings, applications, agreements |
| 1e | `landlord_dashboard.py` | Expand thread pool to 8, unpack 8 results | Run new fetches in parallel |
| 1f | `landlord_dashboard.py` | Add new fields to `dashboard_data` dict | Include in JSON response |
| 2a | `page.tsx` / `landlordDashboard.ts` | Fix `LandlordAgreement` interface field names | Match actual DB column names |
| 2b | `page.tsx` | Remove 4 `useState` declarations | No longer managed locally |
| 2c | `page.tsx` | Replace secondary `useEffect` with payments-only fetch | Eliminate 4 redundant API calls |
| 2d | `page.tsx` | Read bundled data from `landlordData` directly | Single source of truth |
| 2e | `page.tsx` | Loading guard: `\|\| allDataLoading` | Spinner holds until payments resolves |
| 2f | `page.tsx` | Messages card: `\|\|` → `??` | `0` is valid, not falsy |
| 2g | `page.tsx` | Fix agreement field name references in memos | Match DB column names |
| 2h | `page.tsx` | Remove unused imports | Clean codebase |

---

## Do NOT change

- `DashboardContext.tsx` — `fetchLandlordDashboard()` stores whatever the API returns, new fields flow through automatically.
- `payments.ts` — `paymentsAPI.getReceivedPayments()` is correct. The bug was in `page.tsx` not handling the response wrapper.
- `dashboardCache.ts` — no changes.
- `/api/v1/payments/received` backend route — no changes.

---

## Verification checklist after applying fixes

- [ ] `GET /api/v1/landlord/dashboard` response JSON now includes `viewing_requests`, `received_applications`, `agreements` arrays and `stats.total_conversations`
- [ ] Network tab shows only 2 API calls on dashboard load (main dashboard + payments received), not 6
- [ ] Dashboard loads once with a single clean spinner — no zero-to-real-value flash on any stat card
- [ ] Messages stat card shows correct conversation count (not 0)
- [ ] Total Collected card shows the correct payment amount (not ₦0)
- [ ] Viewings, Applications, Agreements counts are correct on first render
- [ ] Refresh button still works (invalidates cache key `'landlord:dashboard'` and refetches)
- [ ] No TypeScript errors on `LandlordAgreement` fields (`rent_amount`, `lease_start_date`, `lease_end_date`)