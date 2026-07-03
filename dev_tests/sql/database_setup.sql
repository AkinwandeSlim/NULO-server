-- ============================================
-- Nulo Africa Database Setup
-- ============================================
-- Run these SQL commands in Supabase SQL Editor
-- 
-- IMPORTANT NOTES:
-- 1. Run this ENTIRE script at once (select all and execute)
-- 2. OR run sections in the exact order shown
-- 3. Make sure 'users' and 'properties' tables exist first
-- 4. If you get errors, drop tables and re-run:
--    DROP TABLE IF EXISTS messages CASCADE;
--    DROP TABLE IF EXISTS conversations CASCADE;
--    DROP TABLE IF EXISTS viewing_requests CASCADE;
--    DROP TABLE IF EXISTS favorites CASCADE;
-- ============================================

-- Enable UUID extension if not already enabled
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ============================================
-- 1. CONVERSATIONS TABLE (Must be created first)
-- ============================================
CREATE TABLE IF NOT EXISTS conversations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  landlord_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  property_id UUID REFERENCES properties(id) ON DELETE CASCADE NOT NULL,
  last_message TEXT,
  last_message_at TIMESTAMP WITH TIME ZONE,
  status VARCHAR(20) DEFAULT 'active' CHECK (status IN ('active', 'archived', 'blocked')),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Ensure unique conversation per tenant-landlord-property combination
  UNIQUE(tenant_id, landlord_id, property_id)
);

-- Indexes for conversations
CREATE INDEX idx_conversations_tenant ON conversations(tenant_id);
CREATE INDEX idx_conversations_landlord ON conversations(landlord_id);
CREATE INDEX idx_conversations_property ON conversations(property_id);
CREATE INDEX idx_conversations_last_message_at ON conversations(last_message_at DESC);

-- ============================================
-- 2. MESSAGES TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS messages (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE NOT NULL,
  sender_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  recipient_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  content TEXT NOT NULL,
  property_id UUID REFERENCES properties(id) ON DELETE SET NULL,
  message_type VARCHAR(20) DEFAULT 'text' CHECK (message_type IN ('text', 'image', 'file', 'system')),
  read BOOLEAN DEFAULT FALSE,
  read_at TIMESTAMP WITH TIME ZONE,
  timestamp TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Ensure content is not empty
  CONSTRAINT content_not_empty CHECK (LENGTH(TRIM(content)) > 0)
);

-- Indexes for messages
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_messages_sender ON messages(sender_id);
CREATE INDEX idx_messages_recipient ON messages(recipient_id);
CREATE INDEX idx_messages_timestamp ON messages(timestamp DESC);
CREATE INDEX idx_messages_unread ON messages(recipient_id, read) WHERE read = FALSE;

-- ============================================
-- 3. VIEWING REQUESTS TABLE
-- ============================================
CREATE TABLE IF NOT EXISTS viewing_requests (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  landlord_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  property_id UUID REFERENCES properties(id) ON DELETE CASCADE NOT NULL,
  preferred_date DATE NOT NULL,
  time_slot VARCHAR(20) NOT NULL CHECK (time_slot IN ('morning', 'afternoon', 'evening')),
  contact_number VARCHAR(20) NOT NULL,
  tenant_name VARCHAR(100) NOT NULL,
  message TEXT,
  status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'confirmed', 'cancelled', 'completed', 'rejected')),
  landlord_notes TEXT,
  confirmed_date DATE,
  confirmed_time VARCHAR(50),
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Ensure preferred date is not in the past
  CONSTRAINT future_date CHECK (preferred_date >= CURRENT_DATE)
);

-- Indexes for viewing_requests
CREATE INDEX idx_viewing_requests_tenant ON viewing_requests(tenant_id);
CREATE INDEX idx_viewing_requests_landlord ON viewing_requests(landlord_id);
CREATE INDEX idx_viewing_requests_property ON viewing_requests(property_id);
CREATE INDEX idx_viewing_requests_status ON viewing_requests(status);
CREATE INDEX idx_viewing_requests_date ON viewing_requests(preferred_date);

-- ============================================
-- 4. FAVORITES TABLE (if not exists)
-- ============================================
CREATE TABLE IF NOT EXISTS favorites (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  tenant_id UUID REFERENCES users(id) ON DELETE CASCADE NOT NULL,
  property_id UUID REFERENCES properties(id) ON DELETE CASCADE NOT NULL,
  created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
  
  -- Ensure unique favorite per tenant-property combination
  UNIQUE(tenant_id, property_id)
);

-- Indexes for favorites
CREATE INDEX idx_favorites_tenant ON favorites(tenant_id);
CREATE INDEX idx_favorites_property ON favorites(property_id);
CREATE INDEX idx_favorites_created_at ON favorites(created_at DESC);

-- ============================================
-- 5. UPDATE TRIGGERS
-- ============================================

-- Auto-update updated_at timestamp for conversations
CREATE OR REPLACE FUNCTION update_conversations_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER conversations_updated_at_trigger
BEFORE UPDATE ON conversations
FOR EACH ROW
EXECUTE FUNCTION update_conversations_updated_at();

-- Auto-update updated_at timestamp for viewing_requests
CREATE OR REPLACE FUNCTION update_viewing_requests_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = NOW();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER viewing_requests_updated_at_trigger
BEFORE UPDATE ON viewing_requests
FOR EACH ROW
EXECUTE FUNCTION update_viewing_requests_updated_at();

-- ============================================
-- 6. ROW LEVEL SECURITY (RLS) POLICIES
-- ============================================

-- Enable RLS on all tables
ALTER TABLE conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE viewing_requests ENABLE ROW LEVEL SECURITY;
ALTER TABLE favorites ENABLE ROW LEVEL SECURITY;

-- Conversations policies
CREATE POLICY "Users can view their own conversations"
  ON conversations FOR SELECT
  USING (auth.uid() = tenant_id OR auth.uid() = landlord_id);

CREATE POLICY "Tenants can create conversations"
  ON conversations FOR INSERT
  WITH CHECK (auth.uid() = tenant_id);

CREATE POLICY "Users can update their own conversations"
  ON conversations FOR UPDATE
  USING (auth.uid() = tenant_id OR auth.uid() = landlord_id);

-- Messages policies
CREATE POLICY "Users can view their own messages"
  ON messages FOR SELECT
  USING (auth.uid() = sender_id OR auth.uid() = recipient_id);

CREATE POLICY "Users can send messages in their conversations"
  ON messages FOR INSERT
  WITH CHECK (
    auth.uid() = sender_id AND
    EXISTS (
      SELECT 1 FROM conversations
      WHERE id = conversation_id
      AND (tenant_id = auth.uid() OR landlord_id = auth.uid())
    )
  );

CREATE POLICY "Recipients can update message read status"
  ON messages FOR UPDATE
  USING (auth.uid() = recipient_id);

-- Viewing requests policies
CREATE POLICY "Users can view their own viewing requests"
  ON viewing_requests FOR SELECT
  USING (auth.uid() = tenant_id OR auth.uid() = landlord_id);

CREATE POLICY "Tenants can create viewing requests"
  ON viewing_requests FOR INSERT
  WITH CHECK (auth.uid() = tenant_id);

CREATE POLICY "Users can update their own viewing requests"
  ON viewing_requests FOR UPDATE
  USING (auth.uid() = tenant_id OR auth.uid() = landlord_id);

-- Favorites policies
CREATE POLICY "Users can view their own favorites"
  ON favorites FOR SELECT
  USING (auth.uid() = tenant_id);

CREATE POLICY "Tenants can add favorites"
  ON favorites FOR INSERT
  WITH CHECK (auth.uid() = tenant_id);

CREATE POLICY "Tenants can remove their favorites"
  ON favorites FOR DELETE
  USING (auth.uid() = tenant_id);

-- ============================================
-- 7. SAMPLE DATA (Optional - for testing)
-- ============================================

-- Note: Replace UUIDs with actual user and property IDs from your database

-- Sample conversation
-- INSERT INTO conversations (tenant_id, landlord_id, property_id, last_message, last_message_at, status)
-- VALUES (
--   'tenant-uuid-here',
--   'landlord-uuid-here',
--   'property-uuid-here',
--   'Hi, is this property still available?',
--   NOW(),
--   'active'
-- );

-- Sample message
-- INSERT INTO messages (conversation_id, sender_id, recipient_id, content, property_id, message_type, read)
-- VALUES (
--   'conversation-uuid-here',
--   'tenant-uuid-here',
--   'landlord-uuid-here',
--   'Hi, is this property still available?',
--   'property-uuid-here',
--   'text',
--   FALSE
-- );

-- Sample viewing request
-- INSERT INTO viewing_requests (tenant_id, landlord_id, property_id, preferred_date, time_slot, contact_number, tenant_name, message, status)
-- VALUES (
--   'tenant-uuid-here',
--   'landlord-uuid-here',
--   'property-uuid-here',
--   '2025-10-25',
--   'afternoon',
--   '+234 803 456 7890',
--   'John Doe',
--   'Hi, I would like to view this property.',
--   'pending'
-- );

-- Sample favorite
-- INSERT INTO favorites (tenant_id, property_id)
-- VALUES (
--   'tenant-uuid-here',
--   'property-uuid-here'
-- );

-- ============================================
-- 8. VERIFICATION QUERIES
-- ============================================

-- Check if tables were created successfully
SELECT table_name 
FROM information_schema.tables 
WHERE table_schema = 'public' 
AND table_name IN ('conversations', 'messages', 'viewing_requests', 'favorites');

-- Check indexes
SELECT tablename, indexname 
FROM pg_indexes 
WHERE schemaname = 'public' 
AND tablename IN ('conversations', 'messages', 'viewing_requests', 'favorites');

-- Check RLS policies
SELECT tablename, policyname, permissive, roles, cmd, qual 
FROM pg_policies 
WHERE schemaname = 'public' 
AND tablename IN ('conversations', 'messages', 'viewing_requests', 'favorites');

-- ============================================
-- SETUP COMPLETE! 🎉
-- ============================================
