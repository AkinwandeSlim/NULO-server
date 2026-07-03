# PowerShell helper script: load .env and run a single Supabase query.
# Usage:
#   .\run_query.ps1
#
# Edit the $QueryUri and $Method below to run a different query.
# Right now it checks the landlord record to confirm the bank lookup
# wrote correctly to the database.

# 1. Load .env into the current process (skip comments and blank lines)
$envPath = Join-Path $PSScriptRoot ".env"
if (-not (Test-Path $envPath)) {
    Write-Error ".env not found at $envPath"
    exit 1
}
$loadedCount = 0
foreach ($line in Get-Content $envPath) {
    $trimmed = $line.Trim()
    if ($trimmed -eq '' -or $trimmed.StartsWith('#')) { continue }
    $idx = $trimmed.IndexOf('=')
    if ($idx -lt 1) { continue }
    $k = $trimmed.Substring(0, $idx).Trim()
    $v = $trimmed.Substring($idx + 1).Trim().Trim('"').Trim("'")
    [Environment]::SetEnvironmentVariable($k, $v, 'Process')
    $loadedCount++
}
Write-Host "Loaded $loadedCount env vars from .env"

# 2. Sanity check the env vars we need
# The .env uses SUPABASE_SERVICE_KEY (not SUPABASE_SERVICE_ROLE_KEY)
if (-not $env:SUPABASE_URL) {
    Write-Error "SUPABASE_URL is not set in .env"
    exit 1
}
$serviceKey = $env:SUPABASE_SERVICE_KEY
if (-not $serviceKey) {
    $serviceKey = $env:SUPABASE_SERVICE_ROLE_KEY  # fallback for other naming conventions
}
if (-not $serviceKey) {
    Write-Error "SUPABASE_SERVICE_KEY is not set in .env"
    exit 1
}
Write-Host "SUPABASE_URL: $($env:SUPABASE_URL.Substring(0, 35))..."
Write-Host "Has SERVICE_KEY: True"
Write-Host ""

# 2b. Build the headers hashtable
$Headers = @{
    "apikey"        = $serviceKey
    "Authorization" = "Bearer $serviceKey"
}

# 3. Build the diagnostic -- checks all 4 tables related to the landlord
$landlordId = "070671cd-a779-4997-9046-771467394f53"

function Run-Query {
    param($Label, $Uri, $Method, $Headers)
    Write-Host ""
    Write-Host "=== $Label ===" -ForegroundColor Cyan
    try {
        $resp = Invoke-RestMethod -Method $Method -Uri $Uri -Headers $Headers
        if ($null -eq $resp -or $resp.Count -eq 0) {
            Write-Host "  0 rows" -ForegroundColor Yellow
        } else {
            $resp | Format-List
        }
    } catch {
        Write-Host "  ERROR: $_" -ForegroundColor Red
    }
}

# 1. Does the user exist at all?
Run-Query "users.id = $landlordId" `
    "$($env:SUPABASE_URL)/rest/v1/users?id=eq.$landlordId&select=id,email,full_name,user_type,verification_status" `
    "GET" $Headers

# 2. landlords table (the one bank lookup writes to)
Run-Query "landlords.id = $landlordId" `
    "$($env:SUPABASE_URL)/rest/v1/landlords?id=eq.$landlordId&select=id,bank_account_number,bank_name,bank_verified_at,verification_approved_at" `
    "GET" $Headers

# 3. landlord_profiles table
Run-Query "landlord_profiles.id = $landlordId" `
    "$($env:SUPABASE_URL)/rest/v1/landlord_profiles?id=eq.$landlordId&select=id,is_verified,verification_status,bank_verified_at,bank_account_number" `
    "GET" $Headers

# 4. landlord_onboarding table (if it exists)
Run-Query "landlord_onboarding.user_id = $landlordId" `
    "$($env:SUPABASE_URL)/rest/v1/landlord_onboarding?user_id=eq.$landlordId&select=user_id,current_step,is_complete" `
    "GET" $Headers

# 5. tenants table (the user's note: "i dont have any data in tenant i only have the tenant_profile populated")
$tenantId = "05c71152-a018-423e-8c27-f701727f4935"  # Eze Uchenna Gerald (the tenant)
Run-Query "tenants.id = $tenantId" `
    "$($env:SUPABASE_URL)/rest/v1/tenants?id=eq.$tenantId&select=*" `
    "GET" $Headers

# 6. tenant_profiles table
Run-Query "tenant_profiles.id = $tenantId" `
    "$($env:SUPABASE_URL)/rest/v1/tenant_profiles?id=eq.$tenantId&select=id,is_verified,verification_status" `
    "GET" $Headers

# 7. List ALL columns in the operational landlord/tenant tables (for consolidation analysis)
Write-Host ""
Write-Host "=== landlords columns ===" -ForegroundColor Cyan
try {
    $cols = Invoke-RestMethod -Method Get -Uri "$($env:SUPABASE_URL)/rest/v1/information_schema/columns?table_name=eq.landlords&table_schema=eq.public&select=column_name,data_type,is_nullable" -Headers $Headers
    $cols | ForEach-Object { Write-Host "  $($_.column_name) ($($_.data_type), nullable=$($_.is_nullable))" }
} catch { Write-Host "  ERROR: $_" -ForegroundColor Red }

Write-Host ""
Write-Host "=== landlord_profiles columns ===" -ForegroundColor Cyan
try {
    $cols = Invoke-RestMethod -Method Get -Uri "$($env:SUPABASE_URL)/rest/v1/information_schema/columns?table_name=eq.landlord_profiles&table_schema=eq.public&select=column_name,data_type,is_nullable" -Headers $Headers
    $cols | ForEach-Object { Write-Host "  $($_.column_name) ($($_.data_type), nullable=$($_.is_nullable))" }
} catch { Write-Host "  ERROR: $_" -ForegroundColor Red }

Write-Host ""
Write-Host "=== tenants columns ===" -ForegroundColor Cyan
try {
    $cols = Invoke-RestMethod -Method Get -Uri "$($env:SUPABASE_URL)/rest/v1/information_schema/columns?table_name=eq.tenants&table_schema=eq.public&select=column_name,data_type,is_nullable" -Headers $Headers
    $cols | ForEach-Object { Write-Host "  $($_.column_name) ($($_.data_type), nullable=$($_.is_nullable))" }
} catch { Write-Host "  ERROR: $_" -ForegroundColor Red }

Write-Host ""
Write-Host "=== tenant_profiles columns ===" -ForegroundColor Cyan
try {
    $cols = Invoke-RestMethod -Method Get -Uri "$($env:SUPABASE_URL)/rest/v1/information_schema/columns?table_name=eq.tenant_profiles&table_schema=eq.public&select=column_name,data_type,is_nullable" -Headers $Headers
    $cols | ForEach-Object { Write-Host "  $($_.column_name) ($($_.data_type), nullable=$($_.is_nullable))" }
} catch { Write-Host "  ERROR: $_" -ForegroundColor Red }
