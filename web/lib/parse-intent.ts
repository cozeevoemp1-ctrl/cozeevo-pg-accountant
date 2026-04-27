/**
 * Client-side voice intent parser — no API call needed.
 * Handles PG payment voice commands like:
 *   "got 8000 from Ravi cash"
 *   "collected 12k from Suresh room 201 UPI"
 *   "15000 Priya GPay"
 */

import type { PaymentIntent } from "./api";

const METHOD_MAP: Record<string, string> = {
  gpay: "UPI", phonepe: "UPI", paytm: "UPI", upi: "UPI",
  online: "UPI", neft: "UPI", imps: "UPI", rtgs: "UPI",
  cash: "CASH", bank: "BANK", card: "CARD",
};

const SKIP = new Set([
  "got", "get", "collected", "received", "paid", "from", "for",
  "room", "the", "a", "and", "in", "at", "of", "with", "via",
  "rupees", "rs", "inr", "nothing", "skip", "later",
]);

export function parseVoiceIntent(text: string): PaymentIntent {
  const lower = text.toLowerCase().trim();

  // ── Amount ────────────────────────────────────────────────────────────────
  let amount: number | null = null;
  const amtMatch = lower.match(/(\d[\d,]*)\.?(\d*)\s*k\b/);
  if (amtMatch) {
    const whole = amtMatch[1].replace(/,/g, "");
    const frac = amtMatch[2] ? Number(`0.${amtMatch[2]}`) : 0;
    amount = (parseInt(whole) + frac) * 1000;
  } else {
    const plain = lower.match(/(\d[\d,]{2,})/);
    if (plain) amount = parseInt(plain[1].replace(/,/g, ""));
  }

  // ── Method ────────────────────────────────────────────────────────────────
  let method: string | null = null;
  for (const [kw, val] of Object.entries(METHOD_MAP)) {
    if (lower.includes(kw)) { method = val; break; }
  }

  // ── Room ──────────────────────────────────────────────────────────────────
  let tenant_room: string | null = null;
  const roomMatch = text.match(/\b([A-Za-z]?\d{2,4}[A-Za-z]?)\b/g);
  if (roomMatch) {
    // Exclude the amount itself
    const candidates = roomMatch.filter((r) => {
      const n = parseInt(r.replace(/\D/g, ""));
      return !(amount && n === amount);
    });
    if (candidates.length) tenant_room = candidates[0].toUpperCase();
  }

  // ── Name ─────────────────────────────────────────────────────────────────
  let tenant_name: string | null = null;
  const words = text.split(/\s+/);
  const nameWords: string[] = [];
  for (const w of words) {
    const clean = w.replace(/[^a-zA-Z]/g, "");
    if (!clean || clean.length < 2) continue;
    if (SKIP.has(clean.toLowerCase())) continue;
    if (METHOD_MAP[clean.toLowerCase()]) continue;
    // Skip if it looks like a room number (letter + digits)
    if (/^[A-Za-z]?\d+$/.test(clean)) continue;
    // Skip amount words
    if (/^\d/.test(clean)) continue;
    // Capitalized or mixed case word — treat as name
    if (/[A-Za-z]{2,}/.test(clean)) nameWords.push(clean);
    if (nameWords.length === 2) break;
  }
  if (nameWords.length) tenant_name = nameWords.join(" ");

  const intent = amount !== null ? "log_payment" : "unknown";

  return { intent, amount, tenant_name, tenant_room, method, for_type: "rent" };
}
