# COZEEVO HELP DESK — PRINTABLE CHEAT SHEET
## Every workflow: what to say, what the bot asks, what happens

---

## 1. COLLECT RENT (Payment)

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| A | **collect rent** | *Who paid?* (name or room) |
|   | Raj | Shows dues summary → *Cash amount?* |
|   | 5000 | *UPI amount?* |
|   | 10000 | *Any notes?* (or skip) |
|   | skip | Shows total → *Confirm? Yes/No* |
|   | yes | Payment logged |
| B | **Raj paid 14000 cash** | Shows dues → *Confirm? Yes/No* |
|   | yes | Payment logged |
| C | **Raj 14000 upi** | Shows dues → *Confirm? Yes/No* |
|   | yes | Payment logged |
| D | **15000 Raj gpay** | Shows dues → *Confirm? Yes/No* |

**Corrections during confirmation:**
| You Say | What Changes |
|---|---|
| **15000** or **no 15000** | Fixes amount |
| **no it was upi** / **actually cash** / **no gpay** | Fixes payment mode |
| **no for february** | Fixes month |
| **no 14000 for february** | Fixes amount + month |
| **no 14000 upi** | Fixes amount + mode |
| **no** / **cancel** | Cancels |

**Multi-month dues:** Bot auto-allocates oldest first. Override with:
- *all to march*
- *feb 3000 march 5000*

**Multiple name matches:** Bot shows numbered list → reply with number.

**Room-only (sharing room):** Bot shows all occupants → pick one.

---

## 2. ADD TENANT (Check-in)

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **add tenant** | *Tenant's full name?* |
| 2 | Raj Kumar | *Phone number?* |
| 3 | 9876543210 | *Gender?* (Male/Female) |
| 4 | Male | *Food preference?* (Veg/Non-veg/Egg/Skip) |
| 5 | Non-veg | *Room number?* (e.g. T-201) |
| 6 | T-301 | *Monthly rent?* |
| 7 | 14000 | *Deposit amount?* |
| 8 | 14000 | *Advance rent paid?* (amount or 0) |
| 9 | 0 | *Maintenance fee?* (one-time, or 0) |
| 10 | 500 | *Check-in date?* (today / 03 April) |
| 11 | today | *Personal details?* (skip / continue) |
|   |   | If **skip** → jumps to Notes |
|   |   | If **continue** → asks all fields below: |
| 12 | continue | *Date of birth?* (or skip) |
| 13 | 15/03/1995 | *Father's name?* (or skip) |
| 14 | Ramesh Kumar | *Father's phone?* (or skip) |
| 15 | 9876543210 | *Permanent address?* (or skip) |
| 16 | 123 Main St | *Email?* (or skip) |
| 17 | raj@email.com | *Occupation?* (or skip) |
| 18 | Software Engineer | *Educational qualification?* (or skip) |
| 19 | B.Tech | *Office/college address?* (or skip) |
| 20 | skip | *Office phone?* (or skip) |
| 21 | skip | *Emergency contact name?* (or skip) |
| 22 | Ramesh Kumar | *Relationship?* (Father/Mother/etc, or skip) |
| 23 | Father | *Emergency phone?* (or skip) |
| 24 | 9876543210 | *ID proof type?* (1-5 or skip) |
| 25 | 1 (Aadhaar) | *Aadhaar number?* (or skip) |
| 26 | 1234 5678 9012 | *Notes?* (or skip) |
| 27 | cash only | Shows full summary → *Confirm? Yes/No* |
| 28 | yes | Tenant added with all details |

**Every personal detail field is skippable.** Type *skip* to skip any field.

**Room full?** Bot offers:
1. Checkout existing tenant (asks who + when)
2. Pick different room
3. Cancel

**Gender mismatch?** Bot warns → asks to confirm or pick different room.

**Quick start:** *checkin Priya* → skips to phone number.

**Bulk input:** You can send all details in one message — bot extracts and shows form for confirmation.

---

## 3. CHECKOUT

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **checkout Raj** | Shows tenant info + dues summary |
|   |   | *Q1/5: Cupboard/almirah key returned? Yes/No* |
| 2 | yes | *Q2/5: Main gate/room key returned? Yes/No* |
| 3 | yes | *Q3/5: Any damages? No / describe them* |
| 4 | broken fan | *Q4/5: Fingerprint/biometric deleted? Yes/No* |
| 5 | yes | Shows settlement: dues, deposit, refund |
|   |   | *Confirm checkout? Yes/No* |
| 6 | yes | Checkout recorded, room freed |

**Multiple matches:** Bot shows list → pick number → then checklist starts.

**Scheduled checkout:** *Raj leaving on 31 May* → same checklist but with future date.

**All 3 triggers go to same checklist:**
- *checkout Raj* (immediate)
- *Raj leaving on 31 May* (scheduled)
- *record checkout* / *checkout form* (form entry)

---

## 4. NOTICE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **Raj gave notice** | Records notice with today's date. Done. |
| 1 | **Raj gave notice on 5 March** | Records notice with that date. Done. |
| 1 | **notice** | *Who gave notice?* |
| 2 | Raj | Notice recorded |

**Multiple matches:** Bot shows list → pick number.

No multi-step form — single action.

---

## 5. ROOM TRANSFER

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **transfer Raj to 305** | Shows current room + rent |
|   |   | *1.* Keep current rent |
|   |   | *2.* Enter new rent |
| 2 | 1 | *Additional deposit needed?* (amount or skip) |
| 3 | skip | Shows summary: Room X → Y, rent, deposit |
|   |   | *Confirm? Yes/No* |
| 4 | yes | Transfer done |

**If you pick option 2:**
| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 2 | 2 | *New rent amount?* |
| 3 | 16000 | *Additional deposit needed?* (amount or skip) |
| 4 | 2000 | Shows summary → *Confirm? Yes/No* |
| 5 | yes | Transfer done, rent + deposit updated |

**Multiple matches:** Bot shows list → pick number → then steps start.

---

## 6. RENT CHANGE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **change Raj rent to 15000** | Shows current rent |
|   |   | *1.* From this month |
|   |   | *2.* From next month |
|   |   | *3.* One-time this month only |
| 2 | 1 | Rent updated from this month |

**Correction:** Send a different amount during confirmation → bot updates.

**Multiple matches:** Bot shows list → pick number → then options.

---

## 7. RENT DISCOUNT / CONCESSION

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **concession for Raj** | *How much concession?* |
|   |   | *1.* This month only |
|   |   | *2.* Permanent |
| 2 | 1 | Concession applied |

---

## 8. DEPOSIT CHANGE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **change deposit for Raj** | Shows current deposit |
|   |   | *New deposit amount?* |
| 2 | 20000 | *Confirm? Yes/No* |
| 3 | yes | Deposit updated |

---

## 9. LOG EXPENSE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| A | **log expense** | *Category?* (electricity/salary/maintenance...) |
|   | electricity | *Amount?* |
|   | 4500 | *Description?* (or skip) |
|   | EB bill March | *Photo/bill?* (send image or skip) |
|   | skip | Shows summary → *Confirm? Yes/No* |
|   | yes | Expense logged |
| B | **electricity 4500** | Shows summary → *Confirm? Yes/No* |
|   | yes | Expense logged |
| C | **maintenance 3000 cash** | Shows summary → *Confirm? Yes/No* |

**Correction during confirmation:** Send new amount → bot updates.

---

## 10. VOID PAYMENT

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **void payment Raj** | Shows recent payments (numbered) |
| 2 | 1 | *Confirm void? Yes/No* |
| 3 | yes | Payment voided (marked is_void, never deleted) |

---

## 11. VOID EXPENSE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **void expense** | Shows recent expenses (numbered) |
| 2 | 1 | *Confirm void? Yes/No* |
| 3 | yes | Expense voided |

---

## 12. REFUNDS

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **add refund Raj 5000** | Shows deposit info → *Confirm? Yes/No* |
| 2 | yes | Refund recorded |
| 1 | **pending refunds** | Lists all pending refunds (no form) |

---

## 13. UPDATE CHECKIN DATE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **update checkin Raj March 5** | *Confirm update? Yes/No* |
| 2 | yes | Checkin date corrected |

No multi-step — single correction + confirm.

---

## 13b. CHANGE CHECKOUT DATE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| A | **change checkout date Raj to 15 April** | Shows current vs new → *Confirm? 1* |
|   | 1 | Checkout date updated |
| B | **update checkout Raj** | Shows current checkout → *New date?* |
|   | 15 April | Checkout date updated |
| C | **Raj checkout was on 10 April** | Shows current vs new → *Confirm? 1* |

Works for both active (expected_checkout) and exited tenants (checkout_date).

**Multiple matches:** Bot shows list → pick number → then date.

---

## 14. BULK REMINDER

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **remind unpaid** | Shows list of unpaid tenants |
|   |   | *Send reminders to all? Yes/No* |
| 2 | yes | Reminders queued and sent |

---

## 15. SET REMINDER (Individual)

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **remind Raj tomorrow** | Reminder set. Done. |
| 1 | **reminder Deepak March 5** | Reminder set. Done. |

No multi-step.

---

## 16. COMPLAINTS

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **complaint fan not working room 301** | Complaint registered (CMP-XXX). Done. |
| 1 | **show complaints** | Lists open complaints |
| 1 | **resolve CMP001** | Complaint marked resolved |

No multi-step — single action + confirm.

---

## 17. ADD CONTACT / VENDOR

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| A | **add contact** | *Name?* |
|   | Ravi | *Phone number?* |
|   | 9876543210 | *Category?* (plumber/electrician/...) |
|   | plumber | Contact saved |
| B | **add plumber Ravi 9876543210** | Contact saved (no form needed) |

---

## 18. WIFI

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **wifi password** | Shows current password. Done. |
| 1 | **set wifi password newpass** | Password updated. Done. |

---

## 19. UPDATE TENANT NOTES

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **update agreement for Raj** | Shows current notes |
|   |   | *New notes?* (type them) |
| 2 | cash only, no AC charge | Notes updated |

---

## 20. ACTIVITY LOG

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **log received 50 chairs** | Activity logged. Done. |
| 1 | **activity today** | Shows today's log. Done. |

No multi-step.

---

## 21. VACATION / ABSENCE

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **Raj on vacation** | Vacation logged. Done. |
| 1 | **Raj going home for 10 days** | Vacation logged with duration. Done. |

No multi-step.

---

## 22. STAFF ROOM MARK / UNMARK (Admin)

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| A | **room 114 staff room** | Room 114 marked as staff room (excluded from revenue) |
| B | **mark 114 staff** | Same |
| C | **room 114 not staff** | Room 114 is now a revenue room |
| D | **not staff rooms 114 and 618** | Both unmarked in one go |
| E | **staff rooms** | Lists all staff rooms with occupants |
| F | **staff Rajesh room G05** | Assigns staff Rajesh to room G05 (auto-flips to staff room) |
| G | **staff Rajesh exit** | Marks staff as exited; room flips back to revenue if empty |

Instant — no multi-step form.

---

## 23. ONBOARDING / KYC (Tenant Self-Service)

| # | You Say (BLUE) | Bot Asks/Does (GREEN) |
|---|---|---|
| 1 | **start onboarding** (admin sends) | Link/form sent to tenant |
|   | *Tenant receives:* | *Date of birth?* |
|   | 15/03/1995 | *Father's name?* |
|   | Ramesh Kumar | *Father's phone?* |
|   | 9876543210 | *Address?* |
|   | 123 Main St, Chennai | *Email?* |
|   | raj@email.com | *Occupation?* |
|   | Software Engineer | *Gender?* |
|   | Male | *Food preference?* |
|   | Non-veg | *Emergency contact name?* |
|   | Ramesh Kumar | *Relationship?* |
|   | Father | *Emergency phone?* |
|   | 9876543210 | *ID type?* (Aadhaar/PAN/...) |
|   | Aadhaar | *ID number?* |
|   | 1234 5678 9012 | *Send ID photo* |
|   | (sends image) | *Send selfie* |
|   | (sends image) | KYC complete |

---

## SINGLE-ACTION QUERIES (No Form)

These are instant — bot replies immediately, no follow-up needed:

| You Say (BLUE) | Bot Shows (GREEN) |
|---|---|
| **who owes** / **defaulters** / **dues this month** | List of unpaid tenants + amounts |
| **Raj balance** / **how much does Raj owe** | Raj's payment history + balance |
| **room 301** | Who's in room 301 + status |
| **report** / **report March** / **report 2026** | Financial report |
| **vacant rooms** / **empty rooms** | All vacant rooms |
| **how many in thor** / **hulk vacant** | Building-specific vacancies |
| **room with female** / **male empty beds** | Gender-matched rooms |
| **occupancy** / **how full** | Occupancy overview |
| **floor plan** / **thor layout** | Room layout diagram |
| **expenses this month** / **March expenses** | Expense breakdown |
| **who checked in** / **recent checkins** | This month's new arrivals |
| **who checked out** / **who left** | This month's exits |
| **who is leaving this month** / **upcoming checkouts** | Tenants with notice |
| **bank report** | Bank statement analysis |
| **match deposits** | Bank deposit matching |
| **rules** | PG rules & regulations |
| **notes for Raj** / **agreement for room 301** | Tenant notes/terms |
| **electrician number** / **vendor list** | Contact lookup |
| **pending refunds** / **refund status** | Refund list |
| **show complaints** / **pending complaints** | Open complaints |
| **add partner** / **add staff** | Add admin access |

---

## UNIVERSAL COMMANDS

| You Say | What Happens |
|---|---|
| **cancel** / **stop** | Cancels any active form |
| **hi** / **hello** | Resets and shows menu |
| **help** / **menu** | Shows available commands |
| **yes** / **ok** / **haan** / **confirm** | Confirms pending action |
| **no** | Cancels pending action |

---

## TENANT SELF-SERVICE COMMANDS

| You Say (BLUE) | Bot Shows (GREEN) |
|---|---|
| **my balance** / **how much do I owe** | Your dues |
| **my payments** / **payment history** | Your payment history |
| **my room** / **my details** | Room, rent, checkin date |
| **receipt** / **payment receipt** | Payment receipt |
| **wifi password** | WiFi password |
| **complaint fan not working** | Registers complaint |
| **I want to leave** / **giving notice** | Records checkout notice |
| **going home for 5 days** | Vacation notice |
| **rules** | PG rules |

---

## LEAD (Enquiry) COMMANDS

| You Say (BLUE) | Bot Shows (GREEN) |
|---|---|
| **price** / **rent** / **rates** | Room pricing |
| **rooms available** | Vacancy info |
| **single room** / **sharing** | Room types |
| **visit** / **tour** | Schedules visit |
| Anything else | AI conversation |

---

*Color Guide: BLUE = what you type | GREEN = what bot responds*
*Updated: 6 Apr 2026 | Cozeevo Co-living*
