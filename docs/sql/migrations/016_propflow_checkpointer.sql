-- Migration 016: PropFlow Checkpointer — Supabase REST-backed checkpoint storage
-- Created: 2026-07-22
--
-- Creates two tables for LangGraph's checkpoint persistence via the Supabase REST API:
--   - propflow_checkpoints       stores serialized checkpoint snapshots
--   - propflow_checkpoint_writes stores pending writes for human-in-the-loop
--
-- Also updates propflow_threads with landlord_id and workflow metadata for
-- multi-tenant landlord dashboards.
--
-- Run this in the Supabase SQL editor before restarting the server.

-- ═══════════════════════════════════════════════════════════════════════════════
-- TABLE: propflow_checkpoints
-- Stores serialized LangGraph Checkpoint objects (one per step per thread).
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS propflow_checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB DEFAULT '{}'::jsonb,
    channel_values JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE INDEX IF NOT EXISTS idx_pc_thread
    ON propflow_checkpoints(thread_id, checkpoint_ns, checkpoint_id DESC);

CREATE INDEX IF NOT EXISTS idx_pc_created
    ON propflow_checkpoints(created_at DESC);

-- ═══════════════════════════════════════════════════════════════════════════════
-- TABLE: propflow_checkpoint_writes
-- Stores pending writes for human-in-the-loop checkpoints.
-- Each row is one pending write (channel + value) for a specific checkpoint
-- and task.
-- ═══════════════════════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS propflow_checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    value JSONB NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS idx_pcw_lookup
    ON propflow_checkpoint_writes(thread_id, checkpoint_ns, checkpoint_id);

-- ═══════════════════════════════════════════════════════════════════════════════
-- TABLE: propflow_threads
-- Maps thread_id to tenant_id and landlord_id for multi-tenant queries.
-- Updated automatically by the checkpointer on every checkpoint write.
--
-- NOTE: This table replaces the migration 015 version. If 015 was previously
-- run, this DROP + CREATE is safe because 015's data was never populated
-- (MemorySaver was always used).
-- ═══════════════════════════════════════════════════════════════════════════════

DROP TABLE IF EXISTS propflow_threads CASCADE;

CREATE TABLE propflow_threads (
    thread_id TEXT PRIMARY KEY,
    tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    landlord_id UUID REFERENCES users(id) ON DELETE SET NULL,
    workflow_id TEXT,
    current_stage TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_propflow_threads_tenant
    ON propflow_threads(tenant_id);

CREATE INDEX IF NOT EXISTS idx_propflow_threads_landlord
    ON propflow_threads(landlord_id);

CREATE INDEX IF NOT EXISTS idx_propflow_threads_status
    ON propflow_threads(status);

CREATE INDEX IF NOT EXISTS idx_propflow_threads_updated
    ON propflow_threads(updated_at DESC);

-- Auto-update trigger for updated_at
CREATE OR REPLACE FUNCTION update_propflow_threads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trigger_propflow_threads_updated_at ON propflow_threads;
CREATE TRIGGER trigger_propflow_threads_updated_at
    BEFORE UPDATE ON propflow_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_propflow_threads_updated_at();

-- Row-level security
ALTER TABLE propflow_threads ENABLE ROW LEVEL SECURITY;

-- Policy: Tenants can see their own threads
CREATE POLICY propflow_threads_select_tenant_policy ON propflow_threads
    FOR SELECT USING (tenant_id = auth.uid());

-- Policy: Landlords can see threads for their properties
CREATE POLICY propflow_threads_select_landlord_policy ON propflow_threads
    FOR SELECT USING (landlord_id = auth.uid());

-- Policy: Service role can insert/update (used by checkpointer with service key)
CREATE POLICY propflow_threads_insert_policy ON propflow_threads
    FOR INSERT WITH CHECK (true);

CREATE POLICY propflow_threads_update_policy ON propflow_threads
    FOR UPDATE USING (true);

-- Comments
COMMENT ON TABLE propflow_checkpoints
    IS 'Serialized LangGraph checkpoints for PropFlow AI agent workflows';
COMMENT ON COLUMN propflow_checkpoints.channel_values
    IS 'Extracted PropFlowState for fast querying without deserializing full checkpoint';
COMMENT ON TABLE propflow_checkpoint_writes
    IS 'Pending writes for human-in-the-loop checkpoint interrupts';
