#!/usr/bin/env bash
# vps_env_set.sh — set/update an env var in the VPS /opt/pg-accountant/.env and
# restart the service. This is how SECRET changes reach production: .env is
# gitignored, so `git push` (which auto-deploys code) NEVER carries it. The
# value is passed at runtime and never committed — no secret ever enters git.
#
# Usage:
#   scripts/vps_env_set.sh KEY "value"
#   scripts/vps_env_set.sh DATABASE_URL "postgresql+asyncpg://..."
#
# Requires: SSH access to the VPS (key ~/.ssh/id_ed25519, verified working).
set -euo pipefail

VPS="root@187.127.130.194"
ENVFILE="/opt/pg-accountant/.env"
SERVICE="pg-accountant"

KEY="${1:?usage: vps_env_set.sh KEY VALUE}"
VALUE="${2:?usage: vps_env_set.sh KEY VALUE}"

# Base64 the value so no quoting/special-char can break the remote shell.
B64=$(printf '%s' "$VALUE" | base64 | tr -d '\n')

ssh -o BatchMode=yes -o ConnectTimeout=15 "$VPS" "
set -e
cp '$ENVFILE' '$ENVFILE.bak.\$(date +%s)'
VAL=\$(printf '%s' '$B64' | base64 -d)
python3 - <<PYEOF
import io,os
p='$ENVFILE'; k='$KEY'; v=os.environ.get('_INJ') or '''\$VAL'''
lines=io.open(p).read().splitlines()
out=[]; found=False
for ln in lines:
    if ln.startswith(k+'=') or ln.startswith(k+' ='):
        out.append(f'{k}=\"{v}\"'); found=True
    else:
        out.append(ln)
if not found: out.append(f'{k}=\"{v}\"')
io.open(p,'w').write('\n'.join(out)+'\n')
print(('updated' if found else 'added')+f' {k}')
PYEOF
systemctl restart '$SERVICE'
sleep 4
echo \"service: \$(systemctl is-active '$SERVICE')\"
"
echo "done — remember to mirror the same change into local .env if it applies there."
