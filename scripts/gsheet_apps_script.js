/**
 * Cozeevo Operations — Google Apps Script v5 (header-driven)
 * ===========================================================
 * Paste into: Extensions > Apps Script
 * Run setupTriggers() once.
 *
 * v5 changes (2026-04-19):
 *   - All sheet reads/writes use header-name lookup, never positional.
 *   - Supports both legacy (4-row header) and new sync_sheet_from_db.py
 *     layout (7-row header + Rent + Deposit columns) on the same script.
 *   - Header row is detected by scanning column A for "Room".
 *
 * FEATURES:
 *   - Month dropdown on dashboard — switch between any month
 *   - Auto-refresh on edit (any monthly tab or TENANTS)
 *   - Deposit total from TENANTS tab (Active tenants only)
 *   - THOR vs HULK comparison per selected month
 *   - Month-on-month trend table
 *
 * Canonical monthly-tab columns are defined by Python's MONTHLY_HEADERS
 * (src/integrations/gsheets.py). This script READS those headers and
 * looks up data by name — never by position.
 */

const TOTAL_BEDS = 297; // updated 2026-05-09; +1 G20 (non-staff May 2026) +2 room 107 (non-staff May 2026)
const MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
const MONTH_TAB_RE = /^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}$/i;
const DROPDOWN_CELL = "E1";  // Where the month picker lives on DASHBOARD

// ── Header-detection helpers (used everywhere — DRY single source) ──────────

/**
 * Scan column A of a 2D array (data) for a row whose A-cell equals expected
 * (case-insensitive, trimmed). Returns 0-indexed row index, or -1 if not found.
 * Use to locate header rows without assuming a fixed position.
 */
function _findRow_(data, expectedColA, maxScan) {
  const limit = Math.min(maxScan || 12, data.length);
  const want = String(expectedColA).trim().toLowerCase();
  for (let i = 0; i < limit; i++) {
    const cell = data[i] && data[i][0];
    if (String(cell || "").trim().toLowerCase() === want) return i;
  }
  return -1;
}

/**
 * Build a {lowercase_header_name: 0-indexed-col} map from a header row array.
 * Used for column lookup by name — never by position.
 */
function _colMap_(headerRow) {
  const map = {};
  (headerRow || []).forEach((h, i) => {
    const key = String(h || "").trim().toLowerCase();
    if (key) map[key] = i;
  });
  return map;
}

/** Get column 0-indexed by name from a colMap. -1 if missing. */
function _col_(colMap, name) {
  const v = colMap[String(name).trim().toLowerCase()];
  return (v === undefined) ? -1 : v;
}

// ── TRIGGERS & MENU ─────────────────────────────────────────────────────────

function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));
  ScriptApp.newTrigger("onSheetEdit").forSpreadsheet(SpreadsheetApp.getActive()).onEdit().create();
  ScriptApp.newTrigger("createNewMonthIfNeeded").timeBased().everyDays(1).atHour(0).create();
  SpreadsheetApp.getActive().toast("Triggers set! Dashboard auto-updates on edit.", "Done", 5);
}

function onOpen() {
  SpreadsheetApp.getUi().createMenu("Cozeevo")
    .addItem("Refresh Dashboard", "refreshDashboard")
    .addItem("Create Next Month Tab", "createNextMonth")
    .addItem("Validate Totals", "validateTotals")
    .addSeparator()
    .addItem("Setup Triggers (first time)", "setupTriggers")
    .addItem("Lock All Sheets (read-only)", "lockAllSheets")
    .addToUi();

  // Auto-jump to the most recent monthly tab on every open. Tabs are named
  // "<MONTH> <YYYY>" (e.g. "APRIL 2026"). Picks the chronologically latest
  // and selects it; falls back to no-op if none match.
  jumpToLatestMonth();
}

function jumpToLatestMonth() {
  var ss = SpreadsheetApp.getActive();
  var monthMap = {
    JANUARY: 1, FEBRUARY: 2, MARCH: 3, APRIL: 4, MAY: 5, JUNE: 6,
    JULY: 7, AUGUST: 8, SEPTEMBER: 9, OCTOBER: 10, NOVEMBER: 11, DECEMBER: 12,
  };
  var best = null;
  ss.getSheets().forEach(function(sh) {
    var nm = sh.getName().toUpperCase();
    var parts = nm.split(/\s+/);
    if (parts.length !== 2) return;
    var m = monthMap[parts[0]];
    var y = parseInt(parts[1], 10);
    if (!m || isNaN(y)) return;
    var ord = y * 12 + m;
    if (!best || ord > best.ord) best = { sheet: sh, ord: ord };
  });
  if (best) ss.setActiveSheet(best.sheet);
}

/**
 * Lock all sheets so only the bot service account can edit.
 * Everyone else can view and use filters but cannot change data.
 * Run once from Cozeevo menu > Lock All Sheets.
 */
function lockAllSheets() {
  var ss = SpreadsheetApp.getActive();
  // Bot service account — the only editor allowed
  var botEmail = "cozeevo-sheets-bot@cozeevo-bot-491219.iam.gserviceaccount.com";
  var sheets = ss.getSheets();
  var count = 0;

  sheets.forEach(function(sheet) {
    var name = sheet.getName();

    // Remove existing protections on this sheet
    sheet.getProtections(SpreadsheetApp.ProtectionType.SHEET).forEach(function(p) {
      p.remove();
    });

    var protection = sheet.protect().setDescription("Read-only: " + name);
    // Only bot + owner can edit. Owner access is required for Apps Script triggers.
    // All other users (partner, staff, viewers) are fully locked out.
    // Owner: DO NOT manually edit — all changes must go through the WhatsApp bot.
    protection.removeEditors(protection.getEditors());
    protection.addEditor(botEmail);
    protection.addEditor(ss.getOwner().getEmail());

    if (protection.canDomainEdit()) {
      protection.setDomainEdit(false);
    }
    count++;
  });

  SpreadsheetApp.getActive().toast(
    count + " sheets locked. Only bot service account can edit. Everyone else: view + filter only.",
    "Sheets Locked", 10
  );
}

function _isClosedMonth_(tabName) {
  // Returns true if tabName refers to a month BEFORE the current calendar month.
  const match = tabName.trim().toUpperCase().match(/^([A-Z]+)\s+(\d{4})$/);
  if (!match) return false;
  const monthIdx = MONTH_NAMES.indexOf(match[1]);
  if (monthIdx === -1) return false;
  const tabYear = parseInt(match[2], 10);
  const now = new Date();
  const curYear = now.getFullYear();
  const curMonth = now.getMonth(); // 0-indexed
  if (tabYear < curYear) return true;
  if (tabYear === curYear && monthIdx < curMonth) return true;
  return false;
}

function onSheetEdit(e) {
  try {
    const sheet = e.source.getActiveSheet();
    const name = sheet.getName();
    if (name === "DASHBOARD") {
      // Dropdown changed — redraw dashboard content (not the dropdown itself)
      const cell = sheet.getActiveCell();
      if (cell.getA1Notation() === DROPDOWN_CELL) {
        refreshDashboardContent_();
      }
    } else if (MONTH_TAB_RE.test(name.toUpperCase())) {
      // Freeze guard: past months are read-only mirrors of DB — warn on edit.
      if (_isClosedMonth_(name)) {
        SpreadsheetApp.getUi().alert(
          "Closed Period",
          name + " is a closed period. Past month data is a read-only mirror of the database.\n\n" +
          "To correct a discrepancy, use the Adjustment line on the current month row in the app or bot.",
          SpreadsheetApp.getUi().ButtonSet.OK
        );
        return;
      }
      // New layout (sync_sheet_from_db.py) puts header at row 7, with 5
      // summary cards at rows 2-6. The legacy updateMonthSummary writes to
      // rows 2-3 — skip it on the new layout to avoid corrupting cards.
      if (!isLegacyLayout_(sheet)) return;
      updateMonthSummary(sheet);
      refreshDashboardContent_();
    } else if (name === "TENANTS") {
      refreshDashboard();
    }
  } catch (err) { }
}

// Returns true only if the tab uses the OLD 4-row-header layout. The new
// sync_sheet_from_db.py layout has "Room" header at row 7, not row 4.
function isLegacyLayout_(sheet) {
  try {
    const r4a = String(sheet.getRange("A4").getValue() || "").trim().toLowerCase();
    return r4a === "room";
  } catch (err) {
    return false;
  }
}

// ── HELPERS ─────────────────────────────────────────────────────────────────

function pn(val) {
  if (!val) return 0;
  const n = parseFloat(String(val).replace(/,/g, "").trim());
  return isNaN(n) ? 0 : n;
}

function getMonthTabs_() {
  const ss = SpreadsheetApp.getActive();
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

function getTotalDeposit_() {
  const ss = SpreadsheetApp.getActive();
  const tenants = ss.getSheetByName("TENANTS");
  if (!tenants) return 0;
  const data = tenants.getDataRange().getValues();
  if (data.length < 2) return 0;
  // Header-driven — TENANTS tab row 1 is the header. Look up by name.
  const cm = _colMap_(data[0]);
  const cStatus = _col_(cm, "Status");
  const cDeposit = _col_(cm, "Deposit");
  if (cStatus < 0 || cDeposit < 0) return 0;
  let total = 0;
  for (let i = 1; i < data.length; i++) {
    const status = String(data[i][cStatus] || "").trim().toLowerCase();
    if (status === "active") {
      total += pn(data[i][cDeposit]);
    }
  }
  return total;
}

// ── READ MONTHLY TAB ────────────────────────────────────────────────────────

function readMonthData(sheet) {
  const data = sheet.getDataRange().getValues();
  const r = {
    tenants: 0, beds: 0, regular: 0, premium: 0, noshow: 0,
    daywise: 0,  // day-stay guests currently checked in (from DAY WISE tab)
    cash: 0, upi: 0, balance: 0, rentExpected: 0,
    paid: 0, partial: 0, unpaid: 0,
    newCheckins: 0, exits: 0,
    thorBeds: 0, hulkBeds: 0, thorTenants: 0, hulkTenants: 0,
    thorRent: 0, hulkRent: 0,
    thorCash: 0, hulkCash: 0, thorUpi: 0, hulkUpi: 0,
  };

  // Count active day-stays so DASHBOARD vacant count matches the bot +
  // monthly tab summary. A room with only day-stay guests is NOT vacant.
  try {
    const dw = SpreadsheetApp.getActive().getSheetByName("DAY WISE");
    if (dw) {
      const dwData = dw.getDataRange().getValues();
      const dwHdr = _findRow_(dwData, "Room", 5);
      if (dwHdr >= 0) {
        const dwCm = _colMap_(dwData[dwHdr]);
        const cChk = _col_(dwCm, "Check-in");
        const cOut = _col_(dwCm, "Check-out");
        const cStat = _col_(dwCm, "Status");
        const today = new Date(); today.setHours(0, 0, 0, 0);
        for (let i = dwHdr + 1; i < dwData.length; i++) {
          const row = dwData[i];
          const chk = row[cChk] ? new Date(row[cChk]) : null;
          const out = row[cOut] ? new Date(row[cOut]) : null;
          const stat = String(row[cStat] || "").toUpperCase();
          if (!chk) continue;
          if (stat === "EXIT" || stat === "CANCELLED") continue;
          if (chk <= today && (!out || out > today)) r.daywise++;
        }
      }
    }
  } catch (e) { /* DAY WISE missing or read error — leave 0 */ }
  // Header-driven — locate "Room" header row (row 4 in legacy, row 7 in new
  // sync_sheet_from_db.py layout). Column lookup by name, not position.
  const headerIdx = _findRow_(data, "Room", 12);
  if (headerIdx < 0) return r;
  const cm = _colMap_(data[headerIdx]);
  const dataStart = headerIdx + 1;

  const cBuilding = _col_(cm, "Building");
  const cSharing = _col_(cm, "Sharing");
  const cRent = _col_(cm, "Rent Due");  // billed amount (incl. first-month deposit)
  const cCash = _col_(cm, "Cash");
  const cUpi = _col_(cm, "UPI");
  const cBal = _col_(cm, "Balance");
  const cStatus = _col_(cm, "Status");
  const cEvent = _col_(cm, "Event");

  for (let i = dataStart; i < data.length; i++) {
    const row = data[i];
    if (!row[0] || !row[1]) continue;

    const building = String(row[cBuilding] || "").toUpperCase().trim();
    const sharing = String(row[cSharing] || "").toLowerCase().trim();
    const rentDue = pn(row[cRent]);
    const cash = pn(row[cCash]);
    const upi = pn(row[cUpi]);
    const bal = pn(row[cBal]);
    const status = String(row[cStatus] || "").toUpperCase().trim();
    const event = String(row[cEvent] || "").toUpperCase().trim();

    r.tenants++;
    r.cash += cash;
    r.upi += upi;
    r.balance += bal;
    r.rentExpected += rentDue;

    // Building cell may be "THOR" or "Cozeevo THOR" — substring match
    if (building.indexOf("THOR") >= 0) { r.thorRent += rentDue; r.thorCash += cash; r.thorUpi += upi; }
    else if (building.indexOf("HULK") >= 0) { r.hulkRent += rentDue; r.hulkCash += cash; r.hulkUpi += upi; }

    if (status === "PAID") r.paid++;
    else if (status === "PARTIAL") r.partial++;
    else if (status === "UNPAID") r.unpaid++;

    if (event.indexOf("NEW CHECK-IN") >= 0 || event === "CHECKIN") r.newCheckins++;
    if (event.indexOf("EXIT") >= 0 || status === "EXIT") r.exits++;

    if (status === "EXIT" || event.indexOf("EXIT") >= 0) continue;
    // Event values: "NO SHOW" (space, new) or "NO-SHOW" (dash, legacy)
    if (event.indexOf("NO SHOW") >= 0 || event.indexOf("NO-SHOW") >= 0 ||
        status.indexOf("NO SHOW") >= 0 || status.indexOf("NO-SHOW") >= 0) {
      r.noshow++; continue;
    }

    const bedCount = (sharing === "premium") ? 2 : 1;
    r.beds += bedCount;
    if (sharing === "premium") r.premium++;
    else r.regular++;

    if (building.indexOf("THOR") >= 0) { r.thorBeds += bedCount; r.thorTenants++; }
    else if (building.indexOf("HULK") >= 0) { r.hulkBeds += bedCount; r.hulkTenants++; }
  }

  return r;
}

// ── DASHBOARD ───────────────────────────────────────────────────────────────

function refreshDashboard() {
  const ss = SpreadsheetApp.getActive();
  let dash = ss.getSheetByName("DASHBOARD");
  if (!dash) dash = ss.insertSheet("DASHBOARD");
  dash.clear();
  dash.setTabColor("#1565C0");

  const tabs = getMonthTabs_();
  if (tabs.length === 0) { dash.getRange("A1").setValue("No monthly tabs found."); return; }

  // Title row with dropdown
  dash.getRange("A1:D1").merge().setValue("COZEEVO DASHBOARD")
    .setFontSize(16).setFontWeight("bold").setFontColor("#1565C0").setBackground("#F5F5F5")
    .setVerticalAlignment("middle");

  // Month dropdown in E1
  const tabNames = tabs.map(t => t.name);
  const latest = tabs[tabs.length - 1].name;
  const rule = SpreadsheetApp.newDataValidation()
    .requireValueInList(tabNames, true)
    .setAllowInvalid(false)
    .build();
  dash.getRange(DROPDOWN_CELL).setDataValidation(rule).setValue(latest)
    .setFontSize(14).setFontWeight("bold").setFontColor("#FFFFFF").setBackground("#1565C0")
    .setHorizontalAlignment("center");

  // Column widths — A:200, B:150, C:100, D:200, E:150
  [200, 150, 100, 200, 150].forEach((w, i) => dash.setColumnWidth(i + 1, w));

  // Now draw the content
  refreshDashboardContent_();
}

function refreshDashboardContent_() {
  const ss = SpreadsheetApp.getActive();
  const dash = ss.getSheetByName("DASHBOARD");
  if (!dash) return;

  const tabs = getMonthTabs_();
  if (tabs.length === 0) return;

  // Read selected month from dropdown
  const selected = String(dash.getRange(DROPDOWN_CELL).getValue()).trim();
  const tab = tabs.find(t => t.name.toUpperCase() === selected.toUpperCase()) || tabs[tabs.length - 1];
  const d = readMonthData(tab.sheet);
  const collected = d.cash + d.upi;
  // Vacant must subtract day-stays too — a room with a day-stay guest is
  // not free for a new booking.
  const vacant = TOTAL_BEDS - d.beds - d.noshow - d.daywise;
  const occPct = ((d.beds + d.daywise) / TOTAL_BEDS * 100).toFixed(0);
  const deposit = getTotalDeposit_();

  // Clear content below row 1 (keep title + dropdown)
  if (dash.getMaxRows() > 1) {
    dash.getRange(2, 1, dash.getMaxRows() - 1, 8).clear();
  }

  // Ensure enough rows for all content (occupancy + collections + THOR + month-on-month)
  const neededRows = 30 + tabs.length;
  if (dash.getMaxRows() < neededRows) {
    dash.insertRowsAfter(dash.getMaxRows(), neededRows - dash.getMaxRows());
  }

  let r = 3;  // Start after title row + blank row

  // ── OCCUPANCY + COLLECTED ──
  dash.getRange(r, 1).setValue("Occupancy").setFontSize(10).setFontColor("#666666");
  dash.getRange(r, 2).setValue(d.beds + " / " + TOTAL_BEDS + " (" + occPct + "%)")
    .setFontSize(14).setFontWeight("bold").setFontColor("#1565C0");
  dash.getRange(r, 4).setValue("Collected").setFontSize(10).setFontColor("#666666");
  dash.getRange(r, 5).setValue(collected).setFontSize(14).setFontWeight("bold").setFontColor("#2E7D32")
    .setNumberFormat("#,##0");
  r++;
  dash.getRange(r, 1).setValue(d.regular + " reg + " + d.premium + " prem")
    .setFontSize(9).setFontColor("#999999");
  dash.getRange(r, 2).setValue(d.noshow + " no-show | " + d.daywise + " day-stay | " + vacant + " vacant")
    .setFontSize(9).setFontColor("#999999");
  dash.getRange(r, 4).setValue("Outstanding").setFontSize(10).setFontColor("#666666");
  dash.getRange(r, 5).setValue(d.balance).setFontSize(14).setFontWeight("bold")
    .setFontColor(d.balance > 0 ? "#D32F2F" : "#2E7D32").setNumberFormat("#,##0");
  r += 2;

  // ── COLLECTIONS + STATUS ──
  const sectBg = "#F5F5F5";
  dash.getRange(r, 1, 1, 2).merge().setValue("COLLECTIONS")
    .setFontWeight("bold").setFontSize(10).setBackground("#E8F5E9").setFontColor("#2E7D32");
  dash.getRange(r, 4, 1, 2).merge().setValue("STATUS")
    .setFontWeight("bold").setFontSize(10).setBackground("#FFF3E0").setFontColor("#E65100");
  r++;
  const rows1 = [
    ["Cash", d.cash, "", "Paid", d.paid],
    ["UPI", d.upi, "", "Partial", d.partial],
    ["Total Collected", collected, "", "Unpaid", d.unpaid],
    ["Deposit (all active)", deposit, "", "No-show", d.noshow],
    ["", "", "", "New check-ins", d.newCheckins],
  ];
  dash.getRange(r, 1, rows1.length, 5).setValues(rows1);
  dash.getRange(r, 1, rows1.length, 1).setFontColor("#333333");
  dash.getRange(r, 2, rows1.length, 1).setNumberFormat("#,##0").setFontWeight("bold")
    .setHorizontalAlignment("right").setFontColor("#333333");
  dash.getRange(r, 4, rows1.length, 1).setFontColor("#333333");
  dash.getRange(r, 5, rows1.length, 1).setFontWeight("bold").setHorizontalAlignment("right");
  // Color status rows
  dash.getRange(r, 4, 1, 2).setBackground("#E8F5E9");      // Paid - green
  dash.getRange(r + 1, 4, 1, 2).setBackground("#FFF8E1");   // Partial - yellow
  dash.getRange(r + 2, 4, 1, 2).setBackground("#FFEBEE");   // Unpaid - red
  // Alternating bg for collections
  for (let i = 0; i < rows1.length; i++) {
    dash.getRange(r + i, 1, 1, 2).setBackground(i % 2 === 0 ? "#FFFFFF" : sectBg);
  }
  r += rows1.length + 1;

  // ── THOR vs HULK ──
  dash.getRange(r, 1, 1, 5).merge().setValue("THOR vs HULK")
    .setFontWeight("bold").setFontSize(10).setBackground("#ECEFF1").setFontColor("#37474F");
  r++;
  const thorColl = d.thorCash + d.thorUpi;
  const hulkColl = d.hulkCash + d.hulkUpi;
  dash.getRange(r, 1, 1, 5).setValues([["", "THOR", "", "HULK", ""]])
    .setFontWeight("bold").setBackground("#CFD8DC").setHorizontalAlignment("center");
  r++;
  const thData = [
    ["Beds", d.thorBeds, "", d.hulkBeds, ""],
    ["Tenants", d.thorTenants, "", d.hulkTenants, ""],
    ["Collected", thorColl, "", hulkColl, ""],
    ["Rent Expected", d.thorRent, "", d.hulkRent, ""],
  ];
  dash.getRange(r, 1, thData.length, 5).setValues(thData);
  dash.getRange(r, 2, thData.length, 1).setNumberFormat("#,##0").setFontWeight("bold").setHorizontalAlignment("right");
  dash.getRange(r, 4, thData.length, 1).setNumberFormat("#,##0").setFontWeight("bold").setHorizontalAlignment("right");
  for (let i = 0; i < thData.length; i++) {
    dash.getRange(r + i, 1, 1, 5).setBackground(i % 2 === 0 ? "#FFFFFF" : sectBg);
  }
  r += thData.length + 1;

  // ── MONTH-ON-MONTH ──
  dash.getRange(r, 1, 1, 5).merge().setValue("MONTH-ON-MONTH")
    .setFontWeight("bold").setFontSize(10).setBackground("#E8EAF6").setFontColor("#283593");
  r++;
  dash.getRange(r, 1, 1, 5).setValues([["Month", "Beds", "Collected", "Dues", "Paid%"]])
    .setFontWeight("bold").setBackground("#C5CAE9").setHorizontalAlignment("center");
  r++;
  const momRows = [];
  tabs.forEach(t => {
    try {
      const md = readMonthData(t.sheet);
      const mc = md.cash + md.upi;
      const paidPct = md.rentExpected > 0 ? Math.round(mc / md.rentExpected * 100) + "%" : "—";
      momRows.push([t.name, md.beds, mc, md.balance, paidPct]);
    } catch (err) {
      momRows.push([t.name, "ERR", 0, 0, "—"]);
    }
  });
  if (momRows.length > 0) {
    dash.getRange(r, 1, momRows.length, 5).setValues(momRows);
    dash.getRange(r, 3, momRows.length, 2).setNumberFormat("#,##0");
    dash.getRange(r, 2, momRows.length, 4).setHorizontalAlignment("right");
    for (let i = 0; i < momRows.length; i++) {
      const bg = (momRows[i][0] === tab.name) ? "#BBDEFB" : (i % 2 === 0 ? "#FFFFFF" : sectBg);
      dash.getRange(r + i, 1, 1, 5).setBackground(bg);
    }
  } else {
    dash.getRange(r, 1).setValue("No monthly tabs found").setFontColor("#999999");
    r++;
  }
  r += momRows.length + 1;

  // ── FOOTER ──
  dash.getRange(r, 1, 1, 5).merge()
    .setValue("Auto-updates on edit | Select month above | " + new Date().toLocaleString("en-IN"))
    .setFontColor("#9E9E9E").setFontSize(9);

  SpreadsheetApp.getActive().toast("Showing: " + tab.name, "Dashboard", 2);
}

// ── UPDATE MONTH SUMMARY (called on edit) ───────────────────────────────────

function updateMonthSummary(sheet) {
  // ONLY runs on legacy (4-row header) tabs. New layout has 5 summary cards
  // at rows 2-6 written directly by sync_sheet_from_db.py — touching them
  // here would corrupt them. The caller (onSheetEdit) gates this with
  // isLegacyLayout_(); we re-check defensively in case it's called directly.
  const data = sheet.getDataRange().getValues();
  const headerIdx = _findRow_(data, "Room", 12);
  if (headerIdx !== 3) return;  // not legacy → don't touch summary rows

  const cm = _colMap_(data[headerIdx]);
  const cRent = _col_(cm, "Rent Due");
  const cCash = _col_(cm, "Cash");
  const cUpi = _col_(cm, "UPI");
  const cTp = _col_(cm, "Total Paid");
  const cBal = _col_(cm, "Balance");
  const cSt = _col_(cm, "Status");
  const cPrev = _col_(cm, "Prev Due");
  const lastColIdx = data[headerIdx].length;
  const lastCol = _colLetter_(lastColIdx);

  const d = readMonthData(sheet);
  const collected = d.cash + d.upi;
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = (d.beds / TOTAL_BEDS * 100).toFixed(1);

  // Build row arrays sized to last column
  function _padRow(arr) {
    const out = arr.slice();
    while (out.length < lastColIdx) out.push("");
    return out;
  }
  const r2 = _padRow([
    "Checked-in", d.beds + " beds (" + d.regular + "+" + d.premium + "P)",
    "No-show: " + d.noshow, "Vacant: " + vacant, "Occ: " + occPct + "%",
    "Cash", d.cash, "UPI", d.upi, "Total", collected, "Bal: " + d.balance,
  ]);
  const r3 = _padRow([
    "THOR: " + d.thorBeds + "b (" + d.thorTenants + "t)",
    "HULK: " + d.hulkBeds + "b (" + d.hulkTenants + "t)",
    "New: " + d.newCheckins, "Exit: " + d.exits, "",
    "PAID:" + d.paid, "PARTIAL:" + d.partial, "UNPAID:" + d.unpaid,
  ]);
  sheet.getRange("A2:" + lastCol + "2").setValues([r2]);
  sheet.getRange("A3:" + lastCol + "3").setValues([r3]);
  sheet.getRange("A2:" + lastCol + "3").setFontSize(9).setFontWeight("bold")
    .setFontColor("#444444").setBackground("#F8F9FA")
    .setBorder(false, false, false, false, false, false);

  // Per-row recalc: Total Paid, Balance, Status (legacy layout only)
  for (let i = headerIdx + 1; i < data.length; i++) {
    if (!data[i][0]) continue;
    const curSt = String(data[i][cSt] || "").toUpperCase().trim();
    if (["EXIT", "NO SHOW", "NO-SHOW", "ADVANCE", "CANCELLED"].indexOf(curSt) >= 0) continue;
    const cash = pn(data[i][cCash]);
    const upi = pn(data[i][cUpi]);
    const rent = pn(data[i][cRent]);
    const prevDue = (cPrev >= 0) ? pn(data[i][cPrev]) : 0;
    const tp = cash + upi;
    let bal = rent + prevDue - tp;
    if (bal < 0) bal = 0;  // excess is deposit/advance, not overpayment
    // Status: current rent only (ignore prev due). Kiran 2026-04-23.
    const st = (tp >= rent) ? "PAID" : "PARTIAL";
    if (cTp >= 0) sheet.getRange(i + 1, cTp + 1).setValue(tp);
    if (cBal >= 0) sheet.getRange(i + 1, cBal + 1).setValue(bal);
    if (cSt >= 0) sheet.getRange(i + 1, cSt + 1).setValue(st);
  }
}

// 0-indexed col → letter (A, B, ..., Z, AA, AB, ...). Apps Script-friendly.
function _colLetter_(colIdx) {
  let n = colIdx;
  let s = "";
  while (n > 0) {
    const r = (n - 1) % 26;
    s = String.fromCharCode(65 + r) + s;
    n = Math.floor((n - 1) / 26);
  }
  return s || "A";
}

// ── NEW MONTH ───────────────────────────────────────────────────────────────

function createNewMonthIfNeeded() {
  const today = new Date();
  const tabName = MONTH_NAMES[today.getMonth()] + " " + today.getFullYear();
  const ss = SpreadsheetApp.getActive();
  if (ss.getSheetByName(tabName)) return;
  createMonthTab(tabName, today.getMonth(), today.getFullYear());
  refreshDashboard();
}

function createNextMonth() {
  const next = new Date();
  next.setMonth(next.getMonth() + 1);
  const tabName = MONTH_NAMES[next.getMonth()] + " " + next.getFullYear();
  const ss = SpreadsheetApp.getActive();
  if (ss.getSheetByName(tabName)) { SpreadsheetApp.getUi().alert(tabName + " already exists!"); return; }
  createMonthTab(tabName, next.getMonth(), next.getFullYear());
  refreshDashboard();
}

function createMonthTab(tabName, monthIdx, year) {
  // DEPRECATED: New month tabs are created by Python's
  // scripts/sync_sheet_from_db.py (header-driven, 19 cols, matches DB).
  // This legacy creator builds a 17-col tab with old layout — only kept as
  // a fallback when the script is run from the Cozeevo menu without server
  // access. Do not call from new code.
  const ss = SpreadsheetApp.getActive();
  const tenants = ss.getSheetByName("TENANTS");
  if (!tenants) { SpreadsheetApp.getUi().alert("TENANTS tab not found!"); return; }
  SpreadsheetApp.getActive().toast(
    "Legacy month creator — prefer running scripts/sync_sheet_from_db.py.",
    "Heads up", 5);

  // ── Find previous month tab to get dues + notes ──
  const prevIdx = monthIdx === 0 ? 11 : monthIdx - 1;
  const prevYear = monthIdx === 0 ? year - 1 : year;
  const prevTab = MONTH_NAMES[prevIdx] + " " + prevYear;
  const prevSheet = ss.getSheetByName(prevTab);

  // Build lookup: tenant name → {balance, notes} from previous month
  const prevData = {};
  if (prevSheet) {
    const pData = prevSheet.getDataRange().getValues();
    const hdr = pData.length > 3 ? pData[3] : [];
    const isNewFmt = String(hdr[2] || "").toUpperCase().includes("PHONE");
    const balCol = isNewFmt ? 9 : 8;
    const notesCol = isNewFmt ? 14 : 12;
    const startRow = pData.length > 4 ? 4 : 1;
    for (let i = startRow; i < pData.length; i++) {
      const name = String(pData[i][1]).trim();
      if (!name) continue;
      prevData[name] = {
        balance: pn(pData[i][balCol]),
        notes: String(pData[i][notesCol] || "").trim(),
      };
    }
  }

  const tData = tenants.getDataRange().getValues();
  const sheet = ss.insertSheet(tabName);

  // 17 columns: A-Q (DB-aligned)
  const headers = ["Room", "Name", "Phone", "Building", "Sharing", "Rent Due",
    "Cash", "UPI", "Total Paid", "Balance", "Status",
    "Check-in", "Notice Date", "Event", "Notes", "Prev Due", "Entered By"];

  sheet.getRange("A1").setValue(tabName);
  sheet.getRange("A1:Q1").merge().setFontSize(13).setFontWeight("bold");
  sheet.getRange("A2:Q2").setValues([["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]]);
  sheet.getRange("A3:Q3").setValues([["", "", "", "", "", "", "", "", "", "", "", "", "", "", "", "", ""]]);
  sheet.getRange("A4:Q4").setValues([headers]).setFontWeight("bold").setBackground("#D6EAF8");

  const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
  const mStart = new Date(year, monthIdx, 1);
  const mEnd = new Date(year, monthIdx, daysInMonth);

  // TENANTS: 0=Room,1=Name,2=Phone,3=Gender,4=Building,5=Floor,6=Sharing,7=Checkin,8=Status,9=AgreedRent,10=Deposit,...,13=NoticeDate
  const rows = [];
  for (let i = 1; i < tData.length; i++) {
    const t = tData[i];
    const status = String(t[8]).trim();
    if (status !== "Active" && status !== "No-show") continue;

    const rent = pn(t[9]);  // Agreed Rent
    let rentDue = rent;
    let event = "";

    const checkin = parseDate_(t[7]);
    if (checkin && checkin >= mStart && checkin <= mEnd) {
      event = status === "No-show" ? "NO-SHOW" : "NEW CHECK-IN";
      if (status !== "No-show") {
        rentDue = Math.floor(rent * (daysInMonth - checkin.getDate() + 1) / daysInMonth);
      }
    }
    if (status === "No-show" && (!checkin || checkin > mEnd)) continue;

    const name = String(t[1]).trim();
    const prev = prevData[name] || { balance: 0, notes: "" };
    const prevDue = prev.balance > 0 ? prev.balance : 0;
    const totalDue = rentDue + prevDue;
    const noticeDate = String(t[13] || "").trim();  // Notice Date from TENANTS

    // Carry forward notes from previous month if tenant has dues
    const carryNotes = (prevDue > 0 && prev.notes) ? "[" + prevTab.split(" ")[0].substring(0, 3) + "] " + prev.notes.substring(0, 100) : "";

    rows.push([
      t[0], t[1], t[2],          // A: Room, B: Name, C: Phone
      t[4], t[6],                 // D: Building, E: Sharing
      rentDue,                    // F: Rent Due
      0, 0, 0,                   // G: Cash, H: UPI, I: Total Paid
      totalDue,                   // J: Balance = rent + prevDue
      "PARTIAL",                  // K: Status (no UNPAID on live months — Kiran 2026-04-23)
      t[7],                       // L: Check-in
      noticeDate,                 // M: Notice Date
      event,                      // N: Event
      carryNotes,                 // O: Notes (carried from prev month if dues exist)
      prevDue,                    // P: Prev Due
      "",                         // Q: Entered By
    ]);
  }

  if (rows.length > 0) sheet.getRange(5, 1, rows.length, 17).setValues(rows);

  sheet.setFrozenRows(4);
  sheet.getRange("F5:J" + (4 + rows.length)).setNumberFormat("#,##0");
  sheet.getRange("P5:P" + (4 + rows.length)).setNumberFormat("#,##0");

  // Conditional formatting for Status (col K)
  const sRange = sheet.getRange("K5:K" + (4 + rows.length));
  sheet.setConditionalFormatRules([
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("PAID").setBackground("#D5F5E3").setFontColor("#1E8449").setRanges([sRange]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("PARTIAL").setBackground("#FEF9E7").setFontColor("#B7950B").setRanges([sRange]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("UNPAID").setBackground("#FDEDEC").setFontColor("#CB4335").setRanges([sRange]).build(),
  ]);

  // Highlight Prev Due > 0 in red (col P)
  const pRange = sheet.getRange("P5:P" + (4 + rows.length));
  const existingRules = sheet.getConditionalFormatRules();
  existingRules.push(
    SpreadsheetApp.newConditionalFormatRule().whenNumberGreaterThan(0).setBackground("#FFEBEE").setFontColor("#D32F2F").setRanges([pRange]).build()
  );
  sheet.setConditionalFormatRules(existingRules);

  sheet.getRange("A4:Q" + (4 + rows.length)).createFilter();
  [70, 180, 120, 70, 80, 90, 90, 90, 90, 90, 80, 100, 100, 100, 200, 90, 100].forEach((w, i) => sheet.setColumnWidth(i + 1, w));

  updateMonthSummary(sheet);

  // Auto-lock new tab (only bot + owner can edit)
  _protectSheet(sheet);
}

function _protectSheet(sheet) {
  var ss = SpreadsheetApp.getActive();
  var botEmail = "cozeevo-sheets-bot@cozeevo-bot-491219.iam.gserviceaccount.com";
  var protection = sheet.protect().setDescription("Read-only: " + sheet.getName());
  protection.removeEditors(protection.getEditors());
  protection.addEditor(botEmail);
  protection.addEditor(ss.getOwner().getEmail());
  if (protection.canDomainEdit()) {
    protection.setDomainEdit(false);
  }
}

function parseDate_(val) {
  if (!val) return null;
  const s = String(val).trim();
  const fmts = [/^(\d{2})-(\d{2})-(\d{4})$/, /^(\d{2})\/(\d{2})\/(\d{4})$/, /^(\d{4})-(\d{2})-(\d{2})$/];
  for (const f of fmts) {
    const m = s.match(f);
    if (m) {
      if (m[1].length === 4) return new Date(+m[1], +m[2] - 1, +m[3]);
      else return new Date(+m[3], +m[2] - 1, +m[1]);
    }
  }
  const d = new Date(val);
  return isNaN(d.getTime()) ? null : d;
}

// ── VALIDATION ──────────────────────────────────────────────────────────────

function validateTotals() {
  // Header-driven validation: sum data rows by header name, compare against
  // the readMonthData() aggregate. Works on legacy AND new layouts.
  const ss = SpreadsheetApp.getActive();
  const issues = [];

  ss.getSheets().forEach(sheet => {
    if (!MONTH_TAB_RE.test(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    const headerIdx = _findRow_(data, "Room", 12);
    if (headerIdx < 0) return;

    const cm = _colMap_(data[headerIdx]);
    const cRent = _col_(cm, "Rent Due");
    const cCash = _col_(cm, "Cash");
    const cUpi = _col_(cm, "UPI");
    if (cRent < 0 || cCash < 0 || cUpi < 0) return;

    let sumCash = 0, sumUpi = 0, sumRent = 0;
    for (let i = headerIdx + 1; i < data.length; i++) {
      if (!data[i][0]) continue;
      sumRent += pn(data[i][cRent]);
      sumCash += pn(data[i][cCash]);
      sumUpi += pn(data[i][cUpi]);
    }

    const d = readMonthData(sheet);
    if (Math.abs(d.rentExpected - sumRent) > 1)
      issues.push(sheet.getName() + ": readMonth Rent " + d.rentExpected + " != row sum " + sumRent);
    if (Math.abs((d.cash + d.upi) - (sumCash + sumUpi)) > 1)
      issues.push(sheet.getName() + ": readMonth Collected " + (d.cash + d.upi) + " != row sum " + (sumCash + sumUpi));
  });

  SpreadsheetApp.getUi().alert(issues.length === 0
    ? "All totals consistent!"
    : "Issues:\n\n" + issues.join("\n"));
}
