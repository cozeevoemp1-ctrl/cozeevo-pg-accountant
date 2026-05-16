/**
 * Cozeevo Executive Dashboard — Google Apps Script Web App
 * =========================================================
 *
 * SETUP:
 *   1. Open your Google Sheet → Extensions → Apps Script
 *   2. Create TWO files:
 *      - Code.gs  → paste this entire file
 *      - Index.html → paste the contents of gsheet_dashboard_index.html
 *   3. Deploy → New deployment → Web app
 *      - Execute as: Me
 *      - Who has access: Anyone with the link (or Anyone in your org)
 *   4. Copy the deployment URL — that's your dashboard link
 *
 * DATA SOURCE: Reads directly from monthly tabs (MARCH 2026, etc.)
 *              and TENANTS tab. No hardcoded cell positions.
 */

const TOTAL_BEDS = 295; // updated 2026-05-16; 107+114+618 revenue (not staff)
const MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
  "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
const MONTH_TAB_RE = /^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}$/i;

// ── Web App Entry Point ─────────────────────────────────────────────────────

function doGet() {
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Cozeevo Dashboard')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

// ── Data API (called from frontend via google.script.run) ───────────────────

function getDashboardData(monthTab) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const tabs = getMonthTabs_(ss);

  if (tabs.length === 0) return { error: "No monthly tabs found" };

  // Find requested month or use latest
  let tab;
  if (monthTab) {
    tab = tabs.find(t => t.name.toUpperCase() === monthTab.toUpperCase());
  }
  if (!tab) tab = tabs[tabs.length - 1];

  const d = readMonthData_(tab.sheet);
  const collected = d.cash + d.upi;
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = TOTAL_BEDS > 0 ? Math.round(d.beds / TOTAL_BEDS * 100) : 0;
  const collPct = d.rentExpected > 0 ? Math.round(collected / d.rentExpected * 100) : 0;
  const deposit = getTotalDeposit_(ss);

  // Month-on-month data
  const trend = tabs.map(t => {
    try {
      const md = readMonthData_(t.sheet);
      const mc = md.cash + md.upi;
      return {
        name: t.name,
        beds: md.beds,
        collected: mc,
        dues: md.balance,
        rentExpected: md.rentExpected,
        paidPct: md.rentExpected > 0 ? Math.round(mc / md.rentExpected * 100) : 0,
        isCurrent: t.name === tab.name
      };
    } catch(e) {
      return { name: t.name, beds: 0, collected: 0, dues: 0, rentExpected: 0, paidPct: 0, error: true };
    }
  });

  // Top unpaid tenants
  const unpaidList = getUnpaidTenants_(tab.sheet);

  return {
    selectedMonth: tab.name,
    availableMonths: tabs.map(t => t.name),

    occupancy: {
      beds: d.beds,
      total: TOTAL_BEDS,
      vacant: vacant,
      pct: occPct,
      regular: d.regular,
      premium: d.premium,
      noshow: d.noshow
    },

    collection: {
      cash: d.cash,
      upi: d.upi,
      total: collected,
      outstanding: d.balance,
      rentExpected: d.rentExpected,
      pct: collPct
    },

    status: {
      paid: d.paid,
      partial: d.partial,
      unpaid: d.unpaid,
      exits: d.exits,
      newCheckins: d.newCheckins
    },

    properties: {
      thor: {
        beds: d.thorBeds,
        tenants: d.thorTenants,
        collected: d.thorCash + d.thorUpi,
        rent: d.thorRent
      },
      hulk: {
        beds: d.hulkBeds,
        tenants: d.hulkTenants,
        collected: d.hulkCash + d.hulkUpi,
        rent: d.hulkRent
      }
    },

    deposit: deposit,
    trend: trend,
    unpaidList: unpaidList,
    timestamp: new Date().toLocaleString('en-IN', { timeZone: 'Asia/Kolkata' })
  };
}

// ── Read Monthly Tab ────────────────────────────────────────────────────────

function readMonthData_(sheet) {
  const data = sheet.getDataRange().getValues();
  const r = {
    tenants: 0, beds: 0, regular: 0, premium: 0, noshow: 0,
    cash: 0, upi: 0, balance: 0, rentExpected: 0,
    paid: 0, partial: 0, unpaid: 0,
    newCheckins: 0, exits: 0,
    thorBeds: 0, hulkBeds: 0, thorTenants: 0, hulkTenants: 0,
    thorRent: 0, hulkRent: 0,
    thorCash: 0, hulkCash: 0, thorUpi: 0, hulkUpi: 0,
  };
  if (data.length < 5) return r;

  const headers = data.length > 3 ? data[3] : [];
  const isNew = String(headers[2] || "").toUpperCase().includes("PHONE");
  const C = isNew
    ? { building: 3, sharing: 4, rent: 5, cash: 6, upi: 7, bal: 9, status: 10, event: 13 }
    : { building: 2, sharing: 3, rent: 4, cash: 5, upi: 6, bal: 8, status: 9, event: 11 };

  for (let i = 4; i < data.length; i++) {
    const row = data[i];
    if (!row[0] || !row[1]) continue;

    const building = String(row[C.building]).toUpperCase().trim();
    const sharing = String(row[C.sharing]).toLowerCase().trim();
    const rentDue = pn_(row[C.rent]);
    const cash = pn_(row[C.cash]);
    const upi = pn_(row[C.upi]);
    const bal = pn_(row[C.bal]);
    const status = String(row[C.status]).toUpperCase().trim();
    const event = String(row[C.event]).toUpperCase().trim();

    r.tenants++;
    r.cash += cash;
    r.upi += upi;
    r.balance += bal;
    r.rentExpected += rentDue;

    if (building === "THOR") { r.thorRent += rentDue; r.thorCash += cash; r.thorUpi += upi; }
    else { r.hulkRent += rentDue; r.hulkCash += cash; r.hulkUpi += upi; }

    if (status === "PAID") r.paid++;
    else if (status === "PARTIAL") r.partial++;
    else if (status === "UNPAID") r.unpaid++;

    if (event.includes("NEW CHECK-IN")) r.newCheckins++;
    if (event.includes("EXITED") || status === "EXIT") r.exits++;

    if (status === "EXIT") continue;
    if (event === "NO-SHOW" || status === "NO SHOW") { r.noshow++; continue; }

    const bedCount = (sharing === "premium") ? 2 : 1;
    r.beds += bedCount;
    if (sharing === "premium") r.premium++;
    else r.regular++;

    if (building === "THOR") { r.thorBeds += bedCount; r.thorTenants++; }
    else { r.hulkBeds += bedCount; r.hulkTenants++; }
  }
  return r;
}

// ── Unpaid Tenants List ─────────────────────────────────────────────────────

function getUnpaidTenants_(sheet) {
  const data = sheet.getDataRange().getValues();
  if (data.length < 5) return [];

  const headers = data.length > 3 ? data[3] : [];
  const isNew = String(headers[2] || "").toUpperCase().includes("PHONE");
  const C = isNew
    ? { room: 0, name: 1, building: 3, rent: 5, bal: 9, status: 10 }
    : { room: 0, name: 1, building: 2, rent: 4, bal: 8, status: 9 };

  const list = [];
  for (let i = 4; i < data.length; i++) {
    const row = data[i];
    if (!row[0] || !row[1]) continue;
    const status = String(row[C.status]).toUpperCase().trim();
    if (status !== "UNPAID" && status !== "PARTIAL") continue;

    const bal = pn_(row[C.bal]);
    if (bal <= 0) continue;

    list.push({
      room: String(row[C.room]).trim(),
      name: String(row[C.name]).trim(),
      building: String(row[C.building]).toUpperCase().trim(),
      rent: pn_(row[C.rent]),
      balance: bal,
      status: status
    });
  }

  list.sort((a, b) => b.balance - a.balance);
  return list;
}

// ── Helpers ─────────────────────────────────────────────────────────────────

function pn_(val) {
  if (!val) return 0;
  const n = parseFloat(String(val).replace(/,/g, "").trim());
  return isNaN(n) ? 0 : n;
}

function getMonthTabs_(ss) {
  const tabs = [];
  ss.getSheets().forEach(s => {
    if (MONTH_TAB_RE.test(s.getName())) {
      const p = s.getName().split(" ");
      const monthUpper = p[0].toUpperCase();
      tabs.push({ name: s.getName(), sheet: s, sort: parseInt(p[1]) * 100 + MONTH_NAMES.indexOf(monthUpper) });
    }
  });
  tabs.sort((a, b) => a.sort - b.sort);
  return tabs;
}

function getTotalDeposit_(ss) {
  const tenants = ss.getSheetByName("TENANTS");
  if (!tenants) return 0;
  const data = tenants.getDataRange().getValues();
  let total = 0;
  for (let i = 1; i < data.length; i++) {
    if (String(data[i][8]).trim() === "Active") {
      total += pn_(data[i][11]);
    }
  }
  return total;
}
