-- Migration 015: PropFlow Threads Table
-- Stores persisted state for LangGraph workflow threads
-- Created: 2026-07-15 (Day 4 - Qwen Hackathon)

-- Create propflow_threads table
CREATE TABLE IF NOT EXISTS propflow_threads (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT propflow_threads_tenant_id_fkey FOREIGN KEY (tenant_id) REFERENCES users(id) ON DELETE CASCADE
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_propflow_threads_tenant_id ON propflow_threads(tenant_id);
CREATE INDEX IF NOT EXISTS idx_propflow_threads_updated_at ON propflow_threads(updated_at DESC);

-- Row-level security
ALTER TABLE propflow_threads ENABLE ROW LEVEL SECURITY;

-- Policy: Users can only see their own threads
CREATE POLICY propflow_threads_select_policy ON propflow_threads
    FOR SELECT USING (tenant_id = auth.uid());

-- Policy: Users can insert their own threads
CREATE POLICY propflow_threads_insert_policy ON propflow_threads
    FOR INSERT WITH CHECK (tenant_id = auth.uid());

-- Policy: Users can update their own threads
CREATE POLICY propflow_threads_update_policy ON propflow_threads
    FOR UPDATE USING (tenant_id = auth.uid());

-- Trigger to auto-update updated_at
CREATE OR REPLACE FUNCTION update_propflow_threads_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trigger_update_propflow_threads_updated_at
    BEFORE UPDATE ON propflow_threads
    FOR EACH ROW
    EXECUTE FUNCTION update_propflow_threads_updated_at();

-- Comment
COMMENT ON TABLE propflow_threads IS 'Persists LangGraph state for PropFlow AI agent workflows';
COMMENT ON COLUMN propflow_threads.state IS 'Full PropFlowState JSON including workflow_id, current_stage, extracted_intent, etc.';
