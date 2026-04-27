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

async function _postForm<T>(path: string, form: FormData): Promise<T> {
  const headers = await _authHeaders();
  const res = await fetch(`${BASE_URL}${path}`, { method: "POST", headers, body: form });
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

export interface KpiResponse {
  occupied_beds: number;
  total_beds: number;
  vacant_beds: number;
  occupancy_pct: number;
  active_tenants: number;
  checkins_today: number;
  checkouts_today: number;
  open_complaints: number;
}

export interface ActivityItem {
  tenant_name: string;
  room_number: string;
  amount: number;
  method: string;
  for_type: string;
  payment_date: string;
}

export interface ActivityResponse {
  items: ActivityItem[];
}

export interface TranscribeResponse {
  text: string;
  language: string;
  duration_seconds: number;
}

export interface PaymentIntent {
  intent: string;
  amount: number | null;
  tenant_name: string | null;
  tenant_room: string | null;
  method: string | null;
  for_type: string;
}

// ── API calls ────────────────────────────────────────────────────────────────

export function getCollectionSummary(periodMonth: string): Promise<CollectionSummary> {
  return _get(`/api/v2/app/reporting/collection?period_month=${encodeURIComponent(periodMonth)}`);
}

export function getKpi(): Promise<KpiResponse> {
  return _get("/api/v2/app/reporting/kpi");
}

export function getRecentActivity(limit = 20): Promise<ActivityResponse> {
  return _get(`/api/v2/app/activity/recent?limit=${limit}`);
}

export function createPayment(body: PaymentCreate): Promise<PaymentResponse> {
  return _post("/api/v2/app/payments", body);
}

export function transcribeAudio(blob: Blob, mime: string): Promise<TranscribeResponse> {
  const form = new FormData();
  form.append("audio", blob, mime.includes("mp4") ? "audio.mp4" : "audio.webm");
  return _postForm("/api/v2/app/voice/transcribe", form);
}

export function extractPaymentIntent(transcript: string): Promise<PaymentIntent> {
  return _post("/api/v2/app/voice/intent", { transcript });
}

export interface TenantSearchResult {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  rent: number;
  status: string;
}

export interface TenantDues {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  rent: number;
  dues: number;
  last_payment_date: string | null;
  last_payment_amount: number | null;
  period_month: string;
}

export function searchTenants(q: string): Promise<TenantSearchResult[]> {
  return _get<TenantSearchResult[]>(`/api/v2/app/tenants/search?q=${encodeURIComponent(q)}`);
}

export function getTenantDues(tenancyId: number): Promise<TenantDues> {
  return _get<TenantDues>(`/api/v2/app/tenants/${tenancyId}/dues`);
}

// ── Physical check-in ────────────────────────────────────────────────────────

export interface CheckinPreview {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  actual_date: string;
  agreed_checkin_date: string | null;
  agreed_rent: number;
  security_deposit: number;
  booking_amount: number;
  prorated_rent: number;
  first_month_total: number;
  balance_due: number;
  overpayment: number;
  date_changed: boolean;
}

export interface CheckinResponse {
  tenancy_id: number;
  checkin_date_used: string;
  date_changed: boolean;
  prorated_rent: number;
  first_month_total: number;
  booking_amount: number;
  amount_collected: number;
  balance_remaining: number;
  payment_id: number | null;
}

export interface CheckinCreate {
  tenancy_id: number;
  actual_checkin_date: string;
  amount_collected: number;
  payment_method: string;
  notes?: string;
}

export function getCheckinPreview(tenancyId: number, actualDate: string): Promise<CheckinPreview> {
  return _get<CheckinPreview>(
    `/api/v2/app/tenants/${tenancyId}/checkin-preview?actual_date=${encodeURIComponent(actualDate)}`
  );
}

export function recordCheckin(body: CheckinCreate): Promise<CheckinResponse> {
  return _post<CheckinResponse>("/api/v2/app/checkin", body);
}
