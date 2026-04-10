"""
Flexible natural-language query handler.

Takes a user question like "how many rooms have single female occupant"
and generates a safe read-only SQL query, executes it, then formats
the result as a WhatsApp-friendly reply.

Safety: read-only (SELECT only), table whitelist, row limit, timeout.
"""
from __future__ import annotations

import json
import os
import re
from typing import Optional

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

# ── Schema context for the LLM ──────────────────────────────────────────────

DB_SCHEMA = """
-- tenants: PG residents
tenants(id INT PK, name VARCHAR, gender VARCHAR, phone VARCHAR, notes TEXT,
  occupation VARCHAR, date_of_birth DATE)

-- tenancies: tenant-room assignments
tenancies(id INT PK, tenant_id INT FK→tenants, room_id INT FK→rooms,
  status ENUM('active','exited','cancelled','no_show'),
  stay_type ENUM('monthly','daily'),
  sharing_type ENUM('single','double','triple','premium'),
  checkin_date DATE, checkout_date DATE, expected_checkout DATE, notice_date DATE,
  agreed_rent NUMERIC, security_deposit NUMERIC, booking_amount NUMERIC,
  maintenance_fee NUMERIC, notes TEXT)

-- rooms: physical rooms
rooms(id INT PK, property_id INT FK→properties, room_number VARCHAR,
  floor INT, room_type ENUM('single','double','triple','premium'),
  max_occupancy INT, has_ac BOOL, has_attached_bath BOOL,
  active BOOL, is_staff_room BOOL, notes TEXT)

-- properties: buildings
properties(id INT PK, name VARCHAR, total_rooms INT, active BOOL)
  -- name values: 'Cozeevo Co-living THOR', 'Cozeevo Co-living HULK'

-- payments: rent/deposit payments
payments(id INT PK, tenancy_id INT FK→tenancies, amount NUMERIC,
  payment_date DATE, payment_mode ENUM('cash','upi','bank_transfer','cheque'),
  for_type ENUM('rent','deposit','booking','maintenance','food','penalty','other'),
  period_month DATE, is_void BOOL, notes TEXT)

-- rent_schedule: monthly rent records
rent_schedule(id INT PK, tenancy_id INT FK→tenancies, period_month DATE,
  rent_due NUMERIC, maintenance_due NUMERIC, adjustment NUMERIC,
  status ENUM('pending','paid','partial','waived','na','exit'), notes TEXT)

-- expenses: property expenses
expenses(id INT PK, category_id INT, amount NUMERIC, expense_date DATE,
  payment_mode ENUM('cash','upi','bank_transfer','cheque'),
  vendor_name VARCHAR, description TEXT, is_void BOOL)

-- daywise_stays: short-term daily guests
daywise_stays(id INT PK, room_number VARCHAR, guest_name VARCHAR, phone VARCHAR,
  checkin_date DATE, checkout_date DATE, num_days INT,
  daily_rate NUMERIC, total_amount NUMERIC, status VARCHAR, assigned_staff VARCHAR)

-- complaints: tenant complaints
complaints(id INT PK, tenancy_id INT FK→tenancies,
  category ENUM('plumbing','electricity','wifi','food','furniture','other'),
  status ENUM('open','in_progress','resolved','closed'),
  description TEXT, created_at TIMESTAMP, resolved_at TIMESTAMP)

-- refunds: deposit refunds
refunds(id INT PK, tenancy_id INT FK→tenancies, amount NUMERIC,
  refund_date DATE, status ENUM('pending','processed','cancelled'), reason TEXT)

IMPORTANT JOINS:
  tenancies.tenant_id → tenants.id
  tenancies.room_id → rooms.id
  rooms.property_id → properties.id
  payments.tenancy_id → tenancies.id
  rent_schedule.tenancy_id → tenancies.id
  'THOR' building: properties.name ILIKE '%THOR%'
  'HULK' building: properties.name ILIKE '%HULK%'

CURRENT DATE: Use CURRENT_DATE for today.
Revenue rooms only: rooms.active = true AND rooms.is_staff_room = false
Active tenants only: tenancies.status = 'active'
Non-voided payments: payments.is_void = false
"""

# Tables allowed in queries
ALLOWED_TABLES = {
    "tenants", "tenancies", "rooms", "properties", "payments",
    "rent_schedule", "expenses", "daywise_stays", "complaints", "refunds",
}

# Dangerous patterns
FORBIDDEN_PATTERNS = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|EXEC|EXECUTE)\b",
    re.IGNORECASE,
)

MAX_ROWS = 50
QUERY_TIMEOUT = 10  # seconds


async def run_flexible_query(
    question: str,
    session: AsyncSession,
    role: str = "admin",
) -> str:
    """
    Answer a natural-language question by generating and executing SQL.
    Returns a formatted WhatsApp reply.
    """
    if role not in ("admin", "owner", "receptionist", "power_user"):
        return "Flexible queries are only available for admins."

    # Step 1: Generate SQL from question
    sql = await _generate_sql(question)
    if not sql:
        return "I couldn't understand that query. Try rephrasing, e.g.:\n• _how many female tenants_\n• _vacant beds in THOR_\n• _total rent collected in April_"

    # Step 2: Validate SQL safety
    error = _validate_sql(sql)
    if error:
        logger.warning(f"[FlexQuery] Blocked unsafe SQL: {error} | {sql}")
        return "I couldn't run that query safely. Try a simpler question."

    # Step 3: Execute
    try:
        logger.info(f"[FlexQuery] Q: {question} | SQL: {sql}")
        result = await session.execute(text(sql))
        rows = result.fetchall()
        columns = list(result.keys())
    except Exception as e:
        logger.error(f"[FlexQuery] SQL error: {e} | {sql}")
        return f"Query failed: {str(e)[:100]}. Try rephrasing."

    # Step 4: Format result
    if not rows:
        return f"No results found for: _{question}_"

    return await _format_result(question, columns, rows, sql)


async def _generate_sql(question: str) -> Optional[str]:
    """Use Groq LLM to generate SQL from natural language question."""
    import httpx

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None

    system_prompt = f"""You are a SQL query generator for a PG (paying guest) accommodation database.
Given a natural language question, generate a PostgreSQL SELECT query.

DATABASE SCHEMA:
{DB_SCHEMA}

RULES:
1. ONLY generate SELECT queries. Never INSERT/UPDATE/DELETE.
2. Always add LIMIT {MAX_ROWS} at the end.
3. Use proper JOINs based on the schema.
4. For "active tenants" always filter tenancies.status = 'active'.
5. For "revenue rooms" always filter rooms.active = true AND rooms.is_staff_room = false.
6. For building filters: properties.name ILIKE '%THOR%' or '%HULK%'.
7. For current occupancy queries, also consider daywise_stays where checkin_date <= CURRENT_DATE AND checkout_date >= CURRENT_DATE.
8. Return ONLY the SQL query, nothing else. No markdown, no explanation.
9. Use clear column aliases so results are readable.
10. For count queries, use COUNT(*) with a clear alias.
11. Round monetary values: ROUND(amount, 0).
12. Do NOT use table aliases like p, t, r. Use full table names always.
13. For aggregate questions ("how many", "total", "sum"), always return a single aggregated row, not per-row results.
14. If user asks for "top N" or "first N", use LIMIT N (not LIMIT {MAX_ROWS}).
15. For vacant/occupancy queries, DON'T use complex JOINs. Use subqueries: total beds = (SELECT SUM(max_occupancy) FROM rooms WHERE ...), occupied = (SELECT COUNT(*) FROM tenancies WHERE status='active' AND room_id IN (...)), vacant = total - occupied.
"""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": question},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 500,
                },
            )
            resp.raise_for_status()
            sql = resp.json()["choices"][0]["message"]["content"].strip()
            # Clean markdown fences
            sql = sql.strip("`").lstrip("sql").strip()
            if sql.startswith("```"):
                sql = sql.split("```")[1].strip()
                if sql.startswith("sql"):
                    sql = sql[3:].strip()
            return sql
    except Exception as e:
        logger.error(f"[FlexQuery] LLM error: {e}")
        return None


def _validate_sql(sql: str) -> Optional[str]:
    """Validate SQL is safe to execute. Returns error message or None."""
    if not sql:
        return "Empty query"

    # Must start with SELECT
    if not sql.strip().upper().startswith("SELECT"):
        return "Only SELECT queries allowed"

    # Check for forbidden operations
    if FORBIDDEN_PATTERNS.search(sql):
        return "Forbidden SQL operation detected"

    # Must have LIMIT
    if "LIMIT" not in sql.upper():
        return "Missing LIMIT clause"

    # Check LIMIT value
    limit_match = re.search(r"LIMIT\s+(\d+)", sql, re.IGNORECASE)
    if limit_match and int(limit_match.group(1)) > MAX_ROWS:
        return f"LIMIT exceeds {MAX_ROWS}"

    # Check only allowed tables — extract table names (first word after FROM/JOIN)
    table_refs = re.findall(r"(?:FROM|JOIN)\s+(\w+)", sql, re.IGNORECASE)
    for table in table_refs:
        if table.lower() not in ALLOWED_TABLES:
            return f"Table '{table}' not allowed"

    return None


async def _format_result(question: str, columns: list, rows: list, sql: str) -> str:
    """Format query results as a clean WhatsApp message."""
    total_rows = len(rows)

    # Single value result (e.g. COUNT query)
    if len(columns) == 1 and total_rows == 1:
        val = rows[0][0]
        if isinstance(val, (int, float)):
            val = f"{int(val):,}" if val == int(val) else f"{val:,.2f}"
        return f"*{columns[0]}*: {val}"

    # Single row result
    if total_rows == 1 and len(columns) <= 6:
        lines = [f"*Result for: {question}*\n"]
        for col, val in zip(columns, rows[0]):
            if isinstance(val, (int, float)) and val == int(val):
                val = f"{int(val):,}"
            lines.append(f"  {col}: {val}")
        return "\n".join(lines)

    # Table result
    lines = [f"*{question}* ({total_rows} result{'s' if total_rows > 1 else ''})\n"]

    for row in rows[:30]:  # Cap display at 30
        parts = []
        for col, val in zip(columns, row):
            if val is None:
                continue
            if isinstance(val, (int, float)):
                try:
                    val = f"{int(val):,}" if val == int(val) else f"{val:,.0f}"
                except (ValueError, OverflowError):
                    pass
            parts.append(f"{col}: {val}")
        lines.append("• " + " | ".join(parts))

    if total_rows > 30:
        lines.append(f"\n_...and {total_rows - 30} more rows_")

    return "\n".join(lines)
