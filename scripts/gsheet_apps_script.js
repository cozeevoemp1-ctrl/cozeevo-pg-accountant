/**
 * Cozeevo Operations — Google Apps Script v3
 * ============================================
 * Paste into: Extensions > Apps Script
 * Run setupTriggers() once.
 *
 * COLUMN LAYOUT (monthly tabs, row 5+):
 *   A=Room, B=Name, C=Building, D=Sharing, E=Rent Due,
 *   F=Cash Paid, G=UPI Paid, H=Total Paid, I=Balance,
 *   J=Status, K=Check-in, L=Event, M=Notes,
 *   N=Chandra, O=Lakshmi
 *
 * ROW LAYOUT:
 *   1: Title (month name)
 *   2: Occupancy summary (auto-updated)
 *   3: Financial summary (auto-updated)
 *   4: Headers
 *   5+: Tenant data
 */

const TOTAL_BEDS = 291;
const MONTH_NAMES = ["JANUARY","FEBRUARY","MARCH","APRIL","MAY","JUNE","JULY","AUGUST","SEPTEMBER","OCTOBER","NOVEMBER","DECEMBER"];
const MONTH_TAB_RE = /^(JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)\s+\d{4}$/;

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
    const name = e.source.getActiveSheet().getName();
    if (MONTH_TAB_RE.test(name)) {
      updateMonthSummary(e.source.getActiveSheet());
      refreshDashboard();
    } else if (name === "TENANTS") {
      refreshDashboard();
    }
  } catch (err) {}
}

// ── READ MONTHLY TAB (row-by-row, no header parsing) ────────────────────────

function pn(val) {
  if (!val) return 0;
  const n = parseFloat(String(val).replace(/,/g, "").trim());
  return isNaN(n) ? 0 : n;
}

function readMonthData(sheet) {
  const data = sheet.getDataRange().getValues();
  const r = {
    tenants: 0, beds: 0, regular: 0, premium: 0, noshow: 0,
    cash: 0, upi: 0, balance: 0, rentExpected: 0,
    chandra: 0, lakshmi: 0,
    paid: 0, partial: 0, unpaid: 0,
    newCheckins: 0, exits: 0,
    thorBeds: 0, hulkBeds: 0, thorTenants: 0, hulkTenants: 0,
    thorRent: 0, hulkRent: 0,
    thorCash: 0, hulkCash: 0, thorUpi: 0, hulkUpi: 0,
  };
  if (data.length < 5) return r;

  for (let i = 4; i < data.length; i++) {
    const row = data[i];
    if (!row[0] || !row[1]) continue;

    const building = String(row[2]).toUpperCase().trim();
    const sharing = String(row[3]).toLowerCase().trim();
    const rentDue = pn(row[4]);
    const cash = pn(row[5]);
    const upi = pn(row[6]);
    const bal = pn(row[8]);
    const status = String(row[9]).toUpperCase().trim();
    const event = String(row[11]).toUpperCase().trim();
    const chandra = pn(row[13]);  // Column N
    const lakshmi = pn(row[14]);  // Column O

    r.tenants++;
    r.cash += cash;
    r.upi += upi;
    r.balance += bal;
    r.rentExpected += rentDue;
    r.chandra += chandra;
    r.lakshmi += lakshmi;

    // Building split
    if (building === "THOR") { r.thorRent += rentDue; r.thorCash += cash; r.thorUpi += upi; }
    else { r.hulkRent += rentDue; r.hulkCash += cash; r.hulkUpi += upi; }

    // Payment status
    if (status === "PAID") r.paid++;
    else if (status === "PARTIAL") r.partial++;
    else if (status === "UNPAID") r.unpaid++;

    // Events
    if (event.includes("NEW CHECK-IN")) r.newCheckins++;
    if (event.includes("EXITED") || status === "EXIT") r.exits++;

    // Occupancy: count beds for active tenants (not EXIT, not pure NO-SHOW)
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

  // Collect all monthly tabs sorted
  const tabs = [];
  ss.getSheets().forEach(s => {
    if (MONTH_TAB_RE.test(s.getName())) {
      const p = s.getName().split(" ");
      tabs.push({ name: s.getName(), sheet: s, sort: parseInt(p[1]) * 100 + MONTH_NAMES.indexOf(p[0]) });
    }
  });
  tabs.sort((a, b) => a.sort - b.sort);
  if (tabs.length === 0) { dash.getRange("A1").setValue("No monthly tabs found."); return; }

  const latest = tabs[tabs.length - 1];
  const d = readMonthData(latest.sheet);
  const collected = d.cash + d.upi;
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = (d.beds / TOTAL_BEDS * 100).toFixed(1);
  const collPct = d.rentExpected > 0 ? (collected / d.rentExpected * 100).toFixed(1) : "0";

  let row = 1;

  // ── HEADER ──
  dash.getRange(row, 1, 1, 8).merge().setValue("COZEEVO OPERATIONS DASHBOARD")
    .setFontSize(18).setFontWeight("bold").setFontColor("#1565C0").setBackground("#F5F5F5");
  row += 2;

  // ── CURRENT MONTH BADGE ──
  dash.getRange(row, 1, 1, 8).merge().setValue("  " + latest.name)
    .setFontSize(14).setFontWeight("bold").setBackground("#1565C0").setFontColor("#FFFFFF");
  row += 2;

  // ── OCCUPANCY CARD (A) ──
  const occStart = row;
  dash.getRange(row, 1, 1, 3).merge().setValue("OCCUPANCY").setFontWeight("bold").setFontSize(11)
    .setBackground("#E3F2FD").setFontColor("#1565C0");
  row++;
  const occRows = [
    ["Revenue Beds", TOTAL_BEDS, ""],
    ["Checked-in", d.beds, d.regular + " reg + " + d.premium + " premium"],
    ["No-show", d.noshow, "booked, not arrived"],
    ["Vacant", vacant, ""],
    ["Occupancy", occPct + "%", ""],
  ];
  dash.getRange(row, 1, occRows.length, 3).setValues(occRows);
  dash.getRange(row, 2, occRows.length, 1).setFontWeight("bold").setHorizontalAlignment("right");
  dash.getRange(row + 4, 2).setNumberFormat("@");  // Force text for percentage
  dash.getRange(row, 3, occRows.length, 1).setFontColor("#666666").setFontSize(9);
  row += occRows.length;
  dash.getRange(occStart, 1, row - occStart, 3)
    .setBorder(true, true, true, true, false, false, "#BBDEFB", SpreadsheetApp.BorderStyle.SOLID);

  // ── COLLECTIONS CARD (E) ──
  const collStart = occStart;
  let cr = collStart;
  dash.getRange(cr, 5, 1, 3).merge().setValue("COLLECTIONS").setFontWeight("bold").setFontSize(11)
    .setBackground("#E8F5E9").setFontColor("#2E7D32");
  cr++;
  const collRows = [
    ["Cash", d.cash, ""],
    ["UPI", d.upi, ""],
    ["Total Collected", collected, collPct + "%"],
    ["", "", ""],
    ["", "", ""],
  ];
  dash.getRange(cr, 5, collRows.length, 3).setValues(collRows);
  dash.getRange(cr, 6, collRows.length, 1).setNumberFormat("#,##0").setFontWeight("bold").setHorizontalAlignment("right");
  dash.getRange(cr, 7, collRows.length, 1).setFontColor("#666666").setFontSize(9);
  dash.getRange(collStart, 5, row - collStart, 3)
    .setBorder(true, true, true, true, false, false, "#C8E6C9", SpreadsheetApp.BorderStyle.SOLID);

  row += 1;

  // ── PAYMENT STATUS + MOVEMENT ROW ──
  const psStart = row;
  dash.getRange(row, 1, 1, 3).merge().setValue("PAYMENT STATUS").setFontWeight("bold").setFontSize(11)
    .setBackground("#FFF3E0").setFontColor("#E65100");
  dash.getRange(row, 5, 1, 3).merge().setValue("MOVEMENT").setFontWeight("bold").setFontSize(11)
    .setBackground("#F3E5F5").setFontColor("#6A1B9A");
  row++;
  const psRows = [
    ["Paid", d.paid, ""],
    ["Partial", d.partial, ""],
    ["Unpaid", d.unpaid, ""],
  ];
  dash.getRange(row, 1, 3, 3).setValues(psRows);
  dash.getRange(row, 2, 3, 1).setFontWeight("bold").setHorizontalAlignment("right");
  dash.getRange(row, 1, 1, 3).setBackground("#E8F5E9");
  dash.getRange(row + 1, 1, 1, 3).setBackground("#FFF8E1");
  dash.getRange(row + 2, 1, 1, 3).setBackground("#FFEBEE");

  const mvRows = [
    ["New Check-ins", d.newCheckins, ""],
    ["Exits", d.exits, ""],
    ["No-show", d.noshow, ""],
  ];
  dash.getRange(row, 5, 3, 3).setValues(mvRows);
  dash.getRange(row, 6, 3, 1).setFontWeight("bold").setHorizontalAlignment("right");

  dash.getRange(psStart, 1, 4, 3).setBorder(true, true, true, true, false, false, "#FFE0B2", SpreadsheetApp.BorderStyle.SOLID);
  dash.getRange(psStart, 5, 4, 3).setBorder(true, true, true, true, false, false, "#E1BEE7", SpreadsheetApp.BorderStyle.SOLID);
  row += 4;

  // ── OUTSTANDING / DUES ──
  const outStart = row;
  dash.getRange(row, 1, 1, 3).merge().setValue("OUTSTANDING").setFontWeight("bold").setFontSize(11)
    .setBackground("#FCE4EC").setFontColor("#C62828");
  row++;
  const outRows = [
    ["Tenant Dues", d.balance, "from Balance column"],
    ["Chandra (collected)", d.chandra, "not in Cash totals"],
    ["Lakshmi (collected)", d.lakshmi, "not in Cash totals"],
  ];
  dash.getRange(row, 1, outRows.length, 3).setValues(outRows);
  dash.getRange(row, 2, outRows.length, 1).setNumberFormat("#,##0").setFontWeight("bold").setHorizontalAlignment("right");
  dash.getRange(row, 3, outRows.length, 1).setFontColor("#666666").setFontSize(9);
  if (d.balance > 0) dash.getRange(row, 2).setFontColor("#D32F2F");
  dash.getRange(outStart, 1, outRows.length + 1, 3)
    .setBorder(true, true, true, true, false, false, "#F8BBD0", SpreadsheetApp.BorderStyle.SOLID);
  row += outRows.length + 1;

  // ── THOR vs HULK ──
  dash.getRange(row, 1, 1, 8).merge().setValue("THOR vs HULK COMPARISON").setFontWeight("bold").setFontSize(12)
    .setBackground("#ECEFF1").setFontColor("#37474F");
  row++;
  const thHeaders = ["", "THOR", "HULK", "TOTAL"];
  dash.getRange(row, 1, 1, 4).setValues([thHeaders]).setFontWeight("bold").setBackground("#CFD8DC");
  row++;
  const thorCollected = d.thorCash + d.thorUpi;
  const hulkCollected = d.hulkCash + d.hulkUpi;
  const thRows = [
    ["Beds Occupied", d.thorBeds, d.hulkBeds, d.beds],
    ["Tenants", d.thorTenants, d.hulkTenants, d.thorTenants + d.hulkTenants],
    ["Rent Expected", d.thorRent, d.hulkRent, d.rentExpected],
    ["Cash", d.thorCash, d.hulkCash, d.cash],
    ["UPI", d.thorUpi, d.hulkUpi, d.upi],
    ["Total Collected", thorCollected, hulkCollected, collected],
  ];
  dash.getRange(row, 1, thRows.length, 4).setValues(thRows);
  dash.getRange(row, 2, thRows.length, 3).setNumberFormat("#,##0").setHorizontalAlignment("right");
  for (let i = 0; i < thRows.length; i++) {
    dash.getRange(row + i, 1, 1, 4).setBackground(i % 2 === 0 ? "#FFFFFF" : "#FAFAFA");
  }
  dash.getRange(row - 1, 1, thRows.length + 1, 4)
    .setBorder(true, true, true, true, true, true, "#B0BEC5", SpreadsheetApp.BorderStyle.SOLID);
  row += thRows.length + 1;

  // ── MONTH-ON-MONTH ──
  dash.getRange(row, 1, 1, 8).merge().setValue("MONTH-ON-MONTH TREND").setFontWeight("bold").setFontSize(12)
    .setBackground("#E8EAF6").setFontColor("#283593");
  row++;
  const momH = ["Month", "Tenants", "Beds", "Cash", "UPI", "Collected", "Dues", "Chandra"];
  dash.getRange(row, 1, 1, 8).setValues([momH]).setFontWeight("bold").setBackground("#C5CAE9");
  row++;

  const momRows = [];
  tabs.forEach(t => {
    const md = readMonthData(t.sheet);
    const mc = md.cash + md.upi;
    momRows.push([t.name, md.tenants, md.beds, md.cash, md.upi, mc, md.balance, md.chandra]);
  });

  if (momRows.length > 0) {
    dash.getRange(row, 1, momRows.length, 8).setValues(momRows);
    dash.getRange(row, 2, momRows.length, 7).setNumberFormat("#,##0").setHorizontalAlignment("right");
    for (let i = 0; i < momRows.length; i++) {
      dash.getRange(row + i, 1, 1, 8).setBackground(i % 2 === 0 ? "#FFFFFF" : "#F5F5F5");
    }
  }
  row += momRows.length + 1;

  // ── FOOTER ──
  dash.getRange(row, 1).setValue("Updated: " + new Date().toLocaleString("en-IN"))
    .setFontColor("#9E9E9E").setFontSize(9);

  // ── Column widths ──
  [160, 120, 120, 20, 160, 120, 120, 100].forEach((w, i) => dash.setColumnWidth(i + 1, w));

  SpreadsheetApp.getActive().toast("Dashboard refreshed!", "Done", 2);
}

// ── UPDATE MONTH SUMMARY (called on edit) ───────────────────────────────────

function updateMonthSummary(sheet) {
  const d = readMonthData(sheet);
  const collected = d.cash + d.upi;
  const vacant = TOTAL_BEDS - d.beds - d.noshow;
  const occPct = (d.beds / TOTAL_BEDS * 100).toFixed(1);
  const collPct = d.rentExpected > 0 ? (collected / d.rentExpected * 100).toFixed(1) : "0";

  sheet.getRange("A2:O2").setValues([[
    "Occupancy", d.beds + " beds (" + d.regular + "+" + d.premium + "P)",
    "No-show: " + d.noshow, "Vacant: " + vacant, "Occ: " + occPct + "%",
    "Cash", d.cash, "UPI", d.upi, "Total", collected,
    "Bal: " + d.balance, "Chandra: " + d.chandra, "Lakshmi: " + d.lakshmi, ""
  ]]);
  sheet.getRange("A3:O3").setValues([[
    "New check-ins", d.newCheckins, "Exits", d.exits,
    "PAID:" + d.paid, "PARTIAL:" + d.partial, "UNPAID:" + d.unpaid,
    "", "", "", "", "", "", "", ""
  ]]);

  // Recalculate Total Paid, Balance, Status for each data row
  // BUT preserve EXIT / NO SHOW / ADVANCE / CANCELLED statuses
  const data = sheet.getDataRange().getValues();
  for (let i = 4; i < data.length; i++) {
    if (!data[i][0]) continue;
    const curSt = String(data[i][9]).toUpperCase().trim();

    // Don't touch rows with special statuses
    if (curSt === "EXIT" || curSt === "NO SHOW" || curSt === "ADVANCE" || curSt === "CANCELLED") continue;

    const cash = pn(data[i][5]);
    const upi = pn(data[i][6]);
    const rent = pn(data[i][4]);
    const tp = cash + upi;
    const bal = rent - tp;
    const st = bal <= 0 ? "PAID" : (tp > 0 ? "PARTIAL" : "UNPAID");
    sheet.getRange(i + 1, 8).setValue(tp);
    sheet.getRange(i + 1, 9).setValue(bal);
    sheet.getRange(i + 1, 10).setValue(st);
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

  const tData = tenants.getDataRange().getValues();
  const sheet = ss.insertSheet(tabName);

  const headers = ["Room", "Name", "Building", "Sharing", "Rent Due",
    "Cash Paid", "UPI Paid", "Total Paid", "Balance", "Status",
    "Check-in", "Event", "Notes", "Chandra", "Lakshmi"];

  sheet.getRange("A1").setValue(tabName);
  sheet.getRange("A1:O1").merge().setFontSize(13).setFontWeight("bold");
  sheet.getRange("A2:O2").setValues([["Occupancy","","","","","Rent Expected",0,"Collected",0,"Outstanding",0,"","","",""]]);
  sheet.getRange("A3:O3").setValues([["New check-ins",0,"Exits",0,"","","","","","","","","","",""]]);
  sheet.getRange("A4:O4").setValues([headers]).setFontWeight("bold").setBackground("#D6EAF8");

  const daysInMonth = new Date(year, monthIdx + 1, 0).getDate();
  const mStart = new Date(year, monthIdx, 1);
  const mEnd = new Date(year, monthIdx, daysInMonth);

  // TENANTS cols: 0=Room,1=Name,2=Phone,3=Gender,4=Building,5=Floor,6=Sharing,7=Checkin,8=Status,9=MonthlyRent,10=CurrentRent
  const rows = [];
  for (let i = 1; i < tData.length; i++) {
    const t = tData[i];
    const status = String(t[8]).trim();
    if (status !== "Active" && status !== "No-show") continue;

    const rent = pn(t[10]) || pn(t[9]);
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

    rows.push([t[0], t[1], t[4], t[6], rentDue, 0, 0, 0, rentDue, "UNPAID", t[7], event, "", 0, 0]);
  }

  if (rows.length > 0) sheet.getRange(5, 1, rows.length, 15).setValues(rows);

  // Format
  sheet.setFrozenRows(4);
  sheet.getRange("E5:I" + (4 + rows.length)).setNumberFormat("#,##0");

  // Conditional formatting
  const sRange = sheet.getRange("J5:J" + (4 + rows.length));
  sheet.setConditionalFormatRules([
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("PAID").setBackground("#D5F5E3").setFontColor("#1E8449").setRanges([sRange]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("PARTIAL").setBackground("#FEF9E7").setFontColor("#B7950B").setRanges([sRange]).build(),
    SpreadsheetApp.newConditionalFormatRule().whenTextEqualTo("UNPAID").setBackground("#FDEDEC").setFontColor("#CB4335").setRanges([sRange]).build(),
  ]);

  sheet.getRange("A4:O" + (4 + rows.length)).createFilter();
  [70,180,70,80,100,100,100,100,100,80,100,120,200,80,80].forEach((w, i) => sheet.setColumnWidth(i + 1, w));

  updateMonthSummary(sheet);
}

function parseDate_(val) {
  if (!val) return null;
  const s = String(val).trim();
  const fmts = [/^(\d{2})-(\d{2})-(\d{4})$/, /^(\d{2})\/(\d{2})\/(\d{4})$/, /^(\d{4})-(\d{2})-(\d{2})$/];
  for (const f of fmts) {
    const m = s.match(f);
    if (m) {
      if (m[1].length === 4) return new Date(+m[1], +m[2]-1, +m[3]);
      else return new Date(+m[3], +m[2]-1, +m[1]);
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

    const hRent = pn(data[1][6]);  // Row 2, col G
    const hColl = pn(data[1][8]);  // Row 2, col I
    const calc = sumCash + sumUpi;

    if (Math.abs(hRent - sumRent) > 1) issues.push(sheet.getName() + ": Rent header " + hRent + " != rows " + sumRent);
    if (Math.abs(hColl - calc) > 1) issues.push(sheet.getName() + ": Collected header " + hColl + " != rows " + calc);
  });

  SpreadsheetApp.getUi().alert(issues.length === 0
    ? "All totals consistent!"
    : "Issues:\n\n" + issues.join("\n"));
}
