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

# Find Anshsinha
cur.execute("SELECT t.id, tn.name, r.room_number, t.status, t.checkin_date FROM tenancies t JOIN tenants tn ON t.tenant_id = tn.id JOIN rooms r ON t.room_id = r.id WHERE LOWER(tn.name) LIKE '%anshsinha%' ORDER BY t.checkin_date")
results = cur.fetchall()
print(f"Anshsinha tenancies: {len(results)}")
for tid, name, room, status, checkin in results:
    print(f"  Tenancy {tid}: {name}, Room {room}, Status {status}, Checkin {checkin}")

# Find Nagarajan.P
cur.execute("SELECT t.id, tn.name, r.room_number, t.status, t.checkin_date FROM tenancies t JOIN tenants tn ON t.tenant_id = tn.id JOIN rooms r ON t.room_id = r.id WHERE LOWER(tn.name) LIKE '%nagarajan%' ORDER BY t.checkin_date")
results = cur.fetchall()
print(f"\nNagarajan.P tenancies: {len(results)}")
for tid, name, room, status, checkin in results:
    print(f"  Tenancy {tid}: {name}, Room {room}, Status {status}, Checkin {checkin}")

cur.close()
conn.close()
