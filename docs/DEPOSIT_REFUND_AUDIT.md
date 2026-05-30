# Deposit Refund Audit Log

**Source:** `bank_transactions` WHERE `category = 'Tenant Deposit Refund'`  
**Rule:** Re-run `python scripts/_generate_audit_logs.py` after every bank CSV import. This file is the single source of truth for all deposit refunds ever paid.
**Last updated:** 2026-05-30

| # | Date | Account | Name | Amount |
|---|------|---------|------|-------:|
| 1 | 2025-11-08 | THOR | Radhika | 5,000 |
| 2 | 2025-11-30 | THOR | Sanidhya Srivastava | 10,000 |
| 3 | 2025-12-07 | THOR | Refund - Adithya | 14,000 |
| 4 | 2025-12-08 | THOR | Booking Cancellation - Arun Philip | 24,394 |
| 5 | 2025-12-20 | THOR | Majji Divya - Day Wise | 1,200 |
| 6 | 2025-12-22 | THOR | Prem - Day Wise | 250 |
| 7 | 2025-12-29 | THOR | Sethuraman (101) | 7,500 |
| 8 | 2026-01-05 | THOR | Refund - Chandrasekhar | 20,000 |
| 9 | 2026-01-06 | THOR | Unknown-9518874547 | 2,444 |
| 10 | 2026-01-10 | THOR | Refund - T Srinivasa | 1,500 |
| 11 | 2026-01-27 | THOR | Akshay Bhagat (310) | 7,000 |
| 12 | 2026-01-27 | THOR | Refund - Bharath (cancelled) | 2,000 |
| 13 | 2026-01-31 | THOR | Anurag (104) | 11,000 |
| 14 | 2026-01-31 | THOR | Sameer & Rishika (204) | 10,000 |
| 15 | 2026-01-31 | THOR | Booking Cancellation Refund | 2,000 |
| 16 | 2026-02-01 | THOR | Sree Lakshmy AJ | 21,000 |
| 17 | 2026-02-01 | THOR | Anwasha Pal (401) | 21,000 |
| 18 | 2026-02-05 | THOR | Sorabh Mahra | 500 |
| 19 | 2026-02-14 | THOR | Omkar | 32 |
| 20 | 2026-02-16 | THOR | Refund - Chandrasekhar | 3,000 |
| 21 | 2026-02-23 | THOR | Yogeshwaran (411) | 8,500 |
| 22 | 2026-02-28 | THOR | Anandhu (208) | 9,500 |
| 23 | 2026-02-28 | THOR | Gokul Harish (104) | 7,000 |
| 24 | 2026-02-28 | THOR | Unknown-7661991929 | 4,000 |
| 25 | 2026-03-02 | THOR | Sherylin M Rajan (210) | 10,000 |
| 26 | 2026-03-03 | THOR | Prem - Day Wise | 50 |
| 27 | 2026-03-05 | THOR | Ankit | 100 |
| 28 | 2026-03-11 | THOR | Rithiv | 1,000 |
| 29 | 2026-03-11 | THOR | Anudeep | 100 |
| 30 | 2026-03-12 | THOR | Akshay Gupta (219) | 10,000 |
| 31 | 2026-03-12 | THOR | Prem (day-wise) | 50 |
| 32 | 2026-03-13 | THOR | Refund - K S Shyam Reddy | 24,500 |
| 33 | 2026-03-14 | THOR | Soham Vijay (219) | 3,100 |
| 34 | 2026-03-15 | THOR | Tejas Jallapelli (516) | 298 |
| 35 | 2026-03-17 | THOR | Refund - Swami Venkatesh | 1,263 |
| 36 | 2026-03-21 | THOR | Subhadeep Sikdar (413) | 17,500 |
| 37 | 2026-03-22 | THOR | Dhruv | 60 |
| 38 | 2026-03-26 | THOR | Unknown-9947814505 | 200 |
| 39 | 2026-03-30 | THOR | Adithya Saraf | 22,000 |
| 40 | 2026-03-31 | THOR | Refund - Amal | 19,000 |
| 41 | 2026-03-31 | PERSONAL_SBI_0167 | Deposit Refund — Anumola Yoga Anil Kumar | 11,000 |
| 42 | 2026-03-31 | PERSONAL_SBI_0167 | Deposit Refund — Aahil Rafiq | 11,000 |
| 43 | 2026-03-31 | THOR | Lakshmi Priya (215) | 10,000 |
| 44 | 2026-03-31 | THOR | Refund - Kuhan Mohan | 8,500 |
| 45 | 2026-03-31 | THOR | Hafiz Khan (308) | 8,000 |
| 46 | 2026-03-31 | THOR | Refund - Siva Kumar | 8,000 |
| 47 | 2026-03-31 | THOR | Refund - Vijay Kumar | 6,720 |
| 48 | 2026-03-31 | THOR | Refund - Mohammed Umar | 5,000 |
| 49 | 2026-03-31 | THOR | Gotham | 4,000 |
| 50 | 2026-03-31 | THOR | Rishwanth | 1,000 |
| 51 | 2026-04-03 | THOR | Nirmal Kumar (612) | 20,600 |
| 52 | 2026-04-05 | THOR | Sakshi | 16,000 |
| 53 | 2026-04-05 | THOR | Room 610 Akshayaratna | 250 |
| 54 | 2026-04-05 | THOR | Ankit Kumar | 100 |
| 55 | 2026-04-08 | THOR | Satish Waghela (621) | 8,000 |
| 56 | 2026-04-10 | THOR | Yatam Ramakanth (520) | 3,500 |
| 57 | 2026-04-11 | THOR | Refund - Shaurya Shah | 9,500 |
| 58 | 2026-04-15 | PERSONAL_SBI_0167 | Deposit Refund — P Deepa | 9,870 |
| 59 | 2026-04-15 | PERSONAL_SBI_0167 | Deposit Refund — P Deepa | 100 |
| 60 | 2026-04-16 | THOR | Tejas Jallapelli (516) | 8,668 |
| 61 | 2026-04-16 | THOR | Nakul Gupta (521) | 2,600 |
| 62 | 2026-04-17 | THOR | Shashank (521) | 3,050 |
| 63 | 2026-04-21 | THOR | Booking Cancellation Refund | 1,500 |
| 64 | 2026-04-22 | THOR | Sujal Jaiswal (217) | 8,000 |
| 65 | 2026-04-25 | THOR | Soumya Agarwal (206) | 22,000 |
| 66 | 2026-04-25 | THOR | Refund - Shubhi Vishnoi | 1,750 |
| 67 | 2026-04-25 | THOR | Bhanu Prakash | 175 |
| 68 | 2026-04-26 | THOR | Neha Pramod (210) | 8,000 |
| 69 | 2026-04-28 | THOR | Adnan Doshi (510) | 9,500 |
| 70 | 2026-04-28 | THOR | Sanjay (520) | 8,500 |
| 71 | 2026-04-28 | THOR | Refund - Shashank B V | 1,000 |
| 72 | 2026-04-30 | THOR | Shubham Mishra (514) | 8,500 |
| | | | **TOTAL** | **526,424** |

## Monthly Summary

| Month | Total |
|-------|------:|
| Apr 2026 | 151,163 |
| Dec 2025 | 47,344 |
| Feb 2026 | 74,532 |
| Jan 2026 | 55,944 |
| Mar 2026 | 182,441 |
| Nov 2025 | 15,000 |
| **TOTAL** | **526,424** |
