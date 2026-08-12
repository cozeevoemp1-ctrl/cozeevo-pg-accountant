"""
One-off (C-1): flip the tenant-PII Supabase Storage buckets from public → private.

Run AFTER the signed-URL code is deployed (signed URLs work on public buckets
too, so deploying first is safe; flipping first would break live agreement sends
until the new code lands).

    python scripts/_flip_buckets_private.py            # show current state
    python scripts/_flip_buckets_private.py --write    # flip to private
    python scripts/_flip_buckets_private.py --verify    # prove public 403s, signed 200s

Idempotent — safe to re-run.
"""
import argparse
import os

import requests
from dotenv import load_dotenv

load_dotenv()

URL = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_SERVICE_KEY"]
H = {"Authorization": f"Bearer {KEY}", "apikey": KEY, "Content-Type": "application/json"}
BUCKETS = ["kyc-documents", "agreements", "receipts"]


def state():
    r = requests.get(f"{URL}/storage/v1/bucket", headers=H, timeout=15)
    return {b["id"]: b.get("public") for b in r.json()}


def flip(write: bool):
    cur = state()
    for b in BUCKETS:
        if b not in cur:
            print(f"  SKIP {b}: does not exist yet (born private on first upload)")
            continue
        if cur[b] is False:
            print(f"  SKIP {b}: already private")
            continue
        if not write:
            print(f"  [DRY RUN] would set {b} public=False")
            continue
        r = requests.put(f"{URL}/storage/v1/bucket/{b}", headers=H, json={"public": False}, timeout=15)
        r.raise_for_status()
        print(f"  FLIPPED {b} -> private")


def verify():
    """Pick one real object per existing bucket; prove public 403s and signed 200s."""
    for b in [x for x in BUCKETS if x in state()]:
        lr = requests.post(f"{URL}/storage/v1/object/list/{b}", headers=H,
                           json={"limit": 100, "prefix": ""}, timeout=15)
        # descend one level to find a file
        path = None
        for top in lr.json():
            if top.get("id"):
                path = top["name"]
                break
            sub = requests.post(f"{URL}/storage/v1/object/list/{b}", headers=H,
                                json={"limit": 100, "prefix": top["name"]}, timeout=15)
            for o in sub.json():
                if o.get("id"):
                    path = f"{top['name']}/{o['name']}"
                    break
            if path:
                break
        if not path:
            print(f"  {b}: no objects to test")
            continue
        pub = requests.get(f"{URL}/storage/v1/object/public/{b}/{path}", timeout=15)
        s = requests.post(f"{URL}/storage/v1/object/sign/{b}/{path}", headers=H,
                          json={"expiresIn": 3600}, timeout=15)
        signed = f"{URL}/storage/v1" + s.json()["signedURL"] if s.status_code == 200 else None
        sg = requests.get(signed, timeout=15).status_code if signed else "n/a"
        verdict = "OK (locked)" if pub.status_code in (400, 403) else "!!! STILL PUBLIC !!!"
        print(f"  {b}/{path[:40]}...  public={pub.status_code} signed={sg}  -> {verdict}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()
    print("Current bucket state:", state())
    if args.verify:
        print("Verifying access control:")
        verify()
        return
    flip(args.write)
    if not args.write:
        print("\nDry run. Re-run with --write to flip, then --verify to confirm.")
    else:
        print("Done. Run with --verify to confirm public URLs now 403.")


if __name__ == "__main__":
    main()
