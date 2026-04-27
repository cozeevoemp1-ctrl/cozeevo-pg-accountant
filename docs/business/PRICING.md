# Cozeevo PG Accountant — Pricing Tiers

> Target market: PG owners in Bangalore / Hyderabad / Pune with 30–500 beds.
> Distribution: direct WhatsApp demo → CA partnerships → Facebook/Instagram PG groups.

---

## Tiers

> Updated 2026-04-26: PWA (forms + voice) added. Growth = forms. Pro = forms + voice.

| Feature | **Starter** (Free) | **Growth** ₹799/month | **Pro** ₹1,999/month |
|---|---|---|---|
| **Who** | Try it out | 1 property, up to 50 beds | Multi-property, 200+ beds |
| WhatsApp AI Bot (owner + tenant) | ✅ | ✅ | ✅ |
| Tenant queries (own rent, dues, room) | ✅ | ✅ | ✅ |
| Owner queries (who paid, overdue) | ✅ | ✅ | ✅ |
| Occupancy status | ✅ | ✅ | ✅ |
| **Kozzy PWA — Staff forms app** | ❌ | ✅ | ✅ |
| **Collect payment (form)** | ❌ | ✅ | ✅ |
| **Check-in / Check-out (form)** | ❌ | ✅ | ✅ |
| **Day-wise booking (form)** | ❌ | ✅ | ✅ |
| **Dues query (form)** | ❌ | ✅ | ✅ |
| **"Hey Kozzy" voice assistant** | ❌ | ❌ | ✅ |
| **Tap-to-talk voice commands** | ❌ | ❌ | ✅ |
| **Multi-language voice (EN/TA/TE/HI)** | ❌ | ❌ | ✅ |
| Tenant onboarding (KYC via WhatsApp) | ❌ | ✅ | ✅ |
| Checkout checklist | ❌ | ✅ | ✅ |
| P&L from bank statement (PDF upload) | ❌ | ✅ | ✅ |
| Expense classification (15 categories) | ❌ | ✅ | ✅ |
| CA-ready Excel export | ❌ | ✅ | ✅ |
| Staff roles | admin only | admin + 3 staff | Unlimited |
| Properties | 1 | 1 | Up to 5 |
| DB capacity | 30 tenants | 75 tenants | 500 tenants |
| UPI reconciliation (multi-source dedup) | ❌ | ❌ | ✅ |
| Bank + Paytm + PhonePe + Razorpay match | ❌ | ❌ | ✅ |
| Unmatched transaction alerts on WhatsApp | ❌ | ❌ | ✅ |
| Property-wise P&L reports | ❌ | ❌ | ✅ |
| Priority support | ❌ | ❌ | ✅ |

---

## Free Tier Details

- No credit card required
- Full 30-day access to Growth features
- After 30 days: drops to Starter (tenant + owner basic queries only)
- **Goal:** owner gets hooked on P&L report + onboarding flow in first month

---

## Add-ons (any paid tier)

| Add-on | Price |
|---|---|
| Extra property (extra WhatsApp number) | ₹499/month |
| Custom expense categories | ₹999 one-time |
| Historical Excel data import | ₹1,999 one-time |
| Setup + onboarding assistance (video call) | ₹2,999 one-time |

---

## Why This Pricing Works

| Comparison | Cost |
|---|---|
| Part-time accounts assistant | ₹8,000–12,000/month |
| Tally + data entry person | ₹5,000–8,000/month |
| **Cozeevo Growth** | **₹799/month** |
| **Cozeevo Pro** | **₹1,999/month** |

**The pitch:** *"Your staff gets an app. You get WhatsApp. Your tenants get WhatsApp. One system, one source of truth."*

**Voice cost per Pro customer:** ~₹250–400/month (Groq Whisper Turbo at 4hrs/day). Margin at Pro: ~₹1,500+/month.

---

## Go-to-Market

1. **Beta** — 5 PG owners (friends/network) at free for 3 months → get testimonials
2. **Referral** — refer a PG owner → 1 month free
3. **CA partnerships** — CA firms recommend to PG clients → CA earns ₹500/referral/month
4. **Facebook/WhatsApp groups** — PG owner groups in Bangalore, Hyderabad, Pune
5. **Hostinger VPS** (~$5/month) → same server serves all customers (config-driven per customer)

---

## Tech Cost Per Customer

| Component | Monthly Cost |
|---|---|
| Supabase (per PG) | Free tier → $25/month at scale |
| Meta WhatsApp API | Free (1,000 conversations/month free) |
| Hostinger VPS (shared) | ~₹400/month shared across customers |
| Ollama LLM | Free (runs on VPS) |
| **Total at Starter scale** | **~₹500–800/customer** |

Margin kicks in at Growth (₹799) and Pro (₹1,999) tiers.

---

## Roadmap Lock-in Features (coming with LedgerWorker)

These are **Pro-only** features that justify ₹1,999:
- Multi-source UPI reconciliation (bank + Paytm + PhonePe + Razorpay)
- Unmatched transaction WhatsApp alerts
- Monthly reconciliation summary pushed automatically on 1st of month
- `finance/` package: standalone or WhatsApp-triggered

> See `FINANCIAL_VISION.md` for technical design of the reconciliation engine.
