# Premium Tenant Reconciliation — 2026-04-21
Source sheet: `Cozeevo Operations v2` → tab `Long term`
Sheet ID: `1Vr_fSIOuuKBK4MWF-FVqgAIUPbqun3POszaXYfj-Ea0`

## Counts
- Sheet (CHECKIN + sharing contains 'prem'): **22**
- DB (status=active, sharing_type=premium): **23**
- Kiran's expected count: **22**

## Sheet premium CHECKIN rows

| Row | Name | Phone | Room | Sharing |
|---|---|---|---|---|
| 16 | Anuron Dutta | 9831150344 | 105 | premium |
| 17 | Suraj Prasana | 9481617420 | 106 | premium |
| 32 | Karesse | 9561114302 | 119 | premium |
| 53 | Soumya Agarwal | 7389281804 | 206 | premium |
| 54 | Anand | 7550258254 | 207 | premium |
| 94 | Jeewan kant Oberoi | 9878817607 | 305 | premium |
| 95 | Soham Das | 8240058819 | 306 | premium |
| 104 | Venkatha Supramanian | 9841155410 | 311 | premium |
| 132 | Anukriti Dubey | 8875211021 | 402 | premium |
| 133 | Charul Agarwal | 9045520950 | 403 | premium |
| 168 | Sneha AK | 8547554789 | 503 | premium |
| 173 | Saurav Kalia | 8527089555 | 505 | premium |
| 202 | Ganesh Divekar | 8459684546 | 603 | premium |
| 203 | Sarang Swami | 7798675977 | 604 | premium |
| 211 | Omkar Vijaykumar Tuppe | 9665836934 | 611 | premium |
| 213 | Shubham Mishra | 8792394303 | 514 | premium |
| 219 | Pranay samariya | 9571468921 | G02 | premium |
| 281 | Surya shivani | 9619266749 | 606 | premium |
| 297 | Dhamodharan | 9080293318 | G19 | premium |
| 320 | Rakshit Joshi | 98680 72525 | 208 | Premium |
| 323 | Arpit Mathur | 8980933388 | 607 | Premium |
| 339 | T.Rakesh Chetan | 9515739255 | 415 | premium |

## DB premium active tenancies

| Name | Phone | Room |
|---|---|---|
| Anand | +917550258254 | 207 |
| Anukriti Dubey | +918875211021 | 402 |
| Anuron Dutta | +919831150344 | 105 |
| Arpit Mathur | +918980933388 | 607 |
| Charul Agarwal | +919045520950 | 403 |
| Dhamodharan | +919080293318 | G19 |
| Ganesh Divekar | +918459684546 | 603 |
| Jeewan Kant Oberoi | +919878817607 | 305 |
| Karesse | +919561114302 | 119 |
| Omkar Vijaykumar Tuppe | +919665836934 | 611 |
| Pranay Samariya | +919571468921 | G02 |
| Rakesh Thallapally | 9515739255 | 415 |
| Rakshit Joshi | +919868072525 | 208 |
| Sarang Swami | +917798675977 | 604 |
| Saurav Kalia | +918527089555 | 505 |
| Shubham Mishra | +918792394303 | 514 |
| Sneha Ak | +918547554789 | 503 |
| Soham Das | +918240058819 | 306 |
| Soumya Agarwal | +917389281804 | 206 |
| Suraj Prasana | +919481617420 | 106 |
| Surya Shivani | +919619266749 | 606 |
| T.Rakesh Chetan | +919515739255 | 415 |
| Venkatha Supramanian | +919841155410 | 311 |

## Mismatches

### Only in Sheet (0) — sheet says premium, DB doesn't

_None._

### Only in DB (0) — DB says premium, Sheet doesn't

_None._

## DB duplicates by phone (1)

| Phone | Count | Records |
|---|---|---|
| 9515739255 | 2 | Rakesh Thallapally (room 415, raw=9515739255); T.Rakesh Chetan (room 415, raw=+919515739255) |

## Suggested correction workflow

1. For each row in 'Only in Sheet': check physical room occupancy — is tenant actually alone in a multi-bed room?
2. For each row in 'Only in DB': check sheet column M — typo or genuine downgrade?
3. Once verified, update DB via bot command (never direct SQL). Sheet is read-only mirror.
4. Target: reconcile to Kiran's expected count of 22.
