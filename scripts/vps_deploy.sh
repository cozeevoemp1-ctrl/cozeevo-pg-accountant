#!/bin/bash
# /opt/deploy.sh — zero-downtime deploy with concurrent-build protection
# Bootstrap: cp /opt/pg-accountant/scripts/vps_deploy.sh /opt/deploy.sh && chmod +x /opt/deploy.sh

set -e

LOCK=/var/lock/kozzy-deploy.lock
LOG=/tmp/deploy.log

(
  flock -n 9 || { echo "$(date): deploy already running, skipping" >> "$LOG"; exit 0; }

  echo "$(date): deploy started" >> "$LOG"
  cd /opt/pg-accountant

  git pull >> "$LOG" 2>&1

  # Always restart the API
  systemctl restart pg-accountant >> "$LOG" 2>&1
  echo "$(date): pg-accountant restarted" >> "$LOG"

  # Only rebuild PWA if web/ changed
  if git diff --name-only HEAD@{1} HEAD 2>/dev/null | grep -q '^web/'; then
    echo "$(date): web/ changed — building PWA" >> "$LOG"
    cd web
    npm run build >> "$LOG" 2>&1
    systemctl restart kozzy-pwa >> "$LOG" 2>&1
    echo "$(date): kozzy-pwa restarted" >> "$LOG"
  fi

  echo "$(date): deploy done" >> "$LOG"
) 9>"$LOCK"
