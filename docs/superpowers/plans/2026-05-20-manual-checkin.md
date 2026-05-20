# Manual Check-in Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a "Manual check-in" path on the Bookings PWA page so staff can enter KYC details on behalf of a tenant and complete check-in without the tenant filling their own form link.

**Architecture:** New backend endpoint `POST /api/onboarding/{token}/manual-checkin` accepts KYC + collection amounts, patches `tenant_data` + promotes session to `pending_review` in one DB transaction, then delegates to the existing `_approve_session_impl` which handles all tenancy/payment creation. Frontend adds an inline KYC form panel on `pending_tenant` and `expired` cards.

**Tech Stack:** FastAPI + Pydantic (backend), Next.js/React with Tailwind (frontend). No new dependencies.

---

## File Map

| File | Change |
|------|--------|
| `src/api/onboarding_router.py` | Add `ManualCheckinRequest` model + `POST /{token}/manual-checkin` route (~60 lines) |
| `web/app/onboarding/bookings/page.tsx` | Add `ManualCheckinPanel` component + wire button into `BookingCard` |

---

## Task 1: Backend — `ManualCheckinRequest` model + endpoint

**Files:**
- Modify: `src/api/onboarding_router.py` (add after line ~1202, the `ApproveRequest` class)

### Context

`_approve_session_impl` (line 1257) opens its own DB session, reads `obs`, then expects `obs.status == "pending_review"` and `obs.tenant_data` to be a JSON string with at minimum `name` and `phone` keys. Our new endpoint will:

1. Open a session → validate status → build `tenant_data` dict → write to obs → set `obs.status = "pending_review"` → commit.
2. Then call `_approve_session_impl(token, approve_req)` which opens a fresh session and does all the heavy lifting (creates Tenant, Tenancy, RentSchedule, Payment rows, writes to GSheets).

- [ ] **Step 1: Add `ManualCheckinRequest` model**

In `src/api/onboarding_router.py`, immediately after the closing brace of `class ApproveRequest` (line ~1202), add:

```python
class ManualCheckinRequest(BaseModel):
    # KYC — name and phone come from the session; staff fills the rest
    gender: str                              # "Male" | "Female" | "Other"
    food_preference: str                     # "Veg" | "Non-Veg"
    emergency_contact_name: str
    emergency_contact_phone: str
    emergency_contact_relationship: str
    date_of_birth: str = ""
    id_proof_type: str = ""
    id_proof_number: str = ""
    permanent_address: str = ""
    occupation: str = ""
    # Collection at check-in (same fields as ApproveRequest)
    collected_rent_dues: float = 0
    rent_dues_mode: str = "cash"             # "cash" | "upi"
    collected_deposit_dues: float = 0        # always UPI
```

- [ ] **Step 2: Add the route handler after `approve_session`**

In `src/api/onboarding_router.py`, add the following after the `approve_session` function (after line ~1254):

```python
@router.post("/{token}/manual-checkin")
async def manual_checkin(token: str, request: Request, req: ManualCheckinRequest):
    """
    Staff-entered KYC + immediate check-in for tenants who won't fill the form.
    Works for pending_tenant and expired sessions.
    """
    _check_admin_pin(request)
    # Phase 1: patch tenant_data + promote session to pending_review
    async with get_session() as session:
        obs = await session.scalar(select(OnboardingSession).where(OnboardingSession.token == token))
        if not obs:
            raise HTTPException(404, "Session not found")
        if obs.status not in ("pending_tenant", "expired"):
            raise HTTPException(400, f"Manual check-in only allowed for pending_tenant or expired sessions (current: {obs.status})")

        tenant_data = {
            "name": obs.tenant_name or "",
            "phone": obs.tenant_phone or "",
            "gender": req.gender,
            "food_preference": req.food_preference,
            "emergency_contact_name": req.emergency_contact_name,
            "emergency_contact_phone": req.emergency_contact_phone,
            "emergency_contact_relationship": req.emergency_contact_relationship,
            "date_of_birth": req.date_of_birth,
            "id_proof_type": req.id_proof_type,
            "id_proof_number": req.id_proof_number,
            "permanent_address": req.permanent_address,
            "occupation": req.occupation,
            "saved_files": {},  # no file uploads for manual entry
        }
        obs.tenant_data = json.dumps(tenant_data)
        obs.status = "pending_review"
        await session.commit()

    # Phase 2: reuse existing approve logic (opens its own session)
    approve_req = ApproveRequest(
        instant_checkin=True,
        entry_source="manual_entry",
        collected_rent_dues=req.collected_rent_dues,
        rent_dues_mode=req.rent_dues_mode,
        collected_deposit_dues=req.collected_deposit_dues,
    )
    try:
        return await _approve_session_impl(token, approve_req)
    except HTTPException:
        raise
    except Exception as e:
        import logging, traceback
        logging.getLogger(__name__).error(
            "Manual check-in failed for token %s: %s\n%s", token[:8], e, traceback.format_exc()
        )
        raise HTTPException(500, f"Manual check-in failed: {type(e).__name__}: {e}")
```

- [ ] **Step 3: Verify `tenant_name` exists on `OnboardingSession` model**

Run:
```bash
grep -n "tenant_name\|tenant_phone" src/database/models.py | head -10
```

Expected: both `tenant_name` and `tenant_phone` are columns on `OnboardingSession`. If `tenant_name` is missing, replace `obs.tenant_name` with `(json.loads(obs.tenant_data) if obs.tenant_data else {}).get("name", "")` in the tenant_data dict above.

- [ ] **Step 4: Smoke-test the backend endpoint with curl**

Start the API:
```bash
venv/Scripts/python main.py
```

In a second terminal, first get a real `pending_tenant` token:
```bash
venv/Scripts/python -c "
import asyncio, os; from dotenv import load_dotenv; load_dotenv()
import asyncpg
async def run():
    conn = await asyncpg.connect(os.getenv('DATABASE_URL').replace('postgresql+asyncpg','postgresql'))
    r = await conn.fetchrow(\"SELECT token FROM onboarding_sessions WHERE status='pending_tenant' LIMIT 1\")
    print(r['token'] if r else 'no pending_tenant session')
    await conn.close()
asyncio.run(run())
"
```

Then test (replace `<TOKEN>` and use the actual admin PIN):
```bash
curl -s -X POST http://localhost:8000/api/onboarding/<TOKEN>/manual-checkin \
  -H "Content-Type: application/json" \
  -H "X-Admin-Pin: cozeevo2026" \
  -d '{
    "gender": "Male",
    "food_preference": "Veg",
    "emergency_contact_name": "Test Parent",
    "emergency_contact_phone": "9999999999",
    "emergency_contact_relationship": "Parent",
    "collected_rent_dues": 0,
    "collected_deposit_dues": 0
  }' | python -m json.tool
```

Expected: `{"status": "approved", "tenant_id": ..., "tenancy_id": ...}` (same shape as approve response).
Expected failure mode: `{"detail": "Manual check-in only allowed for pending_tenant or expired sessions"}` if wrong status.

- [ ] **Step 5: Commit backend**

```bash
git add src/api/onboarding_router.py
git commit -m "feat(onboarding): add manual-checkin endpoint for staff-entered KYC"
```

---

## Task 2: Frontend — Manual Check-in panel in BookingCard

**Files:**
- Modify: `web/app/onboarding/bookings/page.tsx`

### Context

`BookingCard` is a self-contained component starting at line 272. It already has `editing` state for the edit panel and `expanded` state for the collection panel on `pending_review` cards. We add a `manualOpen` boolean state; when true, render a new `ManualCheckinPanel` section below the existing action row. The "Manual check-in" button appears on `isPending` and `isExpired` cards only.

The new panel needs to POST to `/api/onboarding/{token}/manual-checkin` with the admin PIN header (same `pinHeaders()` used throughout).

- [ ] **Step 1: Add `manualCheckin` API function at the top of the component file**

In `web/app/onboarding/bookings/page.tsx`, add after the `saveAndCheckin` function (around line 127):

```typescript
async function manualCheckinApi(token: string, body: {
  gender: string
  food_preference: string
  emergency_contact_name: string
  emergency_contact_phone: string
  emergency_contact_relationship: string
  date_of_birth?: string
  id_proof_type?: string
  id_proof_number?: string
  permanent_address?: string
  occupation?: string
  collected_rent_dues: number
  rent_dues_mode: string
  collected_deposit_dues: number
}) {
  const res = await fetch(`${API_URL}/api/onboarding/${token}/manual-checkin`, {
    method: "POST",
    headers: pinHeaders(),
    body: JSON.stringify(body),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail ?? `Error ${res.status}`)
  }
  return res.json()
}
```

- [ ] **Step 2: Add state + form fields to `BookingCard`**

Inside `BookingCard`, after the existing `resending` state declaration (around line 291), add:

```typescript
const [manualOpen, setManualOpen] = useState(false)
const [manualSaving, setManualSaving] = useState(false)

// Manual check-in KYC fields
const [mGender, setMGender] = useState("")
const [mFood, setMFood] = useState("Veg")
const [mEcName, setMEcName] = useState("")
const [mEcPhone, setMEcPhone] = useState("")
const [mEcRel, setMEcRel] = useState("")
const [mDob, setMDob] = useState("")
const [mIdType, setMIdType] = useState("")
const [mIdNum, setMIdNum] = useState("")
const [mAddress, setMAddress] = useState("")
const [mOccupation, setMOccupation] = useState("")
const [mRentDues, setMRentDues] = useState("")
const [mRentMode, setMRentMode] = useState<"cash" | "upi">("cash")
const [mDepDues, setMDepDues] = useState("")
```

- [ ] **Step 3: Pre-fill collection amounts when manual panel opens**

Add a `useEffect` that fires when `manualOpen` becomes true, mirroring the `prefillDone` effect for `pending_review` cards:

```typescript
useEffect(() => {
  if (!manualOpen) return
  // Pre-fill collection defaults same as pending_review path
  const rentDue = proRata
  const depositDue = Math.max(0, (b.security_deposit || 0) - (b.booking_amount || 0))
  if (rentDue > 0) setMRentDues(String(rentDue))
  if (depositDue > 0) setMDepDues(String(depositDue))
// eslint-disable-next-line react-hooks/exhaustive-deps
}, [manualOpen])
```

- [ ] **Step 4: Add `doManualCheckin` handler**

Inside `BookingCard`, add:

```typescript
async function doManualCheckin() {
  if (!mGender || !mFood || !mEcName || !mEcPhone || !mEcRel) {
    setErr("Gender, food preference, and all emergency contact fields are required.")
    return
  }
  setManualSaving(true)
  setErr("")
  try {
    await manualCheckinApi(b.token, {
      gender: mGender,
      food_preference: mFood,
      emergency_contact_name: mEcName,
      emergency_contact_phone: mEcPhone,
      emergency_contact_relationship: mEcRel,
      date_of_birth: mDob || undefined,
      id_proof_type: mIdType || undefined,
      id_proof_number: mIdNum || undefined,
      permanent_address: mAddress || undefined,
      occupation: mOccupation || undefined,
      collected_rent_dues: parseFloat(mRentDues) || 0,
      rent_dues_mode: mRentMode,
      collected_deposit_dues: parseFloat(mDepDues) || 0,
    })
    onReload()
  } catch (e) {
    setErr(e instanceof Error ? e.message : "Manual check-in failed")
  } finally {
    setManualSaving(false)
  }
}
```

- [ ] **Step 5: Add "Manual check-in" button to the action row**

In the `isPending` action row section (around line 636, the `/* Awaiting form */` comment block), add a "Manual check-in" button as the last item in the flex row:

```typescript
<button
  onClick={() => { setManualOpen(v => !v); setEditing(false); setCancelConfirm(false); setErr("") }}
  className="w-full rounded-pill border border-[#6B7280] py-2.5 text-xs font-semibold text-[#6B7280] active:opacity-70"
>
  {manualOpen ? "▲ Close manual entry" : "Manual check-in ↓"}
</button>
```

Do the same for the `isExpired` action row (around line 616), add the same button as the last item.

- [ ] **Step 6: Render the `ManualCheckinPanel` below the action row**

After the closing `</div>` of the action row (the `{!editing && (` block, around line 717), add:

```tsx
{/* Manual check-in — KYC entry by staff */}
{manualOpen && (isPending || isExpired) && (
  <div className="border-t border-[#F0EDE9] pt-3 flex flex-col gap-2">
    <p className="text-[10px] font-bold text-ink-muted uppercase tracking-wide">
      Manual check-in — enter tenant details
    </p>

    {/* Personal */}
    <div className="grid grid-cols-2 gap-2">
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Gender *</label>
        <select value={mGender} onChange={e => setMGender(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink">
          <option value="">Select…</option>
          <option value="Male">Male</option>
          <option value="Female">Female</option>
          <option value="Other">Other</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Food *</label>
        <select value={mFood} onChange={e => setMFood(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink">
          <option value="Veg">Veg</option>
          <option value="Non-Veg">Non-Veg</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Date of Birth</label>
        <input type="date" value={mDob} onChange={e => setMDob(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Occupation</label>
        <input type="text" value={mOccupation} onChange={e => setMOccupation(e.target.value)} placeholder="e.g. Engineer"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
    </div>

    {/* Emergency contact */}
    <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mt-1">Emergency contact *</p>
    <div className="grid grid-cols-2 gap-2">
      <div className="col-span-2">
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Name *</label>
        <input type="text" value={mEcName} onChange={e => setMEcName(e.target.value)} placeholder="Full name"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Phone *</label>
        <input type="tel" value={mEcPhone} onChange={e => setMEcPhone(e.target.value)} placeholder="10 digits"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Relation *</label>
        <input type="text" value={mEcRel} onChange={e => setMEcRel(e.target.value)} placeholder="e.g. Parent"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
    </div>

    {/* ID + address */}
    <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mt-1">ID & Address</p>
    <div className="grid grid-cols-2 gap-2">
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">ID Type</label>
        <select value={mIdType} onChange={e => setMIdType(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink">
          <option value="">Select…</option>
          <option value="Aadhaar">Aadhaar</option>
          <option value="PAN">PAN</option>
          <option value="Passport">Passport</option>
          <option value="Driving License">Driving License</option>
        </select>
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">ID Number</label>
        <input type="text" value={mIdNum} onChange={e => setMIdNum(e.target.value)} placeholder="e.g. 1234 5678 9012"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
      <div className="col-span-2">
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Permanent Address</label>
        <input type="text" value={mAddress} onChange={e => setMAddress(e.target.value)} placeholder="City, State"
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
      </div>
    </div>

    {/* Collect at check-in */}
    <p className="text-[9px] font-bold text-ink-muted uppercase tracking-wide mt-1">Collect at check-in</p>
    <div className="grid grid-cols-2 gap-2">
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Rent (₹)</label>
        <input type="number" inputMode="decimal" value={mRentDues} onChange={e => setMRentDues(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
        <ModeToggle mode={mRentMode} setMode={setMRentMode} />
      </div>
      <div>
        <label className="text-[9px] font-semibold text-ink-muted uppercase tracking-wide block mb-0.5">Deposit (₹)</label>
        <input type="number" inputMode="decimal" value={mDepDues} onChange={e => setMDepDues(e.target.value)}
          className="w-full text-xs rounded-tile bg-[#F6F5F0] border border-[#E0DDD8] px-2.5 py-2 text-ink outline-none focus:ring-1 focus:ring-brand-pink" />
        <span className="text-[9px] font-bold text-[#00AEED] px-2 py-0.5 rounded border border-[#00AEED]/30 mt-1 inline-block">UPI</span>
      </div>
    </div>

    {/* Confirm */}
    <div className="flex gap-2 pt-1">
      <button onClick={() => { setManualOpen(false); setErr("") }}
        className="flex-1 rounded-pill border border-[#E2DEDD] py-2.5 text-xs font-semibold text-ink-muted">
        Cancel
      </button>
      <button onClick={doManualCheckin} disabled={manualSaving}
        className="flex-1 rounded-pill bg-brand-pink py-2.5 text-xs font-bold text-white disabled:opacity-50">
        {manualSaving ? "Checking in…" : "Check In →"}
      </button>
    </div>
  </div>
)}
```

- [ ] **Step 7: Build and verify no TypeScript errors**

```bash
cd web && npm run build 2>&1 | tail -20
```

Expected: build succeeds with 0 type errors. If `manualCheckinApi` is referenced before `BookingCard` function, move it above `BookingCard` or convert it to a named export at module scope.

- [ ] **Step 8: Manual browser test**

1. Start API: `venv/Scripts/python main.py`
2. Start PWA dev server: `cd web && npm run dev`
3. Open `http://localhost:3000/onboarding/bookings`
4. Find a "Awaiting form" card — confirm "Manual check-in ↓" button appears below the Copy/Resend/Edit/Cancel row
5. Click it — confirm KYC panel expands
6. Fill required fields (gender, food, emergency contact x3)
7. Click "Check In →" — confirm card disappears and reloads
8. Verify in DB: `SELECT status FROM onboarding_sessions WHERE token='...'` → `approved`
9. Verify tenancy exists: `SELECT id, status FROM tenancies WHERE tenant_id=(SELECT id FROM tenants WHERE name='...')`
10. Also test with an "expired" card — same button should appear and work

- [ ] **Step 9: Commit frontend**

```bash
git add web/app/onboarding/bookings/page.tsx
git commit -m "feat(bookings): manual check-in panel for pending/expired sessions"
```

---

## Task 3: Deploy

- [ ] **Step 1: Push to trigger deploy**

```bash
git push origin master
```

Deploy is automatic on push (GitHub webhook → VPS pulls + restarts). No manual `systemctl` needed.

- [ ] **Step 2: Smoke-test on production**

Open `https://app.getkozzy.com/onboarding/bookings` (or the live PWA URL), find an "Awaiting form" card, confirm the button and panel work end-to-end.

---

## Self-Review Checklist

**Spec coverage:**
- ✅ Works for `pending_tenant` sessions
- ✅ Works for `expired` sessions
- ✅ Staff enters KYC on behalf of tenant (gender, food, emergency contact required; others optional)
- ✅ Collection at check-in (rent + deposit with mode)
- ✅ Single backend call (two internal DB transactions, atomic from frontend perspective)
- ✅ Reuses `_approve_session_impl` — no duplication of tenancy/payment creation logic
- ✅ `entry_source = "manual_entry"` distinguishes these check-ins in audit trail

**Type consistency:**
- `manualCheckinApi` defined in Task 2 Step 1, called in `doManualCheckin` Step 4 — field names match `ManualCheckinRequest` from Task 1.
- `ModeToggle` already exists in the file (line 259) — reused in Step 6 without redefinition.

**No placeholders:** All code blocks are complete and executable.
