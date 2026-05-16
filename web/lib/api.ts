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
  method: "UPI" | "CASH";
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
  deposit_eligible?: boolean;   // notices tile only
  upcoming_checkin?: string | null;  // vacant items: earliest future no-show checkin date (ISO)
  is_staff_room?: boolean;  // vacant items: true for staff rooms
  is_overdue?: boolean;   // no_show items: checkin_date has passed
  days_overdue?: number;  // no_show items: days since expected checkin
  // notices tile extras
  expected_checkout_iso?: string | null;
  days_remaining?: number;
  beds_freed?: number;
  sharing_type?: string | null;
  is_full_exit?: boolean;
  room_active_count?: number;
  room_notice_count?: number;
}
export interface KpiDetail { type: string; items: KpiDetailItem[]; }

export function getKpiDetail(type: string, opts?: { includeStaff?: boolean }, token?: string): Promise<KpiDetail> {
  const params = new URLSearchParams({ type });
  if (opts?.includeStaff) params.set("include_staff", "true");
  return _get(`/api/v2/app/reporting/kpi-detail?${params}`, token);
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
  rent_due: number;
  adjustment: number;
  adjustment_note: string | null;
  booking_amount: number;
  dues: number;
  credit: number;
  deposit_due: number;
  deposit_paid: number;
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
  sharing_type: string | null;
}

export function searchTenants(q: string): Promise<TenantSearchResult[]> {
  return _get<TenantSearchResult[]>(`/api/v2/app/tenants/search?q=${encodeURIComponent(q)}`);
}

export function getTenantDues(tenancyId: number): Promise<TenantDues> {
  return _get<TenantDues>(`/api/v2/app/tenants/${tenancyId}/dues`);
}

export interface AdjustmentResult {
  tenancy_id: number;
  period_month: string;
  adjustment: number;
  adjustment_note: string;
  effective_due: number;
}

export function patchAdjustment(tenancyId: number, amount: number, note: string): Promise<AdjustmentResult> {
  return _patch<AdjustmentResult>(`/api/v2/app/tenants/${tenancyId}/adjustment`, { amount, note });
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
  notice_date: string | null;
  has_notice: boolean;
  expected_checkout: string;     // YYYY-MM-DD (last allowed day)
  deposit_eligible: boolean;
  security_deposit: number;
  maintenance_fee: number;
  agreed_rent: number;
  days_remaining: number;        // negative = already past due date
  gender: string | null;         // "male" | "female" | "other" | null
  sharing_type: string | null;   // "single"|"double"|"triple"|"premium"
  beds_freed: number;            // max_occupancy for premium, else 1
  room_max_occupancy: number;
  room_active_count: number;
  room_notice_count: number;
  is_full_exit: boolean;
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
  comments?: string;
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
  method?: "UPI" | "CASH";
  amount?: number;
  notes?: string;
  for_type?: "rent" | "deposit" | "booking" | "maintenance" | "food" | "penalty" | "other";
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
  total: number;               // gross rent inflows (bank + cash)
  security_deposits: number;  // refundable deposits collected this month (deducted below)
  true_revenue: number;        // total − security_deposits
}

export interface FinanceExpenseRow {
  category: string;
  amount: number;
}

export interface FinanceMonthData {
  month: string;
  income: FinanceIncomeBreakdown;
  capital: number;
  expenses: FinanceExpenseRow[];          // opex only (reduces operating profit)
  capex_items: FinanceExpenseRow[];       // one-time CAPEX (shown below op profit)
  excluded_items: FinanceExpenseRow[];    // balance-sheet items (info only, not deducted)
  total_expense: number;                  // opex total only
  total_capex: number;
  operating_profit: number;              // income − opex
  net_profit: number;                    // operating_profit − capex
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

async function _downloadExcel(path: string, filename: string): Promise<void> {
  const headers = await _authHeaders();
  const res = await fetch(`${BASE_URL}${path}`, { headers });
  if (!res.ok) throw new Error(`Download failed: ${res.status}`);
  const blob = await res.blob();
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  URL.revokeObjectURL(a.href);
}

/** Verified canonical P&L — Oct'25–Apr'26, manually verified figures */
export function downloadPnlExcel(): Promise<void> {
  return _downloadExcel(
    "/api/v2/app/finance/pnl/excel",
    `PnL_Verified_${new Date().toISOString().slice(0, 10)}.xlsx`,
  );
}

/** Live P&L recomputed from DB — reflects latest uploads (HULK, new months) */
export function downloadPnlLive(): Promise<void> {
  return _downloadExcel(
    "/api/v2/app/finance/pnl/live",
    `PnL_Live_${new Date().toISOString().slice(0, 10)}.xlsx`,
  );
}

export interface UnitEconomics {
  month: string;
  total_beds: number;
  occupied_beds: number;
  occupancy_pct: number;
  active_tenants: number;
  avg_agreed_rent: number;
  total_billed: number;
  total_collected: number;
  collection_rate: number;
  bank_available: boolean;
  gross_income: number;
  deposits_held: number;
  true_revenue: number;
  total_opex: number;
  ebitda: number;
  revenue_per_bed: number;
  opex_per_bed: number;
  ebitda_per_bed: number;
  ebitda_margin: number;
  // Concept A — Investment Return
  investment_yield_pct: number | null;
  payback_months: number | null;
  breakeven_occupancy_pct: number | null;
  // Concept B — Revenue Quality
  economic_occupancy_pct: number;
  revenue_leakage: number;
}

export async function getUnitEconomics(month?: string): Promise<UnitEconomics> {
  const qs = month ? `?month=${month}` : "";
  return _get(`/api/v2/app/finance/unit-economics${qs}`);
}

// ── Cash position ─────────────────────────────────────────────────────────────

export interface CashExpense {
  id: number
  date: string           // YYYY-MM-DD
  description: string
  amount: number
  paid_by: string
  is_void: boolean
}

export interface CashCountEntry {
  id: number
  date: string           // YYYY-MM-DD
  amount: number
  counted_by: string
  variance: number       // balance − counted (positive = short, negative = over)
}

export interface CashHistoryRow {
  month: string          // YYYY-MM
  collected: number
  expenses: number
  balance: number
}

export interface CashPosition {
  month: string
  collected: number
  expenses_total: number
  balance: number
  last_count: CashCountEntry | null
  expenses: CashExpense[]
  history: CashHistoryRow[]
}

export interface AddExpenseBody {
  date: string
  description: string
  amount: number
  paid_by: "Prabhakaran" | "Lakshmi" | "Other"
}

export interface LogCountBody {
  date: string
  amount: number
  counted_by: "Prabhakaran" | "Lakshmi"
  notes?: string
}

export async function getCashPosition(month: string): Promise<CashPosition> {
  return _get<CashPosition>(`/api/v2/app/finance/cash?month=${encodeURIComponent(month)}`)
}

export async function addCashExpense(body: AddExpenseBody): Promise<CashExpense> {
  return _post<CashExpense>("/api/v2/app/finance/cash/expenses", body)
}

export async function patchCashExpense(id: number, body: Partial<AddExpenseBody>): Promise<CashExpense> {
  const headers = { ...(await _authHeaders()), "Content-Type": "application/json" }
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/cash/expenses/${id}`, {
    method: "PATCH", headers, body: JSON.stringify(body), cache: "no-store",
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail ?? `PATCH failed: ${res.status}`)
  }
  return res.json()
}

export async function voidCashExpense(id: number): Promise<{ ok: boolean; id: number }> {
  const headers = await _authHeaders()
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/cash/expenses/${id}`, {
    method: "DELETE",
    headers,
    cache: "no-store",
  })
  if (!res.ok) throw new Error(`DELETE /finance/cash/expenses/${id} → ${res.status}`)
  return res.json()
}

export async function logCashCount(body: LogCountBody): Promise<{ id: number; date: string; amount: number; counted_by: string; notes: string | null }> {
  return _post("/api/v2/app/finance/cash/counts", body)
}

// ── UPI Reconciliation ────────────────────────────────────────────────────────

export interface UpiMatchedEntry {
  rrn:        string
  amount:     number
  payer:      string
  tenant:     string
  room:       string
  matched_by: string
}

export interface UpiUnmatchedEntry {
  rrn:    string
  amount: number
  payer:  string
  vpa:    string | null
}

export interface UpiReconcileResult {
  account_name:      string
  matched_count:     number
  matched_amount:    number
  unmatched_count:   number
  unmatched_amount:  number
  skipped_duplicate: number
  matched:           UpiMatchedEntry[]
  unmatched:         UpiUnmatchedEntry[]
}

export async function uploadUpiFile(
  file: File,
  accountName: "THOR" | "HULK",
  periodMonth: string,   // YYYY-MM
): Promise<UpiReconcileResult> {
  const headers = await _authHeaders()
  const form = new FormData()
  form.append("files", file)
  form.append("account_name", accountName)
  form.append("period_month", periodMonth)
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/upi-reconcile`, {
    method: "POST", headers, body: form,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail ?? `Upload failed: ${res.status}`)
  }
  return res.json() as Promise<UpiReconcileResult>
}

export async function getUnmatchedUpi(month?: string): Promise<{ unmatched: Array<{ rrn: string; account: string; date: string; amount: number; payer: string; vpa: string | null }> }> {
  const qs = month ? `?month=${month}` : ""
  return _get(`/api/v2/app/finance/upi-reconcile/unmatched${qs}`)
}

export async function assignUpiEntry(rrn: string, tenancyId: number, periodMonth: string): Promise<{ payment_id: number }> {
  const headers = await _authHeaders()
  const form = new FormData()
  form.append("rrn", rrn)
  form.append("tenancy_id", String(tenancyId))
  form.append("period_month", periodMonth)
  const res = await fetch(`${BASE_URL}/api/v2/app/finance/upi-reconcile/assign`, {
    method: "POST", headers, body: form,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail ?? `Assign failed: ${res.status}`)
  }
  return res.json()
}

export interface QuickBookResult {
  token: string;
  session_id: number;
  whatsapp_sent: boolean;
  form_url: string;
}

export async function quickBook(payload: {
  room_number: string;
  tenant_name: string;
  tenant_phone: string;
  checkin_date: string;
  stay_type?: "monthly" | "daily";
  monthly_rent?: number;
  maintenance_fee?: number;
  security_deposit?: number;
  daily_rate?: number;
  checkout_date?: string;
  booking_amount?: number;
}): Promise<QuickBookResult> {
  return _post("/api/v2/app/bookings/quick-book", payload);
}

const ADMIN_PIN = process.env.NEXT_PUBLIC_ONBOARDING_PIN ?? "cozeevo2026"

export async function updateBookingSession(token: string, payload: {
  agreed_rent?: number;
  checkin_date?: string;
  room_number?: string;
  maintenance_fee?: number;
  security_deposit?: number;
  tenant_phone?: string;
  tenant_name?: string;
}): Promise<{ ok: boolean }> {
  const res = await fetch(`${BASE_URL}/api/onboarding/admin/${token}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
    body: JSON.stringify(payload),
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail ?? `Update failed: ${res.status}`)
  }
  return res.json()
}

export async function cancelBookingSession(token: string): Promise<{ status: string }> {
  const res = await fetch(`${BASE_URL}/api/onboarding/admin/${token}/cancel`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Admin-Pin": ADMIN_PIN },
  })
  if (!res.ok) {
    const d = await res.json().catch(() => ({}))
    throw new Error((d as { detail?: string }).detail ?? `Cancel failed: ${res.status}`)
  }
  return res.json()
}

export async function cancelNoShow(tenancyId: number): Promise<{ ok: boolean; name: string }> {
  const headers = await _authHeaders()
  const res = await fetch(`${BASE_URL}/api/v2/app/tenancies/${tenancyId}/cancel-no-show`, {
    method: "POST", headers,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error((detail as { detail?: string }).detail ?? `Cancel failed: ${res.status}`)
  }
  return res.json()
}

// ── Occupancy Analytics ───────────────────────────────────────────────────────

export interface OccupancyMonthData {
  month: string
  label: string
  occ_beds: number
  fill_pct: number
  ci_single: number
  ci_double: number
  ci_triple: number
  ci_premium: number
  ci_daily: number
  checkouts: number | null  // null = no DB data (historical import)
  avg_rent: number
}

export interface OccupancyKpi {
  today_occ_pct: number
  today_occ_beds: number
  total_beds: number
  current_avg_rent: number
  total_checkins: number
  total_checkouts: number
}

export interface OccupancyData {
  kpi: OccupancyKpi
  months: OccupancyMonthData[]
}

export function getOccupancyData(months = 12): Promise<OccupancyData> {
  return _get<OccupancyData>(`/api/v2/app/analytics/occupancy?months=${months}`)
}
