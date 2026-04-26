/**
 * Typed API client for /api/v2/app/* (FastAPI backend).
 * Reads the Supabase access token from the current session for JWT auth.
 */
import { supabase } from "./supabase";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function _authHeaders(): Promise<Record<string, string>> {
  const { data } = await supabase().auth.getSession();
  const token = data.session?.access_token;
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function _get<T>(path: string): Promise<T> {
  const headers = await _authHeaders();
  const res = await fetch(`${BASE_URL}${path}`, { headers });
  if (!res.ok) throw new Error(`GET ${path} → ${res.status}`);
  return res.json() as Promise<T>;
}

async function _post<T>(path: string, body: unknown): Promise<T> {
  const headers = { ...(await _authHeaders()), "Content-Type": "application/json" };
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "POST",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `POST ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

// ── Typed response shapes ────────────────────────────────────────────────────

export interface CollectionSummary {
  period_month: string;
  expected: number;
  collected: number;
  pending: number;
  collection_pct: number;
  rent_collected: number;
  maintenance_collected: number;
  deposits_received: number;
  booking_advances: number;
  overdue_count: number;
}

export interface PaymentResponse {
  payment_id: number;
  new_balance: number;
  receipt_sent: boolean;
}

export interface PaymentCreate {
  tenant_id: number;
  amount: number;
  method: "UPI" | "CASH" | "BANK" | "CARD" | "OTHER";
  for_type: "rent" | "deposit" | "maintenance" | "booking" | "adjustment";
  period_month: string; // YYYY-MM
  notes?: string;
}

// ── API calls ────────────────────────────────────────────────────────────────

export function getCollectionSummary(periodMonth: string): Promise<CollectionSummary> {
  return _get(`/api/v2/app/reporting/collection?period_month=${encodeURIComponent(periodMonth)}`);
}

export function createPayment(body: PaymentCreate): Promise<PaymentResponse> {
  return _post("/api/v2/app/payments", body);
}
