#!/bin/bash
# /opt/deploy.sh — zero-downtime deploy with concurrent-build protection
# Bootstrap: cp /opt/pg-accountant/scripts/vps_deploy.sh /opt/deploy.sh && chmod +x /opt/deploy.sh
#
# A push that lands while a deploy is running is QUEUED, never dropped: it sets
# $PENDING, waits on the lock, and the running deploy loops until no push is
# outstanding — so back-to-back pushes collapse into extra pulls. (Pushing
# development then master back-to-back used to skip the master deploy — the
# webhook fires for every branch, and the second call hit the lock.)

set -e

LOCK=/var/lock/kozzy-deploy.lock
PENDING=/var/lock/kozzy-deploy.pending
LOG=/tmp/deploy.log

touch "$PENDING"

(
  # Block (don't skip) — a running deploy usually consumes our $PENDING; if it
  # finished just before we touched it, we run it ourselves once the lock frees.
  flock 9

  cd /opt/pg-accountant
  while [ -e "$PENDING" ]; do
    rm -f "$PENDING"
    echo "$(date): deploy started" >> "$LOG"

    BEFORE=$(git rev-parse HEAD)
    git pull >> "$LOG" 2>&1
    AFTER=$(git rev-parse HEAD)

    # Always restart the API
    systemctl restart pg-accountant >> "$LOG" 2>&1
    echo "$(date): pg-accountant restarted at ${AFTER:0:7}" >> "$LOG"

    # Only rebuild PWA if web/ changed
    if [ "$BEFORE" != "$AFTER" ] && git diff --name-only "$BEFORE" "$AFTER" | grep -q '^web/'; then
      echo "$(date): web/ changed — building PWA" >> "$LOG"
      (cd web && npm run build >> "$LOG" 2>&1)
      systemctl restart kozzy-pwa >> "$LOG" 2>&1
      echo "$(date): kozzy-pwa restarted" >> "$LOG"
    fi

    echo "$(date): deploy done" >> "$LOG"
  done
) 9>"$LOCK"
