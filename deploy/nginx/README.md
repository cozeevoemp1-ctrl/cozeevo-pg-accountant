# Serving the onboarding form from the app domain

**Why:** the tenant's onboarding link was `https://api.getkozzy.com/onboard/{token}` —
an API hostname in a customer's hands. BRAIN §15a: a customer never sees our
infrastructure. New links become `https://app.getkozzy.com/onboard/{token}`.

The whole switch is one env var (`BASE_URL`, read by
`onboarding_router.py:299/876` and `bookings.py:332`) plus three nginx locations.
Links already issued on `api.getkozzy.com` keep working — that server block is
untouched — so nothing in flight breaks.

## Apply (VPS, ~1 minute)

```bash
# 1. nginx — copy the three locations from this repo's app.getkozzy.com.conf
cp /etc/nginx/sites-enabled/kozzy-pwa /root/kozzy-pwa.bak
cp /opt/pg-accountant/deploy/nginx/app.getkozzy.com.conf /etc/nginx/sites-enabled/kozzy-pwa
nginx -t && systemctl reload nginx

# 2. point new links at the app domain
cd /opt/pg-accountant && bash scripts/vps_env_set.sh BASE_URL "https://app.getkozzy.com"
```

`vps_env_set.sh` restarts pg-accountant itself.

## Verify

```bash
# form loads with no login, logo included
curl -s -o /dev/null -w "%{http_code}\n" https://app.getkozzy.com/onboard/<any-live-token>   # 200
curl -s -o /dev/null -w "%{http_code}\n" https://app.getkozzy.com/static/logo.svg            # 200
# PWA still behind auth
curl -s -o /dev/null -w "%{http_code}\n" https://app.getkozzy.com/tenants                    # 307 -> /login
```

Then create one pre-booking and check the WhatsApp link now reads `app.getkozzy.com`.

## Rollback

`cp /root/kozzy-pwa.bak /etc/nginx/sites-enabled/kozzy-pwa && nginx -t && systemctl reload nginx`,
and `vps_env_set.sh BASE_URL "https://api.getkozzy.com"`.
