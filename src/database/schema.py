"""
Raw SQL DDL for reference and manual migrations.
The ORM (models.py) drives actual table creation via SQLAlchemy.
This file is useful for DB admins and documentation.
"""

SCHEMA_DDL = """
-- ── pg_properties ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pg_properties (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    address     TEXT,
    owner_name  TEXT,
    phone       TEXT,
    total_rooms INTEGER DEFAULT 0,
    active      INTEGER DEFAULT 1,
    created_at  DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- ── categories ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS categories (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,
    parent_id   INTEGER REFERENCES categories(id),
    txn_type    TEXT NOT NULL CHECK(txn_type IN ('income','expense','transfer')),
    description TEXT,
    active      INTEGER DEFAULT 1
);

-- ── customers ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    name          TEXT NOT NULL,
    phone         TEXT UNIQUE,
    upi_id        TEXT,
    room_number   TEXT,
    property_id   INTEGER REFERENCES pg_properties(id),
    rent_amount   NUMERIC(12,2) DEFAULT 0,
    move_in_date  DATE,
    move_out_date DATE,
    active        INTEGER DEFAULT 1,
    notes         TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    confirmed     INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_customers_phone  ON customers(phone);
CREATE INDEX IF NOT EXISTS ix_customers_upi_id ON customers(upi_id);

-- ── vendors ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS vendors (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT NOT NULL,
    phone            TEXT,
    upi_id           TEXT,
    category         TEXT,
    merchant_pattern TEXT,
    active           INTEGER DEFAULT 1,
    notes            TEXT,
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    confirmed        INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_vendors_upi_id ON vendors(upi_id);

-- ── employees ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS employees (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    name           TEXT NOT NULL,
    phone          TEXT,
    upi_id         TEXT,
    role           TEXT,
    monthly_salary NUMERIC(12,2) DEFAULT 0,
    join_date      DATE,
    exit_date      DATE,
    active         INTEGER DEFAULT 1,
    notes          TEXT,
    created_at     DATETIME DEFAULT CURRENT_TIMESTAMP,
    confirmed      INTEGER DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_employees_upi_id ON employees(upi_id);

-- ── transactions (core) ───────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS transactions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date          DATE NOT NULL,
    amount        NUMERIC(14,2) NOT NULL,
    txn_type      TEXT NOT NULL CHECK(txn_type IN ('income','expense','transfer')),
    source        TEXT NOT NULL,
    description   TEXT,
    upi_reference TEXT,
    merchant      TEXT,
    category_id   INTEGER REFERENCES categories(id),
    customer_id   INTEGER REFERENCES customers(id),
    vendor_id     INTEGER REFERENCES vendors(id),
    employee_id   INTEGER REFERENCES employees(id),
    property_id   INTEGER REFERENCES pg_properties(id),
    unique_hash   TEXT UNIQUE NOT NULL,
    raw_data      TEXT,
    ai_classified INTEGER DEFAULT 0,
    confidence    NUMERIC(5,4) DEFAULT 1.0,
    is_void       INTEGER DEFAULT 0,
    notes         TEXT,
    created_at    DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at    DATETIME DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS ix_transactions_date        ON transactions(date);
CREATE INDEX IF NOT EXISTS ix_transactions_category    ON transactions(category_id);
CREATE INDEX IF NOT EXISTS ix_transactions_customer    ON transactions(customer_id);
CREATE INDEX IF NOT EXISTS ix_transactions_vendor      ON transactions(vendor_id);
CREATE INDEX IF NOT EXISTS ix_transactions_employee    ON transactions(employee_id);
CREATE INDEX IF NOT EXISTS ix_transactions_hash        ON transactions(unique_hash);
CREATE INDEX IF NOT EXISTS ix_transactions_type_date   ON transactions(txn_type, date);

-- ── monthly_aggregations ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS monthly_aggregations (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    year         INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    category_id  INTEGER REFERENCES categories(id),
    txn_type     TEXT NOT NULL,
    total_amount NUMERIC(16,2) DEFAULT 0,
    txn_count    INTEGER DEFAULT 0,
    property_id  INTEGER REFERENCES pg_properties(id),
    computed_at  DATETIME DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(year, month, category_id, property_id)
);
CREATE INDEX IF NOT EXISTS ix_monthly_agg_ym ON monthly_aggregations(year, month);

-- ── pending_entities (approval queue) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS pending_entities (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_type      TEXT NOT NULL,
    raw_data         TEXT NOT NULL,
    source_txn_hash  TEXT,
    suggested_by     TEXT DEFAULT 'rules',
    approved         INTEGER,           -- NULL=pending, 1=approved, 0=rejected
    created_at       DATETIME DEFAULT CURRENT_TIMESTAMP,
    resolved_at      DATETIME
);
CREATE INDEX IF NOT EXISTS ix_pending_entity_type ON pending_entities(entity_type);
CREATE INDEX IF NOT EXISTS ix_pending_approved    ON pending_entities(approved);
"""

TRANSACTION_SCHEMA_FIELDS = [
    "date", "amount", "txn_type", "source", "description",
    "upi_reference", "merchant", "category_id", "customer_id",
    "vendor_id", "employee_id", "property_id", "unique_hash",
    "raw_data", "ai_classified", "confidence", "notes",
]
