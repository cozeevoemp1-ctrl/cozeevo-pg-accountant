#!/usr/bin/env python3
import os, sys, psycopg2
from dotenv import load_dotenv
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

load_dotenv()
db_url = os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")
conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Simulate the search_tenants query
term = "301"
cur.execute("""
SELECT
    t.id as tenancy_id,
    tn.id as tenant_id,
    tn.name,
    tn.phone,
    r.room_number,
    p.name as building,
    t.agreed_rent,
    t.status
FROM tenancies t
JOIN tenants tn ON tn.id = t.tenant_id
JOIN rooms r ON r.id = t.room_id
JOIN properties p ON p.id = r.property_id
WHERE t.status IN ('active', 'no_show')
AND (
    LOWER(tn.name) LIKE %s
    OR LOWER(r.room_number) LIKE %s
    OR LOWER(tn.phone) LIKE %s
)
ORDER BY tn.name
LIMIT 10
""", (f"%{term}%", f"%{term}%", f"%{term}%"))

results = cur.fetchall()
print(f"Search results for '{term}': {len(results)} rows\n")
for tenancy_id, tenant_id, name, phone, room, building, rent, status in results:
    print(f"Tenancy {tenancy_id}: {name}, Room {room} ({building}), Rent {rent}, Status {status}")

cur.close()
conn.close()
