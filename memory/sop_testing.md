---
name: Testing SOP
description: Mandatory end-to-end testing methodology — read before marking ANY feature as done
type: project
---

# Testing SOP — PG Accountant

## The Rule

**No feature is done until it survives mid-flow corrections.**

A happy-path test proves nothing. Every flow must be tested with deliberate wrong inputs and mid-flow changes before it is called complete. This applies to bot flows, form OCR, payments, checkouts, onboarding — everything.

## The Method

For every flow you implement or change:

### 1. Happy path first
Run the flow with correct inputs start to finish. Verify the expected DB state and WhatsApp reply.

### 2. Mid-flow correction test (MANDATORY)
Pick 2–3 fields that are likely to be wrong. Enter wrong values intentionally. Correct each one separately. Verify:
- The correction is accepted
- ALL previously-corrected fields are still correct (no revert)
- The bot shows the updated state after each correction
- Confirming at the end uses the final corrected values

**Example for checkout form flow:**
1. Send form image → OCR extracts room=906 (wrong), phone=wrong, name=Soumya
2. Send `edit room 206` → verify bot shows room=206, all other fields unchanged
3. Send `edit phone 9876543210` → verify bot shows room=206 AND new phone (both correct)
4. Send `yes` → verify DB checkout uses room=206 and finds correct tenant

### 3. Abandon and restart
Start a flow, get halfway, then start a different flow. Verify the old flow is abandoned and the new one starts fresh.

### 4. Cancel at every step
For multi-step flows: test `cancel` at step 1, step 2, and the final confirmation step. Verify nothing is written to DB on cancel.

### 5. Bad inputs at every step
At each prompt, send garbage: empty, wrong type, impossible value. Verify the bot:
- Does NOT crash
- Gives a clear error
- Stays in the same flow step (pending not resolved)
- The user can correct and continue

### 6. VPS test, not local
Always test on the VPS using test phone numbers. Never test against production data. Use the test tenant/room numbers in the `tests/` directory if available.

## Environment for Testing

- Use VPS bot directly (same DB, same webhook path as production)
- Use a test phone registered as admin/power_user
- Test data: create a disposable tenant in a test room, or use known inactive data
- After testing: clean up any test payments/checkouts using `is_void=True`

## What "Done" Means

A feature is done when:
1. Happy path passes on VPS
2. Mid-flow correction test passes (no field revert)
3. Cancel at final step leaves DB unchanged
4. At least one bad-input scenario handled gracefully

If any of these fail: the feature is not done, it is in_progress. Fix first, mark done second.

## Specific Flows and Their Test Matrix

### Checkout form OCR (CHECKOUT_FORM_CONFIRM)
| Scenario | Expected result |
|---|---|
| Correct OCR → yes | Checkout processed |
| Wrong room → edit room 206 → yes | Uses corrected room |
| Wrong room → edit room → wrong phone → edit phone → yes | Both corrections held, no revert |
| Room+name match but wrong phone → yes | Phone mismatch warning shown, user confirms |
| Room+name match but wrong phone → edit phone → yes | Phone corrected, checkout proceeds |
| No active tenant found | Error with edit hint |
| Multiple matches | Pick-by-number disambiguation |
| cancel at any step | Nothing written to DB |

### Check-in form OCR (FORM_EXTRACT_CONFIRM)
| Scenario | Expected result |
|---|---|
| Correct OCR → yes | Tenant created |
| Wrong name → edit name → yes | Corrected name saved |
| Wrong room → edit room → wrong phone → edit phone → yes | Both corrections held |
| Duplicate phone → edit phone → yes | New phone accepted |
| cancel | Nothing written |

### Day-wise guest flows
| Scenario | Expected result |
|---|---|
| "how many guests today" | Includes day-stay guests |
| "[DayWise name] balance" | Returns correct balance (rent_due - paid) |
| "change [DayWise name] rent 600" | Updates Tenancy.agreed_rent |
| "move [DayWise name] to room 305" | Uses ROOM_TRANSFER flow |
| Payment logged for day-stay guest | Updates DAY WISE tab, not monthly tab |

### Payment flow (CONFIRM_PAYMENT_LOG)
| Scenario | Expected result |
|---|---|
| Correct payment → yes | DB + sheet updated |
| Wrong amount → say new amount | Flow re-prompts with corrected amount |
| cancel at confirmation | Nothing written |
| Same payment twice | Second attempt handled (dedup or error) |

## After Testing: Cleanup

If you created test data during testing:
```sql
-- void a test payment
UPDATE payments SET is_void = true WHERE id = <test_id>;

-- void a test tenancy (do NOT delete)
UPDATE tenancies SET status = 'vacated' WHERE id = <test_id>;
```

Never hard-delete financial records.
