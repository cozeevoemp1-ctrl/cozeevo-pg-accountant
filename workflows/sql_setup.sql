-- ============================================================
-- PG Ledger AI — Database Setup (Supabase / PostgreSQL)
-- Run this ONCE in Supabase SQL Editor before deploying workflows
-- ============================================================

-- 1. Properties
CREATE TABLE IF NOT EXISTS properties (
  id SERIAL PRIMARY KEY,
  name TEXT NOT NULL,
  address TEXT,
  owner_phone TEXT NOT NULL,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 2. Authorized Users (security gate for all WhatsApp messages)
CREATE TABLE IF NOT EXISTS authorized_users (
  id SERIAL PRIMARY KEY,
  phone TEXT NOT NULL UNIQUE,   -- format: 919876543210 (no +)
  role TEXT NOT NULL DEFAULT 'owner', -- owner | tenant
  property_id INT REFERENCES properties(id),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. Rooms
CREATE TABLE IF NOT EXISTS rooms (
  id SERIAL PRIMARY KEY,
  property_id INT REFERENCES properties(id),
  room_number TEXT NOT NULL,
  capacity INT DEFAULT 1,
  rent_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
  status TEXT DEFAULT 'vacant', -- vacant | occupied
  UNIQUE(property_id, room_number)
);

-- 4. Tenants
CREATE TABLE IF NOT EXISTS tenants (
  id SERIAL PRIMARY KEY,
  property_id INT REFERENCES properties(id),
  room_id INT REFERENCES rooms(id),
  name TEXT NOT NULL,
  phone TEXT,
  rent_amount NUMERIC(10,2) NOT NULL DEFAULT 0,
  deposit_paid NUMERIC(10,2) DEFAULT 0,
  check_in_date DATE,
  check_out_date DATE,
  status TEXT DEFAULT 'active', -- active | vacated
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 5. Transactions (all payments)
CREATE TABLE IF NOT EXISTS transactions (
  id SERIAL PRIMARY KEY,
  tenant_id INT REFERENCES tenants(id),
  property_id INT REFERENCES properties(id),
  amount NUMERIC(10,2) NOT NULL,
  txn_type TEXT NOT NULL,        -- rent | deposit | maintenance | other
  payment_mode TEXT DEFAULT 'upi', -- upi | cash | bank
  reference_id TEXT,
  txn_date DATE NOT NULL DEFAULT CURRENT_DATE,
  unique_hash TEXT UNIQUE,       -- prevents duplicates
  confirmed BOOLEAN DEFAULT FALSE,
  notes TEXT,
  logged_by TEXT,                -- phone of who logged it
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 6. Bank Payments (raw UPI/bank imports for reconciliation)
CREATE TABLE IF NOT EXISTS bank_payments (
  id SERIAL PRIMARY KEY,
  property_id INT REFERENCES properties(id),
  amount NUMERIC(10,2) NOT NULL,
  sender_name TEXT,
  reference_id TEXT UNIQUE,
  payment_date DATE,
  matched_tenant_id INT REFERENCES tenants(id),
  match_status TEXT DEFAULT 'pending', -- pending | matched | unmatched
  raw_data JSONB,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- 7. Conversation State (short-term memory, auto-expires in 5 min)
CREATE TABLE IF NOT EXISTS conversation_state (
  id SERIAL PRIMARY KEY,
  phone TEXT NOT NULL UNIQUE,
  state TEXT NOT NULL,           -- AWAIT_CONFIRM_PAYMENT | AWAIT_TENANT_NAME | etc.
  data JSONB DEFAULT '{}',
  expires_at TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '5 minutes')
);

-- 8. Audit Logs
CREATE TABLE IF NOT EXISTS audit_logs (
  id SERIAL PRIMARY KEY,
  action TEXT NOT NULL,
  user_phone TEXT,
  property_id INT,
  details JSONB DEFAULT '{}',
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ============================================================
-- SEED DATA — Replace with your real details before testing
-- ============================================================

-- Insert your PG property
INSERT INTO properties (name, address, owner_phone)
VALUES ('My PG House', '123 Main Street, Bengaluru', '919876543210')
ON CONFLICT DO NOTHING;

-- Add yourself as authorized owner (REPLACE with your WhatsApp number, no +)
-- Format: country code + number, e.g. India +91 9876543210 → 919876543210
INSERT INTO authorized_users (phone, role, property_id)
VALUES ('917845952289', 'owner', 1)
ON CONFLICT (phone) DO NOTHING;

-- Add a test room
INSERT INTO rooms (property_id, room_number, rent_amount, status)
VALUES (1, '101', 8500.00, 'vacant'),
       (1, '102', 9000.00, 'vacant'),
       (1, '103', 8000.00, 'vacant')
ON CONFLICT DO NOTHING;

-- ============================================================
-- INDEXES for fast queries
-- ============================================================
CREATE INDEX IF NOT EXISTS idx_auth_phone ON authorized_users(phone);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON tenants(status);
CREATE INDEX IF NOT EXISTS idx_txn_tenant ON transactions(tenant_id, txn_date);
CREATE INDEX IF NOT EXISTS idx_bank_status ON bank_payments(match_status);
CREATE INDEX IF NOT EXISTS idx_conv_phone ON conversation_state(phone);
CREATE INDEX IF NOT EXISTS idx_conv_expires ON conversation_state(expires_at);
