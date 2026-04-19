# Live Sync Apps Script (paste into source sheet)

## What this does
When anyone edits the **April Month Collection** Google Sheet, this script POSTs a webhook to your API. The API debounces bursts of edits into a single sync after 30s of quiet — pulls source → DB → Operations sheet.

## Setup (one-time, 5 min)

1. Open the source sheet: https://docs.google.com/spreadsheets/d/1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0/edit
2. Menu: **Extensions → Apps Script**
3. Delete any existing code, paste this:

```javascript
// Cozeevo live-sync trigger — fires on every cell edit
// Posts to api.getkozzy.com which debounces bursts into one sync.
const SYNC_URL = "https://api.getkozzy.com/api/sync/source-sheet";
const SYNC_TOKEN = "kozzy-sync-2026";  // must match SYNC_WEBHOOK_TOKEN in .env

function onEdit(e) {
  try {
    // Ignore edits outside the Long term tab
    if (!e || !e.source) return;
    const sheetName = e.source.getActiveSheet().getName();
    if (sheetName !== "Long term" && sheetName !== "Day wise") return;

    UrlFetchApp.fetch(SYNC_URL, {
      method: "post",
      headers: {"X-Sync-Token": SYNC_TOKEN, "Content-Type": "application/json"},
      payload: JSON.stringify({
        sheet: sheetName,
        range: e.range ? e.range.getA1Notation() : "",
        user: (e.user || {}).email || "unknown",
      }),
      muteHttpExceptions: true,
    });
  } catch (err) {
    // Fail silently — don't interrupt user's editing
    console.error("Sync webhook failed:", err);
  }
}

// Also sync on structural changes (insert/delete row, paste)
function onChange(e) {
  onEdit(e);
}
```

4. **File → Save** (Ctrl+S)
5. Set up triggers: Click **Triggers** (clock icon, left sidebar) → **Add Trigger**:
   - **Function:** `onEdit`
   - **Event source:** From spreadsheet
   - **Event type:** On edit
   - Save
6. Add another trigger:
   - **Function:** `onChange`
   - **Event type:** On change
   - Save
7. When prompted, authorize the script (one-time Google OAuth).

## How to verify it works

1. Edit any cell in the "Long term" tab (change a cash amount)
2. Wait 30-60 seconds
3. Check API logs (`api.getkozzy.com/healthz` or VPS journal):
   ```
   [SyncWebhook] Running debounced sync
   [SyncWebhook] DB updated from source
   [SyncWebhook] Operations sheet refreshed
   ```
4. Check Cozeevo Operations sheet — the change should appear in the current month's tab

## Safety net

If a single sync detects more than 5 tenant status flips, it:
- Pauses the sync
- Sends a WhatsApp alert to the admin: "⚠️ Live sync detected N status changes. Please verify."

This prevents accidental row deletions from silently wiping tenants.

## Disable live sync

Delete the two triggers in Apps Script → Triggers. Overnight reconciliation (3am daily) continues regardless.

## Manual sync (bypasses debounce)

For testing or after fixing data, force an immediate sync from terminal:

```bash
curl -X POST https://api.getkozzy.com/api/sync/source-sheet/now \
  -H "X-Sync-Token: kozzy-sync-2026"
```

## Environment config

In `.env` on VPS:

```
SYNC_WEBHOOK_TOKEN=kozzy-sync-2026
```

Change this token periodically and update the Apps Script to match.
