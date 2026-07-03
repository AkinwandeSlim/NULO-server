-- ============================================================================
-- ONBD-09: Database-level enforcement + admin escape hatch
-- File: server/app/db_migrations/2026_06_24_onbd09_admin_exec_sql.sql
--
-- Apply this migration in the Supabase SQL editor OR via
--     psql -f server/app/db_migrations/2026_06_24_onbd09_admin_exec_sql.sql
--
-- It installs:
--   1. A BEFORE INSERT trigger on `properties` that raises an exception
--      when the landlord's `users.verification_status` is 'rejected'.
--      This is a defence-in-depth layer behind the application-level
--      guard added to POST /api/v1/properties in properties.py.
--   2. A SECURITY DEFINER RPC `public.exec_sql(sql text)` used by the
--      hard-delete backfill script
--      (dev_tests/scripts/backfill_hard_delete_rejected_landlord.py).
--      The function is restricted to the service_role so it is only
--      callable from server-side admin scripts.
--
-- The trigger uses a SECURITY DEFINER helper function so it can read the
-- `users` table from the property-insert context (which normally only has
-- the inserting role's grants).
-- ============================================================================

-- ---------------------------------------------------------------------------
-- 1. Helper: read the landlord's verification_status safely
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.get_landlord_verification_status(uid uuid)
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
    SELECT verification_status
    FROM public.users
    WHERE id = uid
    LIMIT 1;
$$;

-- ---------------------------------------------------------------------------
-- 2. Trigger function: blocks INSERTs on `properties` for rejected landlords
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.reject_property_for_rejected_landlord()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_status text;
BEGIN
    v_status := public.get_landlord_verification_status(NEW.landlord_id);

    IF v_status IS NULL THEN
        RAISE EXCEPTION
            'ONBD-09: landlord % does not exist', NEW.landlord_id
            USING ERRCODE = 'foreign_key_violation';
    END IF;

    IF v_status = 'rejected' THEN
        RAISE EXCEPTION
            'ONBD-09: landlord % is rejected and cannot create properties',
            NEW.landlord_id
            USING ERRCODE = 'check_violation';
    END IF;

    RETURN NEW;
END;
$$;

-- Drop the trigger if it already exists (idempotent re-apply)
DROP TRIGGER IF EXISTS trg_block_rejected_landlord_property_insert
    ON public.properties;

CREATE TRIGGER trg_block_rejected_landlord_property_insert
    BEFORE INSERT ON public.properties
    FOR EACH ROW
    EXECUTE FUNCTION public.reject_property_for_rejected_landlord();

-- ---------------------------------------------------------------------------
-- 3. RPC used by the hard-delete backfill script
--    service_role-only: revoke from PUBLIC and grant only to the
--    `service_role` role that Supabase uses for server-side admin clients.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.exec_sql(sql text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
BEGIN
    EXECUTE sql;
END;
$$;

REVOKE ALL ON FUNCTION public.exec_sql(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.exec_sql(text) FROM anon;
REVOKE ALL ON FUNCTION public.exec_sql(text) FROM authenticated;
GRANT EXECUTE ON FUNCTION public.exec_sql(text) TO service_role;

-- ---------------------------------------------------------------------------
-- 4. Helpful read-only view for ad-hoc auditing
-- ---------------------------------------------------------------------------
CREATE OR REPLACE VIEW public.rejected_landlord_remaining_properties AS
SELECT
    u.id           AS landlord_id,
    u.email,
    u.full_name,
    p.id           AS property_id,
    p.title,
    p.verification_status AS property_verification_status,
    p.deleted_at   AS property_deleted_at
FROM public.users u
LEFT JOIN public.properties p ON p.landlord_id = u.id
WHERE u.user_type = 'landlord'
  AND u.verification_status = 'rejected';

GRANT SELECT ON public.rejected_landlord_remaining_properties TO service_role;
