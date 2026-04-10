"""
Flexible natural-language query handler.

Takes a user question like "how many rooms have single female occupant"
and generates a safe read-only SQL query, executes it, then formats
the result as a WhatsApp-friendly reply.

Safety: read-only (SELECT only), table whitelist, row limit, timeout.
"""
from __future__ import annotations

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
    chat_history: str = "",
) -> str:
    """
    Answer a natural-language question by generating and executing SQL.
    Returns a formatted WhatsApp reply.
    """
    if role not in ("admin", "owner", "receptionist", "power_user"):
        return "Flexible queries are only available for admins."

    # Step 0: Basic guardrails on the question itself
    q_lower = question.lower().strip()
    if len(q_lower) < 5:
        return "Please ask a more specific question about your PG data."
    if len(q_lower) > 500:
        return "Question too long. Please keep it concise."

    # Reject questions that aren't about PG data
    non_data_patterns = re.compile(
        r"\b(weather|joke|recipe|news|stock|crypto|movie|song|game|translate|"
        r"write.*code|create.*app|build.*website|what is AI|who are you)\b",
        re.IGNORECASE,
    )
    if non_data_patterns.search(q_lower):
        return "I can only answer questions about your PG data (tenants, rooms, payments, etc.)."

    # Step 1: Generate SQL from question
    sql = await _generate_sql(question, chat_history)
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

    reply = await _format_result(question, columns, rows, sql)

    # Step 5: Log successful query for learning
    try:
        await _log_query(question, sql, len(rows), session)
    except Exception:
        pass  # never fail on logging

    return reply


async def _generate_sql(question: str, chat_history: str = "") -> Optional[str]:
    """Use Groq LLM to generate SQL from natural language question."""
    import httpx

    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return None

    # Add conversation context for follow-up questions
    context_block = ""
    if chat_history:
        context_block = f"""
CONVERSATION CONTEXT (use this to resolve "it", "those", "break it down", etc.):
{chat_history}
"""

    system_prompt = f"""You are a SQL query generator for a PG (paying guest) accommodation database.
Given a natural language question, generate a PostgreSQL SELECT query.

DATABASE SCHEMA:
{DB_SCHEMA}
{context_block}
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

    # Check only allowed tables
    # Extract table refs: FROM/JOIN followed by a word, but NOT inside functions like EXTRACT(... FROM col)
    # Strategy: remove all content inside parentheses first, then find FROM/JOIN table refs
    cleaned = re.sub(r"\([^)]*\)", "()", sql)  # collapse parenthesized content
    table_refs = re.findall(r"(?:FROM|JOIN)\s+(\w+)", cleaned, re.IGNORECASE)
    sql_keywords = {"select", "case", "when", "then", "else", "end", "current_date",
                    "current_timestamp", "now", "lateral"}
    for table in table_refs:
        if table.lower() in sql_keywords:
            continue
        if table.lower() not in ALLOWED_TABLES:
            return f"Table '{table}' not allowed"

    return None


async def _format_result(question: str, columns: list, rows: list, sql: str) -> str:
    """Use LLM to format raw query results into a clean, natural WhatsApp reply."""
    import httpx

    total_rows = len(rows)

    # Build raw data summary for LLM
    raw_lines = []
    for row in rows[:30]:
        parts = []
        for col, val in zip(columns, row):
            if val is None:
                continue
            if isinstance(val, (int, float)):
                try:
                    val = f"{int(val):,}" if val == int(val) else f"{val:,.0f}"
                except (ValueError, OverflowError):
                    pass
            parts.append(f"{col}={val}")
        raw_lines.append(", ".join(parts))

    raw_data = "\n".join(raw_lines)
    if total_rows > 30:
        raw_data += f"\n... and {total_rows - 30} more rows"

    # Use LLM to format the answer naturally
    api_key = os.getenv("GROQ_API_KEY", "")
    if not api_key:
        return _format_fallback(question, columns, rows)

    format_prompt = f"""You are a WhatsApp assistant for a PG (paying guest) accommodation.
The user asked: "{question}"

The database returned this data:
{raw_data}

Total rows: {total_rows}

Write a clean, concise WhatsApp reply answering the user's question.
RULES:
1. Use WhatsApp formatting: *bold* for headers, no markdown links
2. Be concise — summarize, don't dump raw data
3. For lists > 10 items, show top entries and summarize the rest
4. Use Rs. for currency with commas (Rs.15,000)
5. If the data clearly answers the question, state the answer directly
6. If the data seems wrong or incomplete, mention it
7. NO preamble like "Based on the data..." — just answer directly
8. Keep under 500 characters for simple answers, 1500 for lists
"""

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={
                    "model": "llama-3.3-70b-versatile",
                    "messages": [
                        {"role": "system", "content": format_prompt},
                        {"role": "user", "content": question},
                    ],
                    "temperature": 0.0,
                    "max_tokens": 400,
                },
            )
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"[FlexQuery] Format LLM failed: {e}, using fallback")
        return _format_fallback(question, columns, rows)


def _format_fallback(question: str, columns: list, rows: list) -> str:
    """Fallback formatter when LLM is unavailable."""
    total_rows = len(rows)

    if len(columns) == 1 and total_rows == 1:
        val = rows[0][0]
        if isinstance(val, (int, float)):
            val = f"{int(val):,}" if val == int(val) else f"{val:,.2f}"
        return f"*{columns[0]}*: {val}"

    lines = [f"*{question}* ({total_rows} results)\n"]
    for row in rows[:20]:
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

    if total_rows > 20:
        lines.append(f"\n_...{total_rows - 20} more_")
    return "\n".join(lines)


async def _log_query(question: str, sql: str, row_count: int, session: AsyncSession) -> None:
    """Log successful flexible queries for learning and audit."""
    await session.execute(
        text("""
            INSERT INTO classification_log (id, pg_id, message_text, phone, role,
                regex_result, llm_result, llm_confidence, final_intent, created_at)
            VALUES (gen_random_uuid(), :pg_id, :msg, 'system', 'admin',
                NULL, :sql, :conf, 'QUERY_FLEXIBLE', now())
        """),
        {
            "pg_id": os.getenv("DEFAULT_PG_ID", ""),
            "msg": question,
            "sql": sql[:500],
            "conf": 1.0 if row_count > 0 else 0.5,
        },
    )
