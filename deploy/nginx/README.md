# Tenant links come from cozeevo.com

**Why:** the onboarding link used to be `https://api.getkozzy.com/onboard/{token}` —
an API hostname in a customer's hands. BRAIN §15a: a customer never sees our
infrastructure. Links now read:

```
https://cozeevo.com/join/<token>
```

`cozeevo.com` serves **only** the form. No PWA, no API surface, no admin routes —
everything else on that hostname returns 404.

## Already done (in code, deployed)

- `/join/{token}` serves the form; `/onboard/{token}` kept forever so links
  already sent on api.getkozzy.com keep working (`main.py:267`).
- Link generation switched to `/join/` in all three places that build it
  (`onboarding_router.py:300,877`, `bookings.py:333`).
- The host in those links is `BASE_URL`, so the final switch is one env var.

## To apply (needs DNS + VPS access)

```bash
# 1. DNS, in the Hostinger account that holds cozeevo.com
#    A     cozeevo.com       -> 187.127.130.194
#    A     www.cozeevo.com   -> 187.127.130.194
#    (replaces the parked-domain page; allow a few minutes)

# 2. nginx + certificate, on the VPS
cp /opt/pg-accountant/deploy/nginx/cozeevo.com.conf /etc/nginx/sites-available/cozeevo.com
ln -sf /etc/nginx/sites-available/cozeevo.com /etc/nginx/sites-enabled/cozeevo.com
nginx -t && systemctl reload nginx
certbot --nginx -d cozeevo.com -d www.cozeevo.com      # free, auto-renews

# 3. point new links at it
cd /opt/pg-accountant && bash scripts/vps_env_set.sh BASE_URL "https://cozeevo.com"
```

Step 3 restarts pg-accountant itself. Do it **last** — until then links still
generate on api.getkozzy.com, which works fine with the new `/join/` path.

## Verify

```bash
curl -s -o /dev/null -w "%{http_code}\n" https://cozeevo.com/join/<live-token>   # 200
curl -s -o /dev/null -w "%{http_code}\n" https://cozeevo.com/static/logo.svg     # 200
curl -s -o /dev/null -w "%{http_code}\n" https://cozeevo.com/api/v2/app/config   # 404 (closed)
curl -s -o /dev/null -w "%{http_code}\n" https://cozeevo.com/tenants             # 404 (closed)
```

Then make one pre-booking and check the WhatsApp link reads `cozeevo.com/join/...`.

## Rollback

`bash scripts/vps_env_set.sh BASE_URL "https://api.getkozzy.com"` — links revert
immediately. The nginx block can stay; it serves nothing until BASE_URL points at it.
