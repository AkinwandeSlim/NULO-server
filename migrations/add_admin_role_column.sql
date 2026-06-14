-- Migration: Add admin_role field to users table
-- Purpose: Enable role-based access control for admin users (super_admin, admin, limited_admin)
-- Date: 2026-06-13

ALTER TABLE users
ADD COLUMN admin_role VARCHAR(50) DEFAULT NULL
CHECK (admin_role IN ('super_admin', 'admin', 'limited_admin', NULL));

-- Add index for faster role lookups
CREATE INDEX idx_users_admin_role ON users(admin_role);

-- Add admin_role to the view that returns user data
-- (if you have views that select from users)

-- Add audit log entry
INSERT INTO audit_logs (
  user_id,
  action,
  table_name,
  description,
  created_at
) VALUES (
  (SELECT id FROM users WHERE user_type = 'admin' LIMIT 1),
  'SCHEMA_UPDATE',
  'users',
  'Added admin_role column for role-based access control',
  NOW()
);

-- Verify the column was added
-- SELECT column_name, data_type, column_default FROM information_schema.columns WHERE table_name='users';
