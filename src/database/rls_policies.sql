-- ============================================================
-- Supabase Row Level Security (RLS) — Cozeevo PG Accountant
-- Run this once in Supabase SQL Editor after tables are created.
-- ============================================================

-- Step 1: Enable pgvector extension (for conversation_memory)
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 2: Enable RLS on all sensitive tables
ALTER TABLE tenants          ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenancies        ENABLE ROW LEVEL SECURITY;
ALTER TABLE rent_schedule    ENABLE ROW LEVEL SECURITY;
ALTER TABLE payments         ENABLE ROW LEVEL SECURITY;
ALTER TABLE refunds          ENABLE ROW LEVEL SECURITY;
ALTER TABLE expenses         ENABLE ROW LEVEL SECURITY;
ALTER TABLE authorized_users ENABLE ROW LEVEL SECURITY;
ALTER TABLE whatsapp_log     ENABLE ROW LEVEL SECURITY;
ALTER TABLE conversation_memory ENABLE ROW LEVEL SECURITY;

-- Tables that are read-only public (no sensitive data):
-- properties, rooms, rate_cards, food_plans, expense_categories
-- leads, rate_limit_log, vacations, reminders — managed by service role

-- ── Helper: get the current caller's role from authorized_users ──────────
-- Called as: get_caller_role('+917845952289')
CREATE OR REPLACE FUNCTION get_caller_role(caller_phone TEXT)
RETURNS TEXT AS $$
  SELECT role FROM authorized_users
  WHERE phone = caller_phone AND active = TRUE
  LIMIT 1;
$$ LANGUAGE sql STABLE SECURITY DEFINER;


-- ============================================================
-- POLICY: authorized_users
-- Only ADMIN can see and modify this table.
-- ============================================================
CREATE POLICY "admin_full_access_authorized_users"
ON authorized_users
FOR ALL
USING (
  get_caller_role(current_setting('app.caller_phone', TRUE)) = 'admin'
);


-- ============================================================
-- POLICY: tenants
-- ADMIN + POWER_USER → all tenants
-- KEY_USER → only tenants in their property
-- END_USER (tenant) → only their own row
-- ============================================================
CREATE POLICY "admin_power_see_all_tenants"
ON tenants FOR SELECT
USING (
  get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user')
);

CREATE POLICY "key_user_see_property_tenants"
ON tenants FOR SELECT
USING (
  get_caller_role(current_setting('app.caller_phone', TRUE)) = 'key_user'
  AND EXISTS (
    SELECT 1 FROM tenancies t
    JOIN rooms r ON t.room_id = r.id
    JOIN authorized_users au ON au.phone = current_setting('app.caller_phone', TRUE)
    WHERE t.tenant_id = tenants.id AND r.property_id = au.property_id
  )
);

CREATE POLICY "tenant_see_own_record"
ON tenants FOR SELECT
USING (
  phone = current_setting('app.caller_phone', TRUE)
);


-- ============================================================
-- POLICY: tenancies + rent_schedule + payments + refunds
-- Same hierarchy: admin/power → all | key → property | tenant → own
-- ============================================================

-- tenancies
CREATE POLICY "admin_power_see_all_tenancies"    ON tenancies FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "tenant_see_own_tenancies"         ON tenancies FOR SELECT USING (EXISTS (SELECT 1 FROM tenants WHERE tenants.id = tenancies.tenant_id AND tenants.phone = current_setting('app.caller_phone', TRUE)));

-- rent_schedule
CREATE POLICY "admin_power_see_all_rent"         ON rent_schedule FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "tenant_see_own_rent"              ON rent_schedule FOR SELECT USING (EXISTS (SELECT 1 FROM tenancies t JOIN tenants tn ON t.tenant_id = tn.id WHERE t.id = rent_schedule.tenancy_id AND tn.phone = current_setting('app.caller_phone', TRUE)));

-- payments
CREATE POLICY "admin_power_see_all_payments"     ON payments FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "tenant_see_own_payments"          ON payments FOR SELECT USING (EXISTS (SELECT 1 FROM tenancies t JOIN tenants tn ON t.tenant_id = tn.id WHERE t.id = payments.tenancy_id AND tn.phone = current_setting('app.caller_phone', TRUE)));

-- refunds
CREATE POLICY "admin_power_see_all_refunds"      ON refunds FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "tenant_see_own_refunds"           ON refunds FOR SELECT USING (EXISTS (SELECT 1 FROM tenancies t JOIN tenants tn ON t.tenant_id = tn.id WHERE t.id = refunds.tenancy_id AND tn.phone = current_setting('app.caller_phone', TRUE)));


-- ============================================================
-- POLICY: expenses — business data, no tenant access
-- ============================================================
CREATE POLICY "admin_power_key_see_expenses"
ON expenses FOR SELECT
USING (
  get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user', 'key_user')
);


-- ============================================================
-- POLICY: whatsapp_log + conversation_memory
-- Only admin and power_user can audit the full log.
-- Each phone can see their own conversation.
-- ============================================================
CREATE POLICY "admin_power_see_all_log"          ON whatsapp_log FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "see_own_log"                      ON whatsapp_log FOR SELECT USING (from_number = current_setting('app.caller_phone', TRUE));

CREATE POLICY "admin_power_see_all_memory"       ON conversation_memory FOR SELECT USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "see_own_memory"                   ON conversation_memory FOR SELECT USING (phone = current_setting('app.caller_phone', TRUE));


-- ============================================================
-- WRITE policies: only admin + power_user can INSERT/UPDATE/DELETE
-- (Tenants are read-only. Service role used by FastAPI bypasses RLS.)
-- ============================================================
CREATE POLICY "admin_power_write_tenants"        ON tenants        FOR ALL USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "admin_power_write_tenancies"      ON tenancies      FOR ALL USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "admin_power_write_payments"       ON payments       FOR ALL USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "admin_power_write_expenses"       ON expenses       FOR ALL USING (get_caller_role(current_setting('app.caller_phone', TRUE)) IN ('admin', 'power_user'));
CREATE POLICY "admin_only_write_authorized"      ON authorized_users FOR ALL USING (get_caller_role(current_setting('app.caller_phone', TRUE)) = 'admin');


-- ============================================================
-- pgvector: IVFFlat index on conversation_memory for fast similarity search
-- Run after you have at least 1000 rows of data.
-- ============================================================
-- CREATE INDEX ON conversation_memory USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================
-- Done. Test with:
-- SET app.caller_phone = '+917845952289';
-- SELECT * FROM authorized_users;  -- should return all rows (admin)
-- SET app.caller_phone = '+919876543210';  -- a tenant phone
-- SELECT * FROM tenants;  -- should return only their own row
-- ============================================================
