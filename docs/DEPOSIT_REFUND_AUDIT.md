# Deposit Refund Audit Log

**Source:** `bank_transactions` WHERE `category = 'Tenant Deposit Refund'`  
**Rule:** Re-run `python scripts/_generate_audit_logs.py` after every bank CSV import. This file is the single source of truth for all deposit refunds ever paid.
**Last updated:** 2026-08-08

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
| 16 | 2026-02-01 | THOR | Anwasha Pal (401) | 21,000 |
| 17 | 2026-02-01 | THOR | Sree Lakshmy AJ | 21,000 |
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
| 73 | 2026-05-01 | THOR | reclassified (PnL) | 26,500 |
| 74 | 2026-05-01 | THOR | reclassified (PnL) | 7,600 |
| 75 | 2026-05-02 | THOR | UNKNOWN: o:6361615610@axl/tejas refund | 10,000 |
| 76 | 2026-05-04 | HULK | reclassified (PnL) | 23,000 |
| 77 | 2026-05-04 | HULK | reclassified (PnL) | 16,500 |
| 78 | 2026-05-04 | THOR | UNKNOWN: o:jaya56793@okaxis/jaya prakash 511 refu | 9,500 |
| 79 | 2026-05-05 | HULK | reclassified (PnL) | 13,000 |
| 80 | 2026-05-08 | THOR | UNKNOWN: o:lakshmipathikarkuri@ibl/refund | 1,200 |
| 81 | 2026-05-09 | THOR | UNKNOWN: o:7981943779@axl/deposit refund | 7,000 |
| 82 | 2026-05-12 | HULK | reclassified (PnL) | 5,000 |
| 83 | 2026-05-15 | THOR | UNKNOWN: o:ait2004.paddy@okaxis/anand 207 deposit | 21,000 |
| 84 | 2026-05-23 | THOR | UNKNOWN: o:pras74514@okaxis/tenant refund | 10,000 |
| 85 | 2026-05-23 | HULK | Rithiv | 7,000 |
| 86 | 2026-05-23 | HULK | UNKNOWN: o:giddu12345@axl/Security deposit refund | 1,000 |
| 87 | 2026-05-24 | HULK | UNKNOWN: o:8816829590@pz/Security deposit refund  | 9,000 |
| 88 | 2026-05-27 | THOR | UNKNOWN: o:venkathasupramanian@okicici/tenant dep | 22,000 |
| 89 | 2026-05-29 | HULK | UNKNOWN: o:9910022238@ptsbi/Refund | 21,000 |
| 90 | 2026-05-29 | THOR | UNKNOWN: o:8260695816@pthdfc/tenant refund | 10,000 |
| 91 | 2026-05-30 | THOR | UNKNOWN: o:9398692454@ptaxis/ashok tenant refund | 9,000 |
| 92 | 2026-05-30 | THOR | UNKNOWN: o:prajwalrangegowda@ibl/prajwal 414 tena | 8,500 |
| 93 | 2026-05-30 | THOR | UNKNOWN: o:gnanesh.varupula@ybl/ganesh tenant ref | 8,000 |
| 94 | 2026-05-30 | THOR | UNKNOWN: o:sumathisubbiah9294@okhdfcbank/ulaganat | 8,000 |
| 95 | 2026-05-31 | THOR | UNKNOWN: o:rajdeepbandyopadhaya@okhdfcbank/rajdee | 16,000 |
| 96 | 2026-05-31 | THOR | UNKNOWN: o:akshita1009@oksbi/akshita tenant depos | 5,500 |
| 97 | 2026-05-31 | HULK | UNKNOWN: o:akshita1009@oksbi/Akshita Tenent Refun | 500 |
| 98 | 2026-06-02 | HULK | UNKNOWN: o:shubhamyadav04.a@okhdfcbank/Refund | 5,750 |
| 99 | 2026-06-03 | THOR | UNKNOWN: o:008anirudhnambeeshan@okaxis/tenant ref | 13,000 |
| 100 | 2026-06-03 | THOR | UNKNOWN: o:9392654824@ibl/refund | 2,000 |
| 101 | 2026-06-04 | THOR | UNKNOWN: o:9561114302@superyes/zero deposit refun | 10,000 |
| 102 | 2026-06-05 | THOR | UNKNOWN: o:sohamggl@oksbi/soham 305 tenant refund | 14,000 |
| 103 | 2026-06-05 | THOR | UNKNOWN: o:6352435163@pz/pratik 517 tenant refund | 7,500 |
| 104 | 2026-06-05 | HULK | UNKNOWN: o:sonali270702@okhdfcbank/Sonali refund | 4,000 |
| 105 | 2026-06-06 | HULK | UNKNOWN: o:arrowhdfc@ybl/Ajay Ramachandran refund | 12,000 |
| 106 | 2026-06-06 | HULK | UNKNOWN: o:arpitmathur23@okicici/Arpit Mathur ref | 10,000 |
| 107 | 2026-06-06 | HULK | UNKNOWN: o:surajsh1602@okicici/Suraj sukumar refu | 9,000 |
| 108 | 2026-06-06 | HULK | UNKNOWN: o:9001291690@ptyes/Priyanshi refund | 8,000 |
| 109 | 2026-06-06 | THOR | UNKNOWN: o:anugunrain-1@okicici/624 tenant refund | 7,000 |
| 110 | 2026-06-06 | THOR | UNKNOWN: o:6200232250@axl/surajit 224 tenant refu | 7,000 |
| 111 | 2026-06-06 | HULK | UNKNOWN: o:amishamohta17@okicici/Amisha mohta ref | 4,000 |
| 112 | 2026-06-06 | HULK | UNKNOWN: o:8130422450@pthdfc/Preesha agarwal refu | 4,000 |
| 113 | 2026-06-06 | HULK | UNKNOWN: o:9116037600@ptsbi/Sparsh gupta refund | 4,000 |
| 114 | 2026-06-06 | THOR | UNKNOWN: o:harshuhari2002@okhdfcbank/harshita 103 | 3,500 |
| 115 | 2026-06-06 | THOR | UNKNOWN: o:8106778788-2@axl/Bhanu prakash 314 ten | 3,234 |
| 116 | 2026-06-06 | THOR | Akshayaratna (610) | 3,125 |
| 117 | 2026-06-06 | THOR | UNKNOWN: o:guptatej98-1@okicici/tejas tenant depo | 3,000 |
| 118 | 2026-06-06 | HULK | UNKNOWN: o:9920872075@pthdfc/Manya Agarwal refund | 3,000 |
| 119 | 2026-06-07 | HULK | UNKNOWN: o:9868072525@ptyes/Rakshit Joshi refund | 10,000 |
| 120 | 2026-06-07 | THOR | UNKNOWN: o:tanishka.baderia@oksbi/tanishka tenant | 8,000 |
| 121 | 2026-06-07 | HULK | UNKNOWN: o:9867007183@ybl/Jay maharajan refund | 4,000 |
| 122 | 2026-06-07 | HULK | UNKNOWN: o:6289132039@ybl/Diya refund | 4,000 |
| 123 | 2026-06-07 | HULK | UNKNOWN: o:gayatrilkulkarni99@okicici/Gayatri ref | 4,000 |
| 124 | 2026-06-07 | THOR | UNKNOWN: o:anmolgupta7994@okhdfcbank/514 tenant d | 4,000 |
| 125 | 2026-06-07 | HULK | UNKNOWN: o:7982664713@pthdfc/Roshni kumari refund | 3,000 |
| 126 | 2026-06-07 | HULK | UNKNOWN: o:9578662395@yescred/Raja refund | 1,300 |
| 127 | 2026-06-08 | HULK | UNKNOWN: o:gauravshukla9182@oksbi/Gaurav refund | 10,000 |
| 128 | 2026-06-09 | HULK | UNKNOWN: o:ivishchoudhary5-1@okhdfcbank/Ivish ref | 3,000 |
| 129 | 2026-06-10 | HULK | UNKNOWN: o:suraj23dec@ybl/Suraj Singh refund | 1,000 |
| 130 | 2026-06-11 | HULK | UNKNOWN: o:arpit-510@ptaxis/Arpit singh refund | 1,000 |
| 131 | 2026-06-12 | HULK | UNKNOWN: o:9542612346-4@ybl/Dara krishna refund | 1,000 |
| 132 | 2026-06-12 | HULK | UNKNOWN: o:nareshdpi20@ybl/Naresh refund | 1,000 |
| 133 | 2026-06-14 | HULK | UNKNOWN: o:stebinstanly01-1@oksbi/Stebuin deposit | 1,000 |
| 134 | 2026-06-15 | HULK | UNKNOWN: o:8086808982@ptaxis/Sajith V refund | 10,000 |
| 135 | 2026-06-16 | HULK | UNKNOWN: o:9080915335@pthdfc/Subashini advance re | 5,000 |
| 136 | 2026-06-16 | HULK | UNKNOWN: o:dodiyampavankumar2001-2@oksbi/Pavan Ku | 1,000 |
| 137 | 2026-06-17 | HULK | Refund - Shashank B V | 1,000 |
| 138 | 2026-06-19 | HULK | UNKNOWN: o:9509803517@pthdfc/Revanth refund | 10,000 |
| 139 | 2026-06-19 | HULK | Bharath (cancelled) | 1,000 |
| 140 | 2026-06-22 | HULK | UNKNOWN: o:amohanamohan2-1@okaxis/Refund | 1,000 |
| 141 | 2026-06-23 | THOR | UNKNOWN: o:shivenkeshav0424@okaxis/shivam 608 ten | 10,000 |
| 142 | 2026-06-24 | THOR | UNKNOWN: o:vasanthraitt13-2@okicici/vasanth rai t | 11,000 |
| 143 | 2026-06-26 | THOR | UNKNOWN: o:cheran411-1@okicici/aravind 609 tenant | 8,000 |
| 144 | 2026-06-26 | HULK | UNKNOWN: o:9500747313@superyes/Refund | 1,000 |
| 145 | 2026-06-26 | HULK | UNKNOWN: o:udhaya1592@okhdfcbank/Refund | 1,000 |
| 146 | 2026-06-26 | HULK | UNKNOWN: o:9605132142@pthdfc/Refund | 1,000 |
| 147 | 2026-06-27 | THOR | Refund - Naitik Raj (6299395850) | 8,000 |
| 148 | 2026-06-28 | THOR | Booking Cancellation Refund | 8,500 |
| 149 | 2026-06-28 | HULK | UNKNOWN: o:jeevasubramani46@oksbi/Refund | 3,000 |
| 150 | 2026-06-28 | HULK | UNKNOWN: o:jeevasubramani46@oksbi/Refund | 2,000 |
| 151 | 2026-06-28 | HULK | UNKNOWN: o:lakshayfriends243@okhdfcbank/Lakshay r | 100 |
| 152 | 2026-06-29 | THOR | UNKNOWN: o:sneehaah-1@oksbi/sneha tenant deposit  | 23,000 |
| 153 | 2026-06-29 | THOR | UNKNOWN: o:6363471049@ptyes/vishnu 320 tenant dep | 8,500 |
| 154 | 2026-06-30 | THOR | UNKNOWN: o:anurondutta-1@okicici/anuron 105 tenan | 24,000 |
| 155 | 2026-06-30 | THOR | UNKNOWN: o:pageychinmay@okaxis/112 tenant deposit | 17,000 |
| 156 | 2026-06-30 | THOR | UNKNOWN: o:6388741169-2@axl/608 tenant deposit re | 10,000 |
| 157 | 2026-06-30 | HULK | Refund - Manideep (tenant #566) | 9,500 |
| 158 | 2026-06-30 | HULK | UNKNOWN: o:9381025664@ybl/Refund | 9,000 |
| 159 | 2026-06-30 | THOR | UNKNOWN: o:7204447908@ibl/222 tenant deposit refu | 7,500 |
| 160 | 2026-06-30 | HULK | UNKNOWN: o:9626563883@ibl/Refund | 6,500 |
| 161 | 2026-06-30 | HULK | UNKNOWN: o:queenofqueens945@okhdfcbank/Mounika re | 5,500 |
| 162 | 2026-06-30 | HULK | UNKNOWN: o:9381347841@axl/Veeram lohit kumar refu | 5,500 |
| 163 | 2026-06-30 | HULK | UNKNOWN: o:singhal.anish@ptyes/Anish Singal Refun | 5,000 |
| 164 | 2026-06-30 | HULK | Sorabh Mahra | 1,000 |
| 165 | 2026-07-01 | HULK | UNKNOWN: o:abhinav.rastogi4567-1@oksbi/Payment | 3,750 |
| 166 | 2026-07-03 | HULK | UNKNOWN: o:8527089555@hdfc/Refund | 14,000 |
| 167 | 2026-07-06 | HULK | UNKNOWN: o:akaashvp-1@okhdfcbank/Refund | 2,000 |
| 168 | 2026-07-09 | THOR | Booking Cancellation Refund | 1,000 |
| 169 | 2026-07-10 | HULK | UNKNOWN: o:venkatsai50@ybl/Refund | 1,000 |
| 170 | 2026-07-11 | HULK | UNKNOWN: o:pgkutty@okhdfcbank/Refund | 4,000 |
| 171 | 2026-07-17 | HULK | UNKNOWN: o:7053001300@axl/Refund | 3,500 |
| 172 | 2026-07-18 | HULK | UNKNOWN: o:poojalingraj22@ybl/Refund | 1,500 |
| 173 | 2026-07-18 | HULK | UNKNOWN: o:8746073467-7@ybl/Refund | 1,500 |
| 174 | 2026-07-24 | THOR | UNKNOWN: o:samaptika.singh@okhdfcbank/502 tenant  | 10,500 |
| 175 | 2026-07-25 | THOR | UNKNOWN: o:yashaswa.ram-1@oksbi/302 yashaswa ram  | 12,500 |
| 176 | 2026-07-25 | HULK | UNKNOWN: o:chaitanyatalokar24@okaxis/Refund | 3,750 |
| 177 | 2026-07-26 | HULK | UNKNOWN: o:7016163544@ibl/Refund | 9,500 |
| 178 | 2026-07-28 | HULK | UNKNOWN: o:sakshammittal111@oksbi/Refund | 1,000 |
| 179 | 2026-07-29 | HULK | UNKNOWN: o:pratham.sk333@oksbi/Refund | 8,500 |
| 180 | 2026-07-29 | HULK | UNKNOWN: o:7975197361@ybl/Refund | 5,000 |
| 181 | 2026-07-29 | HULK | UNKNOWN: o:aryamanjoshi6@okhdfcbank/Refund | 4,500 |
| 182 | 2026-07-30 | HULK | UNKNOWN: o:9392884803@ybl/Refund | 9,000 |
| 183 | 2026-07-30 | HULK | UNKNOWN: o:akshatajitsaraswat@oksbi/Refund | 8,500 |
| 184 | 2026-07-30 | HULK | UNKNOWN: o:manoj19sivagiri@okaxis/Refund | 7,000 |
| 185 | 2026-07-31 | THOR | UNKNOWN: o:rkkishnani99@oksbi/jatin 412 tenant de | 20,000 |
| 186 | 2026-07-31 | THOR | UNKNOWN: o:9014179723@axl/112 tenant deposit refu | 13,500 |
| 187 | 2026-07-31 | THOR | UNKNOWN: o:prateeksinghkhutail-1@okhdfcbank/605 p | 11,000 |
| 188 | 2026-07-31 | THOR | UNKNOWN: o:bittubharadia-1@okhdfcbank/605 sankar  | 11,000 |
| 189 | 2026-07-31 | HULK | UNKNOWN: o:sohanmonies2003@okhdfcbank/Refund | 8,500 |
| 190 | 2026-07-31 | THOR | UNKNOWN: o:6300729676@ptyes/220 tenant deposit re | 8,000 |
| | | | **TOTAL** | **1,394,233** |

## Monthly Summary

| Month | Total |
|-------|------:|
| Apr 2026 | 151,163 |
| Dec 2025 | 47,344 |
| Feb 2026 | 74,532 |
| Jan 2026 | 55,944 |
| Jul 2026 | 184,000 |
| Jun 2026 | 408,009 |
| Mar 2026 | 182,441 |
| May 2026 | 275,800 |
| Nov 2025 | 15,000 |
| **TOTAL** | **1,394,233** |
