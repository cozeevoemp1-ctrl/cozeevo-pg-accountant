"""One-time script to create agent tables in Supabase."""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy import text

SQL_PROPERTY_CONFIG = """
CREATE TABLE IF NOT EXISTS property_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pg_name TEXT NOT NULL, brand_name TEXT, brand_voice TEXT,
    buildings JSONB, rooms JSONB, staff_rooms JSONB, staff JSONB,
    admin_phones JSONB, pricing JSONB, bank_config JSONB,
    expense_categories JSONB, custom_intents JSONB, business_rules JSONB,
    whatsapp_config JSONB, gsheet_config JSONB,
    timezone TEXT DEFAULT 'Asia/Kolkata',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

SQL_INTENT_EXAMPLES = """
CREATE TABLE IF NOT EXISTS intent_examples (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pg_id UUID REFERENCES property_config(id),
    message_text TEXT NOT NULL, intent TEXT NOT NULL, role TEXT,
    entities JSONB, confidence FLOAT, source TEXT, confirmed_by TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
)
"""

SQL_CLASSIFICATION_LOG = """
CREATE TABLE IF NOT EXISTS classification_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    pg_id UUID REFERENCES property_config(id),
    message_text TEXT, phone TEXT, role TEXT,
    regex_result TEXT, regex_confidence FLOAT,
    llm_result TEXT, llm_confidence FLOAT,
    final_intent TEXT, was_corrected BOOLEAN DEFAULT FALSE, corrected_to TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
)
"""

SQL_SEED = """
INSERT INTO property_config (pg_name, brand_name, brand_voice, buildings, staff_rooms, admin_phones, pricing, expense_categories, business_rules)
SELECT 'Cozeevo Co-living', 'Cozeevo Help Desk',
    'You are Cozeevo Help Desk, a friendly and efficient AI assistant for Cozeevo Co-living PG in Chennai. Be concise, professional, and helpful.',
    '[{"name":"THOR","floors":7,"type":"male"},{"name":"HULK","floors":6,"type":"female"}]'::jsonb,
    '["G05","G06","107","108","701","702","G12","114","618"]'::jsonb,
    '["+917845952289","+917358341775","+919444296681"]'::jsonb,
    '{"sharing_3":7500,"sharing_2":9000,"single":12000,"single_ac":15000}'::jsonb,
    '["Electricity","Water","Salaries","Food","Furniture","Maintenance","IT","Internet","Gas","Property Rent","Police/Govt","Marketing","Shopping","Bank Charges","Housekeeping","Security","Insurance","Legal","Other"]'::jsonb,
    '{"proration":"first_month_standard_only","checkout_notice_day":5,"deposit_months":1,"billing_cycle":"monthly","checkout_full_month_charged":true}'::jsonb
WHERE NOT EXISTS (SELECT 1 FROM property_config WHERE pg_name = 'Cozeevo Co-living')
"""


async def main():
    engine = create_async_engine(os.getenv("DATABASE_URL"), echo=False)
    async with engine.begin() as conn:
        await conn.execute(text(SQL_PROPERTY_CONFIG))
        print("1. property_config created")

        await conn.execute(text(SQL_INTENT_EXAMPLES))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_intent_examples_pg_id ON intent_examples(pg_id)"))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_intent_examples_intent ON intent_examples(intent)"))
        print("2. intent_examples created")

        await conn.execute(text(SQL_CLASSIFICATION_LOG))
        await conn.execute(text("CREATE INDEX IF NOT EXISTS ix_classification_log_pg_id ON classification_log(pg_id)"))
        print("3. classification_log created")

        await conn.execute(text(SQL_SEED))
        print("4. Cozeevo seeded")

        r = await conn.execute(text("SELECT id FROM property_config LIMIT 1"))
        row = r.fetchone()
        print(f"PG_ID: {row[0]}" if row else "ERROR: no rows")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
