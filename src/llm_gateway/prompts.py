"""
All LLM prompt templates for PG Accountant.
Centralizing prompts avoids inline strings and makes it easy to tune costs.
"""

MERCHANT_CLASSIFY_PROMPT = """\
You are an accounting assistant for an Indian PG (paying guest) business.
Classify the transaction below into exactly ONE category from the list.

Categories:
{categories}

Transaction:
  Date: {date}
  Amount: ₹{amount}
  Type: {txn_type}
  Description: {description}
  Merchant: {merchant}

Respond in this exact JSON format (no markdown):
{{"category": "<category_name>", "confidence": <0.0-1.0>, "reason": "<one sentence>"}}
"""

INTENT_DETECT_PROMPT = """\
You are the AI assistant for a PG business accounting chatbot on WhatsApp.
Detect the intent from the user message below.

Valid intents:
- summary       : show summary / totals (monthly, weekly, daily)
- export        : export data as CSV or Excel
- rent_status   : who paid rent, pending rent
- expense_query : query expenses by category or vendor
- add_transaction: manually add income or expense
- help          : help / instructions
- unknown       : cannot determine

User message: "{message}"

Respond in this exact JSON format (no markdown):
{{
  "intent": "<intent>",
  "period": "<month_name|week|today|null>",
  "format": "<csv|excel|text|dashboard|null>",
  "category": "<category_name|null>",
  "entities": [],
  "confidence": <0.0-1.0>
}}
"""

CLARIFICATION_PROMPT = """\
You are an accounting assistant for an Indian PG business.
The user's message is ambiguous. Ask ONE short clarifying question in simple English.
Context: {context}
Message: "{message}"
What is unclear: {unclear}

Reply with a single short question only. No preamble.
"""

WHATSAPP_INTENT_PROMPT = """\
You are the AI assistant inside a WhatsApp chatbot for a PG (paying guest) accommodation business in India.
Your job is to read the user's message and return the correct intent + extracted entities in JSON.

Caller role: {role}

Valid intents for this role:
{intents}

User message: "{message}"

Extract these entities when present (use null if absent):
- name       : tenant/person name (e.g. "Jeevan", "Raj Kumar")
- room       : room number (e.g. "203", "G15", "508")
- amount     : numeric amount in INR (e.g. 15000, 8000)
- month      : month number 1-12 (e.g. March → 3, Feb → 2)
- date       : ISO date YYYY-MM-DD if a specific date is mentioned
- payment_mode : "cash" or "upi" if mentioned

Respond in this exact JSON format (no markdown, no extra text):
{{
  "intent": "<INTENT_NAME>",
  "confidence": <0.0-1.0>,
  "entities": {{
    "name": <string or null>,
    "room": <string or null>,
    "amount": <number or null>,
    "month": <number or null>,
    "date": <string or null>,
    "payment_mode": <string or null>
  }}
}}
"""

NEW_ENTITY_PROMPT = """\
A new {entity_type} was detected in a transaction but is not in the master data.

Transaction details:
  Date: {date}
  Amount: ₹{amount}
  Description: {description}
  Merchant/Party: {party}
  UPI ID: {upi_id}

Suggest master data fields to add this {entity_type} to the system.
Respond in this exact JSON format (no markdown):
{{
  "name": "<full name>",
  "phone": "<phone or null>",
  "upi_id": "<upi id or null>",
  "category": "<category if vendor or null>",
  "notes": "<any relevant notes>"
}}
"""
