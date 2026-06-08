#!/usr/bin/env python3
"""
Directly fix duplicate tenancies using DATABASE_URL from .env
"""
import os
import sys
import psycopg2
from dotenv import load_dotenv

# Fix Unicode encoding on Windows
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
db_url = os.getenv("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not in .env")
    exit(1)

# Convert async URL to sync
db_url = db_url.replace("postgresql+asyncpg://", "postgresql://")

# Connect to database
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Step 1: Find duplicates
print("\n=== STEP 1: Finding duplicate tenancies ===\n")
cur.execute("""
WITH duplicates AS (
    SELECT tenant_id, room_id, COUNT(*) as cnt
    FROM tenancies
    WHERE status = 'active'
    GROUP BY tenant_id, room_id
    HAVING COUNT(*) > 1
),
ranked AS (
    SELECT
        t.id,
        t.tenant_id,
        t.room_id,
        t.checkin_date,
        t.created_at,
        ROW_NUMBER() OVER (PARTITION BY t.tenant_id, t.room_id ORDER BY t.checkin_date ASC, t.created_at ASC) as rn
    FROM tenancies t
    WHERE EXISTS (SELECT 1 FROM duplicates d WHERE d.tenant_id = t.tenant_id AND d.room_id = t.room_id)
    AND t.status = 'active'
)
SELECT id, tenant_id, room_id, checkin_date, created_at, rn
FROM ranked
ORDER BY tenant_id, room_id, rn
""")

results = cur.fetchall()
if not results:
    print("✓ No duplicate tenancies found!")
    cur.close()
    conn.close()
    exit(0)

print(f"Found {len(results)} tenancy records in duplicate groups:\n")
for row in results:
    tid, tenant_id, room_id, checkin_date, created_at, rn = row
    status = "KEEP" if rn == 1 else "CANCEL"
    print(f"  [{status}] Tenancy {tid}: Tenant {tenant_id}, Room {room_id}, Checkin {checkin_date}, Created {created_at}, Rank {rn}")

# Step 2: Cancel the duplicates
print("\n=== STEP 2: Cancelling duplicates (keeping earliest for each tenant/room pair) ===\n")

cur.execute("""
WITH duplicates AS (
    SELECT tenant_id, room_id, COUNT(*) as cnt
    FROM tenancies
    WHERE status = 'active'
    GROUP BY tenant_id, room_id
    HAVING COUNT(*) > 1
),
ranked AS (
    SELECT
        t.id,
        t.tenant_id,
        t.room_id,
        t.checkin_date,
        t.created_at,
        ROW_NUMBER() OVER (PARTITION BY t.tenant_id, t.room_id ORDER BY t.checkin_date ASC, t.created_at ASC) as rn
    FROM tenancies t
    WHERE EXISTS (SELECT 1 FROM duplicates d WHERE d.tenant_id = t.tenant_id AND d.room_id = t.room_id)
    AND t.status = 'active'
)
UPDATE tenancies
SET status = 'cancelled'
WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
RETURNING id
""")

cancelled = cur.fetchall()
print(f"✓ Cancelled {len(cancelled)} duplicate tenancy records:")
for (tid,) in cancelled:
    print(f"  - Tenancy {tid}")

# Step 3: Log the action
print("\n=== STEP 3: Logging audit entries ===\n")

cur.execute("""
WITH duplicates AS (
    SELECT tenant_id, room_id, COUNT(*) as cnt
    FROM tenancies
    WHERE status = 'active'
    GROUP BY tenant_id, room_id
    HAVING COUNT(*) > 1
),
ranked AS (
    SELECT
        t.id,
        t.tenant_id,
        t.room_id,
        ROW_NUMBER() OVER (PARTITION BY t.tenant_id, t.room_id ORDER BY t.checkin_date ASC, t.created_at ASC) as rn
    FROM tenancies t
    WHERE EXISTS (SELECT 1 FROM duplicates d WHERE d.tenant_id = t.tenant_id AND d.room_id = t.room_id)
    AND t.status = 'cancelled'
)
INSERT INTO audit_log (changed_by, entity_type, entity_id, entity_name, field, old_value, new_value, source, org_id, created_at)
SELECT
    'run_duplicate_fix.py',
    'tenancy',
    t.id,
    'Tenant ' || t.tenant_id || ', Room ' || r.room_number,
    'status',
    'active',
    'cancelled',
    'script',
    t.org_id,
    NOW()
FROM tenancies t
JOIN rooms r ON r.id = t.room_id
WHERE t.status = 'cancelled'
AND t.id IN (SELECT id FROM ranked WHERE rn > 1)
RETURNING id
""")

logged = cur.fetchall()
print(f"✓ Logged {len(logged)} audit entries")

# Commit all changes
conn.commit()
print("\n=== ALL DONE ===")
print("✓ Duplicate tenancies fixed and logged")

cur.close()
conn.close()
