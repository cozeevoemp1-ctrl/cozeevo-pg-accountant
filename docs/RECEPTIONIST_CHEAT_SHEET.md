# Cozeevo Help Desk — Full Command Cheat Sheet

> Send any of these messages to the WhatsApp bot. You can use your own words — the bot understands variations.

---

## ADMIN / POWER USER COMMANDS

### COLLECT RENT (Payment)

| Message | What it does |
|---------|-------------|
| **collect rent** | Step-by-step: Who? → Cash? → UPI? → Confirm |
| **Raj paid 14000 cash** | Quick log — confirms and saves |
| **Raj 14000 upi** | Short form — name + amount + mode |
| **Priya paid 8000 gpay** | GPay payment |
| **15000 Raj gpay** | Amount-first shorthand |
| **record payment** | Start step-by-step form |
| **Raj payment received** | Log without explicit amount (uses most recent) |
| **Raj paid fifteen thousand** | Word-number payment |

Split payment (cash + UPI): Use "collect rent", enter cash amount, then UPI amount separately.

Bot shows dues summary (all months + notes) before asking for amounts.

---

### ADD TENANT (Check-in)

| Message | What it does |
|---------|-------------|
| **add tenant** | Step-by-step form (name → phone → room → rent → deposit → maintenance → date → confirm) |
| **new tenant** | Same |
| **checkin Priya** | Starts form with name pre-filled |
| **new admission** | Same as add tenant |
| **register tenant** | Same |

---

### START ONBOARDING / KYC

| Message | What it does |
|---------|-------------|
| **start onboarding** | Begin KYC/registration for new tenant |
| **start kyc** | Same |
| **onboard Priya** | Same, with name |
| **start registration** | Same |

---

### CHECKOUT (Immediate)

| Message | What it does |
|---------|-------------|
| **checkout Raj** | Guided checklist: keys → damages → fingerprint → settlement → confirm |
| **checkout room 301** | Same, by room number |
| **Raj is leaving** | Same |
| **vacate room 301** | Same |

---

### RECORD CHECKOUT (Form)

| Message | What it does |
|---------|-------------|
| **record checkout** | Fill checkout form / offboarding record |
| **checkout form** | Same |
| **complete checkout** | Same |
| **keys returned** | Same |
| **handover** | Same |

---

### SCHEDULE CHECKOUT (Future Date)

| Message | What it does |
|---------|-------------|
| **Raj leaving on 31 May** | Schedule future checkout |
| **checkout on 15 June** | Same |
| **Raj leaving end of month** | Same |
| **plan checkout Raj** | Same |

---

### NOTICE

| Message | What it does |
|---------|-------------|
| **Raj gave notice** | Records notice (today's date) |
| **Raj gave notice on 5 March** | Records with specific date |
| **notice from Priya** | Same |
| **notice** | Asks which tenant |
| **Raj wants to leave** | Same as notice |

---

### WHO OWES / DUES

| Message | What it does |
|---------|-------------|
| **who owes** | List all unpaid tenants this month |
| **who hasn't paid** | Same |
| **dues this month** | Same |
| **defaulters** | Same |
| **pending dues** | Same |
| **outstanding dues** | Same |
| **show unpaid** | Same |
| **baki** | Same (Hindi) |

---

### TENANT ACCOUNT / QUERY

| Message | What it does |
|---------|-------------|
| **Raj balance** | Shows Raj's payment history + balance |
| **how much does Raj owe** | Same |
| **Raj payment history** | Same |
| **Raj account** | Same |
| **balance of Raj** | Same |
| **show Raj account** | Same |
| **did Raj pay this month?** | Check if tenant paid |
| **what is the rent for Raj** | Shows rent info |

---

### ROOM STATUS

| Message | What it does |
|---------|-------------|
| **room 301** | Shows who's in room 301 + their status |
| **who is in room 301** | Same |
| **room 301 status** | Same |
| **check room 205** | Same |

---

### REPORTS

| Message | What it does |
|---------|-------------|
| **report** | Current month: income, expenses, occupancy |
| **report March** | Specific month report |
| **report 2026** | Yearly report — all months at a glance |
| **yearly report** | Same |
| **monthly report** | Same |
| **P&L** | Same |
| **how much cash collected** | Cash collection query |
| **how much UPI this month** | UPI collection query |
| **total collected** | Same |

---

### BANK REPORT

| Message | What it does |
|---------|-------------|
| **bank report** | Bank statement P&L / analysis |
| **bank statement report** | Same |
| **bank P&L** | Same |
| **income expense report** | Same |

---

### BANK DEPOSIT MATCH

| Message | What it does |
|---------|-------------|
| **match deposits** | Match bank deposits to tenants |
| **check deposits** | Same |
| **identify deposits** | Same |

---

### VACANT ROOMS

| Message | What it does |
|---------|-------------|
| **vacant rooms** | All empty rooms, both buildings |
| **empty rooms** | Same |
| **any rooms available** | Same |
| **how many in thor** | Empty rooms in THOR only |
| **empty beds in hulk** | Empty rooms in HULK only |
| **hulk vacant** | Same |

---

### FEMALE / MALE BED SEARCH

| Message | What it does |
|---------|-------------|
| **room with female** | Rooms with a female + empty bed |
| **female empty beds** | Same |
| **female empty room** | Same |
| **room for male** | Rooms with a male + empty bed |
| **male empty beds** | Same |
| **any bed with girl** | Same as female |
| **female sharing in hulk** | Female beds in HULK only |

---

### OCCUPANCY

| Message | What it does |
|---------|-------------|
| **occupancy** | How full is the PG — rooms filled vs total |
| **how full** | Same |
| **how many tenants** | Same |
| **capacity** | Same |

---

### FLOOR PLAN / ROOM LAYOUT

| Message | What it does |
|---------|-------------|
| **floor plan** | Show room layout |
| **thor layout** | THOR building layout |
| **hulk rooms** | HULK building rooms |
| **beds per floor** | Same |
| **room diagram** | Same |

---

### LOG EXPENSE

| Message | What it does |
|---------|-------------|
| **log expense** | Step-by-step: category → amount → description → confirm |
| **electricity 4500** | Quick log — auto-categorized |
| **salary 12000** | Quick log |
| **plumber 2000** | Quick log as maintenance |
| **maintenance 3000 cash** | With payment mode |
| **5000 cash maintenance** | Amount-first shorthand |
| **paid electricity bill 4500** | Bill payment |
| **internet 1800** | Quick log |
| **diesel 3000** | Quick log |
| **generator maintenance** | Quick log |

---

### VOID / CANCEL PAYMENT

| Message | What it does |
|---------|-------------|
| **void payment Raj** | Shows Raj's recent payment → confirm void |
| **cancel payment Raj** | Same |
| **wrong payment** | Asks which tenant |
| **undo payment** | Same |
| **reverse payment** | Same |

---

### VOID / CANCEL EXPENSE

| Message | What it does |
|---------|-------------|
| **void expense** | Shows recent expenses → confirm void |
| **cancel expense** | Same |
| **wrong expense** | Same |
| **delete expense** | Same |

---

### ROOM TRANSFER

| Message | What it does |
|---------|-------------|
| **transfer Raj to 305** | Shows rent options → deposit → confirm |
| **move Raj to room 305** | Same |
| **shift Raj to 205** | Same |

---

### RENT CHANGE

| Message | What it does |
|---------|-------------|
| **change Raj rent to 15000** | Update rent (one-time or permanent) |
| **increase rent for room 301** | Same |
| **rent from July 16000** | Set rent from a specific month |
| **set rent for Raj 14000** | Same |

---

### SHARING TYPE CHANGE

Changes only the *tenant's* sharing, never the room's master type.
Use this when one tenant pays extra to occupy the full room (premium)
or when a sharing tier is renegotiated.

| Message | What it does |
|---------|-------------|
| **change Raj sharing to premium** | Update tenant sharing type |
| **update Raj sharing type to double** | Same |
| **Raj is in premium sharing** | Same |
| **set Raj sharing triple** | Same |

Values: `single`, `double`, `triple`, `premium`.

---

### RENT DISCOUNT / CONCESSION

| Message | What it does |
|---------|-------------|
| **concession for Raj** | One-time rent reduction |
| **discount this month** | Same |
| **waive 1000** | Same |
| **extra charge for electricity** | Add surcharge |

---

### DEPOSIT CHANGE

| Message | What it does |
|---------|-------------|
| **change deposit for Raj** | Update deposit amount |
| **deposit correction** | Same |
| **increase deposit** | Same |

---

### REFUNDS

| Message | What it does |
|---------|-------------|
| **add refund Raj 5000** | Record deposit refund with amount |
| **return deposit Raj** | Same |
| **pending refunds** | List all pending deposit refunds |
| **refund status** | Same |
| **show refunds** | Same |
| **refund history** | Same |

---

### BULK REMINDER

| Message | What it does |
|---------|-------------|
| **remind unpaid** | Lists all unpaid tenants + queues reminders |
| **remind all** | Same |
| **send reminder** | Same |
| **send reminder to all** | Same |
| **bulk reminder** | Same |

---

### SET REMINDER (Individual)

| Message | What it does |
|---------|-------------|
| **remind Raj tomorrow** | Set personal reminder |
| **set reminder** | Same |
| **reminder Deepak March 5** | Same, with date |

---

### COMPLAINTS

| Message | What it does |
|---------|-------------|
| **complaint fan not working room 301** | Registers complaint |
| **AC broken room 205** | Same |
| **report plumbing issue** | Same |
| **tap leak room 102** | Same |

---

### COMPLAINT MANAGEMENT

| Message | What it does |
|---------|-------------|
| **show complaints** | List all open/pending complaints |
| **pending complaints** | Same |
| **resolve CMP001** | Mark complaint as resolved |
| **close complaint 3** | Same |
| **complaint solved CMP002** | Same |

---

### UPDATE CHECKIN DATE

| Message | What it does |
|---------|-------------|
| **update checkin Raj March 5** | Backdate/correct check-in date |
| **Raj checkin was on March 1** | Same |
| **Raj joined on 5 March** | Same |
| **joining date for Raj is March 1** | Same |

---

### CHANGE CHECKOUT DATE

| Message | What it does |
|---------|-------------|
| **change checkout date Raj to 15 April** | Update checkout date |
| **update checkout Raj** | Asks for new date |
| **Raj checkout was on 10 April** | Same |
| **change exit date Raj** | Same |
| **actual checkout Raj** | Same |

---

### WIFI

| Message | What it does |
|---------|-------------|
| **wifi password** | Shows current WiFi password |
| **set wifi password newpass123** | Update WiFi password |
| **change wifi** | Same |

---

### UPDATE TENANT NOTES

| Message | What it does |
|---------|-------------|
| **update agreement for Raj** | View + edit permanent tenant notes |
| **update tenant notes Raj** | Same |
| **change notes for room 301** | Same, by room |

---

### VIEW TENANT NOTES

| Message | What it does |
|---------|-------------|
| **notes for Raj** | View tenant's agreed terms / notes |
| **agreement for room 301** | Same |
| **check terms for Priya** | Same |
| **Raj payment method** | Same |

---

### ACTIVITY LOG

| Message | What it does |
|---------|-------------|
| **log** | Start activity log entry |
| **log received 50 chairs** | Log an activity |
| **note generator serviced** | Same |
| **delivered 20 mattresses** | Same |

---

### QUERY ACTIVITY

| Message | What it does |
|---------|-------------|
| **activity today** | Show today's activity log |
| **activity this week** | Show this week's activities |
| **activity yesterday** | Same |
| **show activity** | Same |

---

### CONTACTS / VENDORS

| Message | What it does |
|---------|-------------|
| **add plumber Ravi 9876543210** | Save vendor contact |
| **add contact** | Same |
| **show plumber contact** | Look up vendor |
| **electrician number** | Same |
| **vendor list** | List all contacts |
| **all contacts** | Same |

---

### EXPIRING / UPCOMING CHECKOUTS

| Message | What it does |
|---------|-------------|
| **who is leaving this month** | Tenants with notice / upcoming checkout |
| **upcoming checkouts** | Same |
| **expiring tenancies** | Same |
| **who gave notice** | Same |

---

### CHECKINS THIS MONTH

| Message | What it does |
|---------|-------------|
| **who checked in** | New arrivals this month |
| **new tenants this month** | Same |
| **recent checkins** | Same |
| **checkins March** | Checkins for a specific month |

---

### CHECKOUTS THIS MONTH

| Message | What it does |
|---------|-------------|
| **who checked out** | Exits this month |
| **checkouts this month** | Same |
| **who left** | Same |
| **checkouts March** | For a specific month |

---

### EXPENSE QUERY

| Message | What it does |
|---------|-------------|
| **expenses this month** | Show expense breakdown |
| **what did we spend** | Same |
| **total expenses** | Same |
| **March expenses** | Expenses for a specific month |
| **expense summary** | Same |

---

### VACATION / ABSENCE

| Message | What it does |
|---------|-------------|
| **Raj on vacation** | Log tenant absence |
| **Raj going home for 10 days** | Same, with duration |
| **Priya on leave from Monday** | Same |
| **Raj chutti pe hai** | Same (Hindi) |

---

### ADD PARTNER / STAFF (BOT ACCESS)

| Message | What it does |
|---------|-------------|
| **add partner** | Add admin/power user to bot |
| **give access** | Same |

---

### STAFF MANAGEMENT

| Message | What it does |
|---------|-------------|
| **show staff rooms** | List all staff rooms + who lives there + KYC status |
| **add staff Raju \| Security \| 8000 \| 15-06-1990 \| 9876543210 \| 1234-5678-9012** | Register new staff — name \| role \| salary \| dob \| phone \| aadhar |
| **add staff Raju \| Security \| 8000 \| 15-06-1990 \| 9876543210 \| 1234-5678-9012 \| room G05** | Same + assign to room immediately |
| *(after add staff — send photo/PDF)* | Upload Aadhar / ID card → KYC saved to Supabase |
| *(reply "skip")* | Skip KYC for now — staff marked KYC pending |
| **staff Raju room G05** | Assign existing staff to a room |
| **staff Raju exit** | Mark staff as exited, room flips back to revenue if empty |
| **staff Raju left** | Same |

> **KYC note:** Staff without uploaded ID are shown as `⚠ KYC pending` in `show staff rooms`. Upload anytime by triggering a new `add staff` command or waiting for the bot to prompt.

---

### PG RULES

| Message | What it does |
|---------|-------------|
| **rules** | Show PG rules & regulations |
| **house rules** | Same |
| **what are the rules** | Same |

---

## TENANT COMMANDS (Self-Service)

| Message | What it does |
|---------|-------------|
| **my balance** | Shows dues / how much you owe |
| **how much do I owe** | Same |
| **my payments** | Payment history |
| **payment history** | Same |
| **my room** | Room details, rent, checkin date |
| **my details** | Same |
| **receipt** | Request payment receipt |
| **payment receipt** | Same |
| **wifi password** | Get WiFi password |
| **complaint fan not working** | Register a complaint |
| **AC broken** | Same |
| **rules** | Show PG rules |
| **I want to leave** | Give checkout notice |
| **giving notice** | Same |
| **going home for 5 days** | Vacation notice |
| **on leave** | Same |
| **hi** / **hello** / **help** | Show menu |

---

## LEAD COMMANDS (Room Enquiry)

| Message | What it does |
|---------|-------------|
| **price** / **rent** / **rates** | Room pricing info |
| **rooms available** | Vacancy check |
| **single room** / **sharing** | Room type info |
| **visit** / **tour** / **come see** | Request a visit |
| Any other message | Natural conversation (AI-powered) |

---

## CORRECTIONS (During Payment Confirmation)

When the bot asks "Confirm? Raj Kumar, Rs.15,000 UPI, March 2026. Reply Yes/No":

| Message | What it does |
|---------|-------------|
| **no 15000** or just **15000** | Correct the amount |
| **no it was upi** / **actually cash** / **no gpay** | Correct the payment mode |
| **no for february** / **no january** | Correct the month |
| **no 14000 for february** | Correct amount + month together |
| **no 14000 upi** | Correct amount + mode together |
| **no** / **cancel** / **stop** | Cancel the payment |
| **yes** / **ok** / **haan** / **theek hai** / **confirm** | Confirm and save |

---

## CANCEL / RESET

| During any form... | What it does |
|---------|-------------|
| **cancel** | Stops the current form |
| **stop** | Same |
| **hi** / **hello** | Resets and shows menu |
| **help** | Shows service menu |

---

*Updated: 6 Apr 2026 | Cozeevo Co-living*
