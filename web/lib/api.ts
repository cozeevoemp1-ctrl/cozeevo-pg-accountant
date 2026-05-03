/**
 * Typed API client for /api/v2/app/* (FastAPI backend).
 * Reads the Supabase access token from the current session for JWT auth.
 */
import { supabase } from "./supabase";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "https://api.getkozzy.com";

async function _authHeaders(token?: string): Promise<Record<string, string>> {
  const tok = token ?? (await supabase().auth.getSession()).data.session?.access_token;
  return tok ? { Authorization: `Bearer ${tok}` } : {};
}

async function _get<T>(path: string, token?: string): Promise<T> {
  const headers = await _authHeaders(token);
  const res = await fetch(`${BASE_URL}${path}`, { headers, cache: "no-store" });
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
  expected: number;               // pure_rent_expected + maintenance_expected
  collected: number;              // period-scoped rent + maintenance
  pending: number;
  collection_pct: number;
  pure_rent_expected: number;     // agreed rent total for active tenants (no deposits)
  maintenance_expected: number;
  rent_collected: number;                    // period-scoped
  maintenance_collected: number;
  prior_dues_collected: number;              // cash received this month for prior periods
  cash_received_for_current_period: number;  // cash received this month for this period
  future_advances_collected: number;         // cash received this month for future periods
  deposits_received: number;
  booking_advances: number;
  overdue_count: number;
  method_breakdown: Record<string, number>;
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
  no_show_count: number;
  notices_count: number;
  checkins_today: number;
  checkouts_today: number;
  overdue_tenants: number;
  overdue_amount: number;
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

export interface PaymentIntent {
  intent: string;
  amount: number | null;
  tenant_name: string | null;
  tenant_room: string | null;
  method: string | null;
  for_type: string;
}

// ── API calls ────────────────────────────────────────────────────────────────

export function getCollectionSummary(periodMonth: string, token?: string): Promise<CollectionSummary> {
  return _get(`/api/v2/app/reporting/collection?period_month=${encodeURIComponent(periodMonth)}`, token);
}

export function getDepositsHeld(token?: string): Promise<{ held: number; maintenance: number; refundable: number }> {
  return _get("/api/v2/app/reporting/deposits-held", token);
}

export function getKpi(token?: string): Promise<KpiResponse> {
  return _get("/api/v2/app/reporting/kpi", token);
}

export function getRecentActivity(limit = 20, token?: string): Promise<ActivityResponse> {
  return _get(`/api/v2/app/activity/recent?limit=${limit}`, token);
}

export interface KpiDetailItem {
  tenancy_id?: number;
  name: string;
  room: string;
  detail: string;
  rent?: number;       // occupied items only
  free_beds?: number;  // vacant items only
  gender?: string;     // vacant items: "male" | "female" | "mixed" | "empty" | "unknown"
  stay_type?: string;  // checkins/checkouts: "monthly" | "daily"
  is_checked_out?: boolean;  // checkouts_today: true if already exited
  dues?: number;       // dues items only
  building?: string;   // dues items: "THOR" | "HULK"
  deposit_eligible?: boolean;  // notices tile only
  upcoming_checkin?: string | null;  // vacant items: earliest future no-show checkin date (ISO)
}
export interface KpiDetail { type: string; items: KpiDetailItem[]; }

export function getKpiDetail(type: string, token?: string): Promise<KpiDetail> {
  return _get(`/api/v2/app/reporting/kpi-detail?type=${type}`, token);
}

export function createPayment(body: PaymentCreate): Promise<PaymentResponse> {
  return _post("/api/v2/app/payments", body);
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
  email: string;
  room_number: string;
  building_code: string;
  rent: number;
  dues: number;
  checkin_date: string | null;
  security_deposit: number;
  maintenance_fee: number;
  lock_in_months: number;
  notes: string;
  last_payment_date: string | null;
  last_payment_amount: number | null;
  period_month: string;
  notice_date: string | null;
  expected_checkout: string | null;
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
  stay_type: "monthly" | "daily";
  tenancy_status: string;
  already_checked_in: boolean;
  // monthly
  agreed_rent: number;
  security_deposit: number;
  booking_amount: number;
  prorated_rent: number;
  first_month_total: number;  // for daily: total stay cost
  balance_due: number;
  overpayment: number;
  date_changed: boolean;
  // daily-specific (null for monthly)
  daily_rate: number | null;
  num_days: number | null;
  checkout_date: string | null;
  total_stay_amount: number | null;
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
  actual_checkin_time?: string;  // HH:MM — day-wise stays only
  prorate?: boolean;
}

export function getCheckinPreview(tenancyId: number, actualDate: string, prorate = true): Promise<CheckinPreview> {
  return _get<CheckinPreview>(
    `/api/v2/app/tenants/${tenancyId}/checkin-preview?actual_date=${encodeURIComponent(actualDate)}&prorate=${prorate}`
  );
}

export function recordCheckin(body: CheckinCreate): Promise<CheckinResponse> {
  return _post<CheckinResponse>("/api/v2/app/checkin", body);
}

// ── Tenant list + patch ──────────────────────────────────────────────────────

export interface TenantListItem {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room_number: string;
  building_code: string;
  rent: number;
  dues: number;
  status: string;
}

export interface PatchTenantBody {
  name?: string;
  phone?: string;
  email?: string;
  tenant_notes?: string;
  agreed_rent?: number;
  security_deposit?: number;
  maintenance_fee?: number;
  lock_in_months?: number;
  expected_checkout?: string | null;
  tenancy_notes?: string;
  rent_change_reason?: string;
  notice_date?: string | null;
  room_number?: string;
  prorate_this_month?: boolean;
  checkin_date?: string | null;
}

export interface PatchTenantResponse {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  email: string | null;
  agreed_rent: number;
  security_deposit: number;
  expected_checkout: string | null;
  notes: string | null;
}

async function _patch<T>(path: string, body: unknown): Promise<T> {
  const headers = { ...(await _authHeaders()), "Content-Type": "application/json" };
  const res = await fetch(`${BASE_URL}${path}`, {
    method: "PATCH",
    headers,
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `PATCH ${path} → ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function getTenantsList(): Promise<TenantListItem[]> {
  return _get<TenantListItem[]>("/api/v2/app/tenants/list");
}

export function patchTenant(tenancyId: number, body: PatchTenantBody): Promise<PatchTenantResponse> {
  return _patch<PatchTenantResponse>(`/api/v2/app/tenants/${tenancyId}`, body);
}

export async function deleteTenant(tenancyId: number, reason: string, force = false): Promise<void> {
  const headers = await _authHeaders();
  const url = `${BASE_URL}/api/v2/app/tenants/${tenancyId}?reason=${encodeURIComponent(reason)}${force ? "&force=true" : ""}`;
  const res = await fetch(url, { method: "DELETE", headers });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `DELETE failed: ${res.status}`);
  }
}

// ── Room Transfer ─────────────────────────────────────────────────────────────

export interface RoomCheckResult {
  room_number: string
  max_occupancy: number
  free_beds: number
  is_available: boolean
  occupants: { name: string; tenancy_id: number }[]
}

export interface TransferRoomBody {
  to_room_number: string
  new_rent: number | null
  extra_deposit: number
}

export interface TransferRoomResult {
  success: boolean
  message: string
  from_room?: string
  to_room?: string
  new_rent?: number
  extra_deposit?: number
}

export function checkRoom(roomNumber: string): Promise<RoomCheckResult> {
  return _get<RoomCheckResult>(`/api/v2/app/rooms/check?room=${encodeURIComponent(roomNumber)}`)
}

export function transferRoom(tenancyId: number, body: TransferRoomBody): Promise<TransferRoomResult> {
  return _post<TransferRoomResult>(`/api/v2/app/tenants/${tenancyId}/transfer-room`, body)
}

// ── Checkouts ────────────────────────────────────────────────────────────────

export interface CheckoutListItem {
  tenancy_id: number;
  name: string;
  phone: string;
  room_number: string;
  checkout_date: string;
  stay_type: "monthly" | "daily";
  security_deposit: number;
  refund_amount: number;
  agreed_rent: number;
}

export function getCheckouts(month?: string): Promise<CheckoutListItem[]> {
  const q = month ? `?month=${month}` : "";
  return _get<CheckoutListItem[]>(`/api/v2/app/checkouts${q}`);
}

// ── Reminders ────────────────────────────────────────────────────────────────

export interface OverdueTenant {
  tenancy_id: number;
  tenant_id: number;
  name: string;
  phone: string;
  room: string;
  dues: number;
  reminder_count: number;
  last_reminded_at: string | null;
}

export function getOverdueTenants(): Promise<OverdueTenant[]> {
  return _get<OverdueTenant[]>("/api/v2/app/reminders/overdue");
}

export function sendReminder(body: { tenancy_id?: number; send_all?: boolean }): Promise<{ sent: number[]; failed: number[] }> {
  return _post<{ sent: number[]; failed: number[] }>("/api/v2/app/reminders/send", body);
}

// ── Notices ──────────────────────────────────────────────────────────────────

export interface NoticeItem {
  tenancy_id: number;
  tenant_name: string;
  phone: string;
  room_number: string;
  notice_date: string | null;    // YYYY-MM-DD; null if no formal notice
  has_notice: boolean;
  expected_checkout: string;     // YYYY-MM-DD (last allowed day)
  deposit_eligible: boolean;     // notice on/before 5th
  security_deposit: number;
  maintenance_fee: number;
  agreed_rent: number;
  days_remaining: number;        // negative = already past due date
}

export function getActiveNotices(): Promise<NoticeItem[]> {
  return _get<NoticeItem[]>("/api/v2/app/notices/active");
}

// ── Checkout ─────────────────────────────────────────────────────────────────

export interface CheckoutPrefetch {
  tenancy_id: number;
  tenant_name: string;
  phone: string;
  room_number: string;
  security_deposit: number;
  maintenance_fee: number;
  pending_dues: number;   // outstanding rent only; maintenance_fee deducted separately
  notice_date: string | null;
  expected_checkout: string | null;
  // day-wise fields
  stay_type: string;
  daily_rate: number | null;
  booked_checkout_date: string | null;
  checkin_time: string | null;    // HH:MM recorded at physical check-in
}

export interface CheckoutCreateBody {
  tenancy_id: number;
  checkout_date: string;
  room_key_returned: boolean;
  wardrobe_key_returned: boolean;
  biometric_removed: boolean;
  room_condition_ok: boolean;
  damage_notes?: string;
  security_deposit: number;
  pending_dues: number;
  deductions: number;
  deduction_reason?: string;
  refund_amount: number;
  refund_mode: string;
  checkout_time?: string;  // HH:MM — day-wise stays only
}

export interface CheckoutCreateResponse {
  status: string;
  token: string;
  confirm_link: string;
  expires_at: string;
}

export interface CheckoutStatusResponse {
  token: string;
  status: "pending" | "confirmed" | "rejected" | "cancelled" | "expired";
  confirmed_at: string | null;
  rejection_reason: string | null;
  expires_at: string;
}

export function getCheckoutPrefetch(tenancyId: number): Promise<CheckoutPrefetch> {
  return _get<CheckoutPrefetch>(`/api/v2/app/checkout/tenant/${tenancyId}`);
}

export function createCheckout(body: CheckoutCreateBody): Promise<CheckoutCreateResponse> {
  return _post<CheckoutCreateResponse>("/api/v2/app/checkout/create", body);
}

export function getCheckoutStatus(token: string): Promise<CheckoutStatusResponse> {
  return _get<CheckoutStatusResponse>(`/api/v2/app/checkout/status/${token}`);
}

export async function uploadReceipt(paymentId: number, file: File): Promise<{ payment_id: number; receipt_url: string; transaction_id: string | null }> {
  const headers = await _authHeaders();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/api/v2/app/payments/${paymentId}/receipt`, {
    method: "POST",
    headers,  // no Content-Type — browser sets multipart boundary automatically
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `Upload failed ${res.status}`);
  }
  return res.json();
}

// ── Payment history + edit ───────────────────────────────────────────────────

export interface PaymentListItem {
  payment_id: number;
  amount: number;
  method: string;
  for_type: string;
  period_month: string | null;
  payment_date: string;
  notes: string | null;
  is_void: boolean;
  receipt_url: string | null;
  upi_reference: string | null;
  tenant_name: string | null;
  room_number: string | null;
}

export interface PaymentEditBody {
  method?: "UPI" | "CASH" | "BANK" | "CARD" | "OTHER";
  amount?: number;
  notes?: string;
}

export interface OcrResult {
  amount: number | null;
  transaction_id: string | null;
  method: "UPI" | "CASH" | "BANK" | null;
}

export async function ocrReceiptPreview(file: File): Promise<OcrResult> {
  const headers = await _authHeaders();
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${BASE_URL}/api/v2/app/payments/ocr`, {
    method: "POST",
    headers,
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `OCR failed ${res.status}`);
  }
  return res.json();
}

export function getPaymentHistory(tenancyId?: number, limit = 30): Promise<PaymentListItem[]> {
  const q = tenancyId ? `tenancy_id=${tenancyId}&limit=${limit}` : `limit=${limit}`;
  return _get<PaymentListItem[]>(`/api/v2/app/payments?${q}`);
}

export function editPayment(paymentId: number, body: PaymentEditBody): Promise<PaymentListItem> {
  return _patch<PaymentListItem>(`/api/v2/app/payments/${paymentId}`, body);
}

// ── Recent check-ins ─────────────────────────────────────────────────────────

export interface RecentCheckinItem {
  tenancy_id: number;
  name: string;
  room: string;
  checkin_date: string;
  agreed_rent: number;
  security_deposit: number;
  first_month_due: number;
  first_month_paid: number;
  balance: number;
  stay_type: "monthly" | "daily";
}

export function getRecentCheckins(limit = 10, token?: string): Promise<{ items: RecentCheckinItem[] }> {
  return _get(`/api/v2/app/activity/recent-checkins?limit=${limit}`, token);
}

// ── Finance ──────────────────────────────────────────────────────────────────

export interface FinanceIncomeBreakdown {
  upi_batch: number;
  direct_neft: number;
  cash_db: number;
  total: number;
}

export interface FinanceExpenseRow {
  category: string;
  amount: number;
}

export interface FinanceMonthData {
  month: string;
  income: FinanceIncomeBreakdown;
  capital: number;
  expenses: FinanceExpenseRow[];
  total_expense: number;
  operating_profit: number;
  margin_pct: number;
}

export interface FinancePnlResponse {
  months: string[];
  data: Record<string, FinanceMonthData>;
}

export interface FinanceUploadResult {
  months_affected: string[];
  new_count: number;
  duplicate_count: number;
}

export async function uploadBankCsv(
  files: File[],
  accountName: "THOR" | "HULK",
): Promise<FinanceUploadResult> {
  const headers = await _authHeaders();
  const form = new FormData();
  files.forEach((f) => form.append("files", f));
  form.append("account_name", accountName);
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/upload`, {
    method: "POST",
    headers,  // no Content-Type — browser sets multipart boundary automatically
    body: form,
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string }).detail ?? `Upload failed: ${res.status}`);
  }
  return res.json() as Promise<FinanceUploadResult>;
}

export async function getFinancePnl(month?: string): Promise<FinancePnlResponse> {
  const qs = month ? `?month=${month}` : "";
  return _get<FinancePnlResponse>(`/api/v2/app/finance/pnl${qs}`);
}

export interface DepositReconcileRow {
  txn_id: number;
  txn_date: string;
  amount: number;
  status: "matched" | "unmatched";
  tenant: string | null;
  checkout_id: number | null;
}

export async function getDepositReconciliation(month?: string): Promise<{ rows: DepositReconcileRow[] }> {
  const qs = month ? `?month=${month}` : "";
  return _get(`/api/v2/app/finance/reconcile${qs}`);
}

export async function downloadPnlExcel(fromMonth?: string, toMonth?: string): Promise<void> {
  const headers = await _authHeaders();
  const params = new URLSearchParams();
  if (fromMonth) params.set("from", fromMonth);
  if (toMonth) params.set("to", toMonth);
  const qs = params.size ? "?" + params.toString() : "";
  const url = `${BASE_URL}/api/v2/app/finance/pnl/excel${qs}`;
  const res = await fetch(url, { headers });
  if (!res.ok) throw new Error(`Excel download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `PnL_${new Date().toISOString().slice(0, 10)}.xlsx`;
  a.click();
  URL.revokeObjectURL(a.href);
}
