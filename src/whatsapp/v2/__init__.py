"""
src/whatsapp/v2/
────────────────
Artha v2 — LangGraph + Groq Supervisor Agent pipeline.

Every inbound WhatsApp message goes through:
    load_context → supervisor_classify → agent_executor → save_memory

Endpoint: POST /api/v2/whatsapp/process
Model:    Groq llama-3.1-70b-versatile

v1 at /api/whatsapp/process runs untouched alongside v2.
"""
