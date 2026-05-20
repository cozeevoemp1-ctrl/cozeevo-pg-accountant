import os, requests
from dotenv import load_dotenv
load_dotenv()

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
HEADERS = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Content-Type": "application/json"}
NEW_PW = "Mf3y0302!"

targets = {"krish484@gmail.com", "kirankumarpemmasani@gmail.com"}

resp = requests.get(f"{URL}/auth/v1/admin/users?per_page=1000", headers=HEADERS)
users = resp.json().get("users", [])

found = False
for u in users:
    if u["email"].lower() in targets:
        found = True
        uid = u["id"]
        r = requests.put(f"{URL}/auth/v1/admin/users/{uid}", headers=HEADERS, json={"password": NEW_PW})
        print(f"{u['email']} -> {r.status_code}")
        if r.status_code != 200:
            print(r.text)

if not found:
    print("No matching users found. All users:")
    for u in users:
        print(f"  {u['email']}")
