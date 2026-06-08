# Salary & Staff Payment Audit Log

**Sources:**
- `bank_transactions` WHERE `category = 'Staff & Labour'` (bank transfers)
- `CASH_SALARY_ROWS` in this script (cash payments hardcoded from pnl_builder.py)

**Rule:** Re-run `python scripts/_generate_audit_logs.py` after every bank CSV import or pnl_builder update.
**Last updated:** 2026-05-30

| # | Date | Account | Name | Amount |
|---|------|---------|------|-------:|
| 1 | 2025-11-30 | THOR | Cleaners Advance | 1,000 |
| 2 | 2025-12-01 | THOR | Imran Azmi (Housekeeping) | 16,000 |
| 3 | 2025-12-01 | THOR | Rabha Soma (Housekeeping) | 10,000 |
| 4 | 2025-12-01 | THOR | Sreeraj (Housekeeping) | 10,000 |
| 5 | 2025-12-01 | THOR | Bhukesh | 9,000 |
| 6 | 2025-12-04 | THOR | Rabha Soma (Housekeeping) | 2,000 |
| 7 | 2025-12-04 | THOR | Lokesh (Receptionist) | 220 |
| 8 | 2025-12-06 | THOR | Lokesh (Receptionist) | 55 |
| 9 | 2025-12-10 | THOR | Lokesh (Receptionist) | 14,500 |
| 10 | 2025-12-10 | THOR | Bikey Dey (Staff) | 9,000 |
| 11 | 2025-12-10 | THOR | Abhisek Mandal (Staff) | 8,310 |
| 12 | 2025-12-12 | THOR | Sachin Divya | 3,650 |
| 13 | 2025-12-13 | THOR | Akmal (Staff) | 2,500 |
| 14 | 2025-12-16 | THOR | Lokesh (Receptionist) | 1,600 |
| 15 | 2025-12-16 | THOR | Sachin Divya | 1,000 |
| 16 | 2025-12-17 | THOR | Ravi Kumar | 12,500 |
| 17 | 2025-12-20 | THOR | Sanket Wankhede | 15,000 |
| 18 | 2025-12-20 | THOR | Housekeeping Staff | 3,600 |
| 19 | 2025-12-23 | THOR | Sachin Divya | 3,000 |
| 20 | 2025-12-30 | THOR | Manisha Pundir (Housekeeping) | 13,000 |
| 21 | 2025-12-31 | CASH | Petty Wages (cash) | 500 |
| 22 | 2026-01-09 | THOR | Lokesh (Receptionist) | 1,840 |
| 23 | 2026-01-10 | THOR | Lokesh (Receptionist) | 16,000 |
| 24 | 2026-01-10 | THOR | Abhisek Mandal (Staff) | 15,120 |
| 25 | 2026-01-10 | THOR | Sreeraj (Housekeeping) | 10,000 |
| 26 | 2026-01-10 | THOR | Urban Company (Cleaning Svc) | 307 |
| 27 | 2026-01-11 | THOR | Lokesh (Receptionist) | 6,190 |
| 28 | 2026-01-12 | THOR | Ram Chandra (Cook/Staff) | 12,328 |
| 29 | 2026-01-15 | THOR | Joshi Arjunbhai (Cleaner) | 4,030 |
| 30 | 2026-01-18 | THOR | Swami Sarang | 5,000 |
| 31 | 2026-01-18 | THOR | Lokesh (Receptionist) | 500 |
| 32 | 2026-01-19 | THOR | Vishal (Staff) | 5,000 |
| 33 | 2026-01-19 | THOR | Staff Mobile Recharge (Vi) | 302 |
| 34 | 2026-01-20 | THOR | Staff Mobile Recharge (Jio) | 302 |
| 35 | 2026-01-21 | THOR | Joshi Arjunbhai (Cleaner) | 14,698 |
| 36 | 2026-01-21 | THOR | Urban Company (Cleaning Svc) | 416 |
| 37 | 2026-01-21 | THOR | Lokesh (Receptionist) | 30 |
| 38 | 2026-01-25 | THOR | Sreeraj (Housekeeping) | 1,000 |
| 39 | 2026-01-30 | THOR | Gudadesh (Contractor) | 7,000 |
| 40 | 2026-01-30 | PERSONAL_SBI_0167 | Subramani (Worker) | 3,861 |
| 41 | 2026-01-31 | THOR | Salam Tajamul (Housekeeping) | 12,000 |
| 42 | 2026-01-31 | CASH | Petty Wages (cash) | 790 |
| 43 | 2026-02-01 | THOR | Dilli Rout (Housekeeping) | 1,000 |
| 44 | 2026-02-01 | THOR | Urban Company (Cleaning Svc) | 478 |
| 45 | 2026-02-02 | THOR | Housekeeping Staff | 1,500 |
| 46 | 2026-02-02 | THOR | Lokesh (Receptionist) | 1,000 |
| 47 | 2026-02-02 | THOR | Urban Company (Cleaning Svc) | 534 |
| 48 | 2026-02-03 | THOR | Housekeeping Staff | 4,320 |
| 49 | 2026-02-03 | THOR | Housekeeping Staff | 3,000 |
| 50 | 2026-02-06 | THOR | Housekeeping Staff | 1,200 |
| 51 | 2026-02-09 | THOR | Biplab (Staff) | 25,000 |
| 52 | 2026-02-09 | THOR | Saroj Rout (Housekeeping) | 1,500 |
| 53 | 2026-02-10 | THOR | Lokesh (Receptionist) | 15,000 |
| 54 | 2026-02-11 | THOR | Joshi Arjunbhai (Cleaner) | 35,000 |
| 55 | 2026-02-11 | THOR | Ram Chandra (Cook/Staff) | 23,000 |
| 56 | 2026-02-11 | THOR | Staff-8132966734 | 12,000 |
| 57 | 2026-02-11 | THOR | Lokesh (Receptionist) | 11,000 |
| 58 | 2026-02-11 | THOR | Vivek | 10,000 |
| 59 | 2026-02-11 | THOR | Vivek | 4,000 |
| 60 | 2026-02-11 | THOR | Staff Mobile Recharge (Jio) | 804 |
| 61 | 2026-02-13 | THOR | WorkIndia (Recruitment) | 5,898 |
| 62 | 2026-02-14 | THOR | Staff-9880401360 | 6,560 |
| 63 | 2026-02-14 | THOR | Urban Company (Cleaning Svc) | 314 |
| 64 | 2026-02-15 | THOR | Staff-9880401360 | 1,410 |
| 65 | 2026-02-21 | THOR | Lokesh (Receptionist) | 3,362 |
| 66 | 2026-02-24 | THOR | Kutubuddin (Staff) | 1,025 |
| 67 | 2026-02-27 | THOR | Staff-9880401360 | 1,810 |
| 68 | 2026-02-28 | CASH | Petty Wages (cash) | 580 |
| 69 | 2026-03-04 | THOR | Rampukar (Labour) | 3,000 |
| 70 | 2026-03-07 | THOR | Kshama (Staff) | 23,000 |
| 71 | 2026-03-08 | THOR | Sandeep Gowda | 5,700 |
| 72 | 2026-03-08 | THOR | Dilli Rout (Housekeeping) | 800 |
| 73 | 2026-03-08 | THOR | Dilli Rout (Housekeeping) | 780 |
| 74 | 2026-03-08 | THOR | Dilli Rout (Housekeeping) | 200 |
| 75 | 2026-03-11 | THOR | Joshi Arjunbhai (Cleaner) | 36,000 |
| 76 | 2026-03-11 | THOR | Dilli Rout (Housekeeping) | 600 |
| 77 | 2026-03-14 | THOR | Ram Chandra (Cook/Staff) | 21,056 |
| 78 | 2026-03-14 | THOR | Vivek | 10,000 |
| 79 | 2026-03-14 | THOR | Vivek | 3,000 |
| 80 | 2026-03-16 | THOR | Rock Shield (Security Contractor) | 19,355 |
| 81 | 2026-03-16 | THOR | Rampukar (Labour) | 9,110 |
| 82 | 2026-03-18 | THOR | Staff-9880401360 | 900 |
| 83 | 2026-03-18 | THOR | Staff-9880401360 | 250 |
| 84 | 2026-03-26 | THOR | Volipi (Cleaner) | 5,180 |
| 85 | 2026-03-28 | THOR | Prabhakaran (Manager) | 160 |
| 86 | 2026-03-28 | THOR | Labour - Cash Exchange (ESOB Tanti) | 100 |
| 87 | 2026-03-29 | THOR | Salary - Other Staff | 4,000 |
| 88 | 2026-03-31 | CASH | Vivek, Ravi, Saurav, Cook, helpers — cash labour | 32,600 |
| 89 | 2026-03-31 | CASH | Lokesh + mother (Volipi) — cash salary | 29,000 |
| 90 | 2026-03-31 | THOR | Salary - Other Staff | 12,000 |
| 91 | 2026-03-31 | THOR | Staff-9880401360 | 550 |
| 92 | 2026-04-01 | THOR | Labour - Cash Exchange (ESOB Tanti) | 5,000 |
| 93 | 2026-04-02 | THOR | Labour - Cash Exchange (ESOB Tanti) | 3,000 |
| 94 | 2026-04-03 | THOR | Labour - Cash Exchange (ESOB Tanti) | 2,000 |
| 95 | 2026-04-04 | THOR | Labour - Cash Exchange (ESOB Tanti) | 5,000 |
| 96 | 2026-04-05 | THOR | Staff-9880401360 | 4,700 |
| 97 | 2026-04-06 | THOR | Salary - Other Staff | 1,500 |
| 98 | 2026-04-07 | THOR | Salary - Other Staff | 3,600 |
| 99 | 2026-04-08 | THOR | Salary - Other Staff | 3,000 |
| 100 | 2026-04-09 | THOR | Prabhakaran (Manager) | 8,000 |
| 101 | 2026-04-10 | THOR | Prabhakaran (Manager) | 925 |
| 102 | 2026-04-10 | THOR | Volipi (Cleaner) | 500 |
| 103 | 2026-04-11 | THOR | Joshi Arjunbhai (Cleaner) | 36,000 |
| 104 | 2026-04-11 | THOR | Ambareesh (Cleaner) | 12,504 |
| 105 | 2026-04-11 | THOR | Volipi (Cleaner) | 10,500 |
| 106 | 2026-04-11 | THOR | Ambareesh (Cleaner) | 10,444 |
| 107 | 2026-04-11 | THOR | Ambareesh (Cleaner) | 3,464 |
| 108 | 2026-04-12 | THOR | Volipi (Cleaner) | 3,000 |
| 109 | 2026-04-13 | THOR | Ram Chandra (Cook/Staff) | 24,000 |
| 110 | 2026-04-13 | THOR | Staff-9880401360 | 1,000 |
| 111 | 2026-04-14 | THOR | Prabhakaran (Manager) | 21,060 |
| 112 | 2026-04-14 | THOR | Vivek | 7,000 |
| 113 | 2026-04-14 | THOR | Staff-8409903591 | 5,000 |
| 114 | 2026-04-14 | THOR | Prabhakaran (Manager) | 2,000 |
| 115 | 2026-04-15 | THOR | Ambareesh (Cleaner) | 2,350 |
| 116 | 2026-04-15 | THOR | Ambareesh (Cleaner) | 2,350 |
| 117 | 2026-04-15 | THOR | Ambareesh (Cleaner) | 2,350 |
| 118 | 2026-04-17 | THOR | Prabhakaran (Manager) | 180 |
| 119 | 2026-04-19 | THOR | Prabhakaran (Manager) | 50 |
| 120 | 2026-04-20 | THOR | Prabhakaran (Manager) | 1,200 |
| 121 | 2026-04-20 | THOR | Prabhakaran (Manager) | 150 |
| 122 | 2026-04-20 | THOR | Prabhakaran (Manager) | 40 |
| 123 | 2026-04-21 | THOR | Prabhakaran (Manager) | 40 |
| 124 | 2026-04-23 | THOR | Prabhakaran (Manager) | 50 |
| 125 | 2026-04-24 | THOR | Lokesh (Receptionist) | 500 |
| 126 | 2026-04-25 | THOR | Vivek | 10,000 |
| 127 | 2026-04-25 | THOR | Prabhakaran (Manager) | 140 |
| 128 | 2026-04-27 | THOR | Lokesh (Receptionist) | 1,000 |
| 129 | 2026-04-29 | THOR | Prabhakaran (Manager) | 20 |
| | | | **TOTAL** | **835,402** |

## Monthly Summary

| Month | Total |
|-------|------:|
| Apr 2026 | 193,617 |
| Dec 2025 | 135,435 |
| Feb 2026 | 171,295 |
| Jan 2026 | 116,714 |
| Mar 2026 | 217,341 |
| Nov 2025 | 1,000 |
| **TOTAL** | **835,402** |
