/**
 * Cozeevo Operations — Google Apps Script v4
 * ============================================
 * Paste into: Extensions > Apps Script
 * Run setupTriggers() once.
 *
 * FEATURES:
 *   - Month dropdown on dashboard — switch between any month
 *   - Auto-refresh on edit (any monthly tab or TENANTS)
 *   - Deposit total from TENANTS tab (Active tenants only)
 *   - THOR vs HULK comparison per selected month
 *   - Month-on-month trend table
 *
 * COLUMN LAYOUT (monthly tabs, row 5+, DB-aligned):
 *   A=Room, B=Name, C=Phone, D=Building, E=Sharing, F=Rent Due,
 *   G=Cash, H=UPI, I=Total Paid, J=Balance, K=Status,
 *   L=Check-in, M=Notice Date, N=Event, O=Notes, P=Prev Due,
 *   Q=Entered By
 */

const TOTAL_BEDS = 291;
const MONTH_NAMES = ["JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER"];
const MONTH_TAB_RE = /^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}$/i;
const DROPDOWN_CELL = "E1";  // Where the month picker lives on DASHBOARD

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
    .addToUi();
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
      updateMonthSummary(sheet);
      refreshDashboardContent_();
    } else if (name === "TENANTS") {
      refreshDashboard();
    }
  } catch (err) { }
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
  // TENANTS: 0=Room,1=Name,...,8=Status,...,11=Deposit
  let total = 0;
  for (let i = 1; i < data.length; i++) {
    const status = String(data[i][8]).trim();
    if (status === "Active") {
      total += pn(data[i][11]);
    }
  }
  return total;
}

// ── READ MONTHLY TAB ────────────────────────────────────────────────────────

function readMonthData(sheet) {
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

  // Detect column layout: new format has Phone in col 2 (header row check)
  const headers = data.length > 3 ? data[3] : [];
  const isNew = String(headers[2] || "").toUpperCase().includes("PHONE");
  // Old: A=Room,B=Name,C=Building,D=Sharing,E=Rent,F=Cash,G=UPI,H=TotalPaid,I=Balance,J=Status,K=Checkin,L=Event,M=Notes,N=Chandra,O=Lakshmi
  // New: A=Room,B=Name,C=Phone,D=Building,E=Sharing,F=Rent,G=Cash,H=UPI,I=TotalPaid,J=Balance,K=Status,L=Checkin,M=Notice,N=Event,O=Notes,P=PrevDue
  const C = isNew
    ? { building: 3, sharing: 4, rent: 5, cash: 6, upi: 7, bal: 9, status: 10, event: 13 }
    : { building: 2, sharing: 3, rent: 4, cash: 5, upi: 6, bal: 8, status: 9, event: 11 };

  for (let i = 4; i < data.length; i++) {
    const row = data[i];
    if (!row[0] || !row[1]) continue;

    const building = String(row[C.building]).toUpperCase().trim();
    const sharing = String(row[C.sharing]).toLowerCase().trim();
    const rentDue = pn(row[C.rent]);
    const cash = pn(row[C.cash]);
    const upi = pn(row[C.upi]);
    const bal = pn(row[C.bal]);
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
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = (d.beds / TOTAL_BEDS * 100).toFixed(0);
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
  dash.getRange(r, 2).setValue(d.noshow + " no-show | " + vacant + " vacant")
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
    ["Deposit (all active)", deposit, "", "Exits", d.exits],
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
  const d = readMonthData(sheet);
  const collected = d.cash + d.upi;
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = (d.beds / TOTAL_BEDS * 100).toFixed(1);

  // Detect column layout
  const hdr = sheet.getRange("A4:P4").getValues()[0];
  const isNew = String(hdr[2] || "").toUpperCase().includes("PHONE");

  // Summary rows — clean formatting, no grids
  const lastCol = isNew ? "Q" : "O";

  // Row 2: Occupancy + Collections
  const r2 = isNew
    ? ["Checked-in", d.beds + " beds (" + d.regular + "+" + d.premium + "P)",
       "No-show: " + d.noshow, "Vacant: " + vacant, "Occ: " + occPct + "%",
       "Cash", d.cash, "UPI", d.upi, "Total", collected,
       "Bal: " + d.balance, "", "", "", "", ""]
    : ["Checked-in", d.beds + " beds (" + d.regular + "+" + d.premium + "P)",
       "No-show: " + d.noshow, "Vacant: " + vacant, "Occ: " + occPct + "%",
       "Cash", d.cash, "UPI", d.upi, "Total", collected,
       "Bal: " + d.balance, "", "", ""];
  sheet.getRange("A2:" + lastCol + "2").setValues([r2]);

  // Row 3: Status + Movement
  const r3 = isNew
    ? ["THOR: " + d.thorBeds + "b (" + d.thorTenants + "t)", "HULK: " + d.hulkBeds + "b (" + d.hulkTenants + "t)",
       "New: " + d.newCheckins, "Exit: " + d.exits, "",
       "PAID:" + d.paid, "PARTIAL:" + d.partial, "UNPAID:" + d.unpaid,
       "", "", "", "", "", "", "", "", ""]
    : ["THOR: " + d.thorBeds + "b (" + d.thorTenants + "t)", "HULK: " + d.hulkBeds + "b (" + d.hulkTenants + "t)",
       "New: " + d.newCheckins, "Exit: " + d.exits, "",
       "PAID:" + d.paid, "PARTIAL:" + d.partial, "UNPAID:" + d.unpaid,
       "", "", "", "", "", "", ""];
  sheet.getRange("A3:" + lastCol + "3").setValues([r3]);

  // Format rows 1-3: bold, smaller font, no gridlines
  sheet.getRange("A2:" + lastCol + "3").setFontSize(9).setFontWeight("bold")
    .setFontColor("#444444").setBackground("#F8F9FA")
    .setBorder(false, false, false, false, false, false);
  // Number formatting for financial cells in row 2
  if (isNew) {
    sheet.getRange("G2").setNumberFormat("#,##0");
    sheet.getRange("I2").setNumberFormat("#,##0");
    sheet.getRange("K2").setNumberFormat("#,##0");
  } else {
    sheet.getRange("G2").setNumberFormat("#,##0");
    sheet.getRange("I2").setNumberFormat("#,##0");
    sheet.getRange("K2").setNumberFormat("#,##0");
  }

  // Recalculate Total Paid, Balance, Status per row
  const data = sheet.getDataRange().getValues();
  // Column indices
  const ci = isNew
    ? { rent: 5, cash: 6, upi: 7, tp: 8, bal: 9, st: 10, prevDue: 15 }
    : { rent: 4, cash: 5, upi: 6, tp: 7, bal: 8, st: 9, prevDue: 15 };

  for (let i = 4; i < data.length; i++) {
    if (!data[i][0]) continue;
    const curSt = String(data[i][ci.st]).toUpperCase().trim();
    if (curSt === "EXIT" || curSt === "NO SHOW" || curSt === "ADVANCE" || curSt === "CANCELLED") continue;

    const cash = pn(data[i][ci.cash]);
    const upi = pn(data[i][ci.upi]);
    const rent = pn(data[i][ci.rent]);
    const prevDue = pn(data[i][ci.prevDue]);
    const tp = cash + upi;
    const bal = rent + prevDue - tp;
    const st = (tp === 0) ? "UNPAID" : (bal <= 0 ? "PAID" : "PARTIAL");
    sheet.getRange(i + 1, ci.tp + 1).setValue(tp);
    sheet.getRange(i + 1, ci.bal + 1).setValue(bal);
    sheet.getRange(i + 1, ci.st + 1).setValue(st);
  }
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
  const ss = SpreadsheetApp.getActive();
  const tenants = ss.getSheetByName("TENANTS");
  if (!tenants) { SpreadsheetApp.getUi().alert("TENANTS tab not found!"); return; }

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
      "UNPAID",                   // K: Status
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
  const ss = SpreadsheetApp.getActive();
  const issues = [];

  ss.getSheets().forEach(sheet => {
    if (!MONTH_TAB_RE.test(sheet.getName())) return;
    const data = sheet.getDataRange().getValues();
    if (data.length < 5) return;

    let sumCash = 0, sumUpi = 0, sumRent = 0;
    for (let i = 4; i < data.length; i++) {
      if (!data[i][0]) continue;
      sumRent += pn(data[i][4]);
      sumCash += pn(data[i][5]);
      sumUpi += pn(data[i][6]);
    }

    const hRent = pn(data[1][6]);
    const hColl = pn(data[1][8]);
    const calc = sumCash + sumUpi;

    if (Math.abs(hRent - sumRent) > 1) issues.push(sheet.getName() + ": Rent header " + hRent + " != rows " + sumRent);
    if (Math.abs(hColl - calc) > 1) issues.push(sheet.getName() + ": Collected header " + hColl + " != rows " + calc);
  });

  SpreadsheetApp.getUi().alert(issues.length === 0
    ? "All totals consistent!"
    : "Issues:\n\n" + issues.join("\n"));
}
