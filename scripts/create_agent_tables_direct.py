"""Direct asyncpg migration — bypasses SQLAlchemy pool entirely."""
import asyncio
import os
from dotenv import load_dotenv
load_dotenv()

async def main():
    import asyncpg

    raw_url = os.getenv("DATABASE_URL", "")
    # asyncpg needs postgres:// not postgresql+asyncpg://
    url = raw_url.replace("postgresql+asyncpg://", "postgresql://")

    print(f"Connecting to: {url[:40]}...")
    conn = await asyncio.wait_for(asyncpg.connect(url, timeout=10), timeout=15)
    print("Connected!")

    # Set statement timeout to prevent infinite hangs
    await conn.execute("SET statement_timeout = '10s'")

    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS property_config (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pg_name TEXT NOT NULL,
                brand_name TEXT,
                brand_voice TEXT,
                buildings JSONB,
                rooms JSONB,
                staff_rooms JSONB,
                staff JSONB,
                admin_phones JSONB,
                pricing JSONB,
                bank_config JSONB,
                expense_categories JSONB,
                custom_intents JSONB,
                business_rules JSONB,
                whatsapp_config JSONB,
                gsheet_config JSONB,
                timezone TEXT DEFAULT 'Asia/Kolkata',
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        print("1. property_config OK")
    except Exception as e:
        print(f"1. property_config FAILED: {e}")

    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS intent_examples (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pg_id UUID REFERENCES property_config(id),
                message_text TEXT NOT NULL,
                intent TEXT NOT NULL,
                role TEXT,
                entities JSONB,
                confidence FLOAT,
                source TEXT,
                confirmed_by TEXT,
                is_active BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMPTZ DEFAULT NOW(),
                updated_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS ix_intent_examples_pg_id ON intent_examples(pg_id)")
        await conn.execute("CREATE INDEX IF NOT EXISTS ix_intent_examples_intent ON intent_examples(intent)")
        print("2. intent_examples OK")
    except Exception as e:
        print(f"2. intent_examples FAILED: {e}")

    try:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS classification_log (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                pg_id UUID REFERENCES property_config(id),
                message_text TEXT,
                phone TEXT,
                role TEXT,
                regex_result TEXT,
                regex_confidence FLOAT,
                llm_result TEXT,
                llm_confidence FLOAT,
                final_intent TEXT,
                was_corrected BOOLEAN DEFAULT FALSE,
                corrected_to TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW()
            )
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS ix_classification_log_pg_id ON classification_log(pg_id)")
        print("3. classification_log OK")
    except Exception as e:
        print(f"3. classification_log FAILED: {e}")

    # Seed Cozeevo
    try:
        existing = await conn.fetchval("SELECT id FROM property_config WHERE pg_name = 'Cozeevo Co-living' LIMIT 1")
        if existing:
            print(f"4. Cozeevo already seeded, PG_ID: {existing}")
        else:
            await conn.execute("""
                INSERT INTO property_config (pg_name, brand_name, brand_voice, buildings, staff_rooms, admin_phones, pricing, expense_categories, business_rules)
                VALUES ($1, $2, $3, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb, $8::jsonb, $9::jsonb)
            """,
                'Cozeevo Co-living',
                'Cozeevo Help Desk',
                'You are Cozeevo Help Desk, a friendly and efficient AI assistant for Cozeevo Co-living PG in Chennai. Be concise, professional, and helpful.',
                '[{"name":"THOR","floors":7,"type":"male"},{"name":"HULK","floors":6,"type":"female"}]',
                '["G05","G06","107","108","701","702","G12","114","618"]',
                '["+917845952289","+917358341775","+919444296681"]',
                '{"sharing_3":7500,"sharing_2":9000,"single":12000,"single_ac":15000}',
                '["Electricity","Water","Salaries","Food","Furniture","Maintenance","IT","Internet","Gas","Property Rent","Police/Govt","Marketing","Shopping","Bank Charges","Housekeeping","Security","Insurance","Legal","Other"]',
                '{"proration":"first_month_standard_only","checkout_notice_day":5,"deposit_months":1,"billing_cycle":"monthly","checkout_full_month_charged":true}',
            )
            pg_id = await conn.fetchval("SELECT id FROM property_config WHERE pg_name = 'Cozeevo Co-living' LIMIT 1")
            print(f"4. Cozeevo seeded, PG_ID: {pg_id}")
    except Exception as e:
        print(f"4. Seed FAILED: {e}")

    await conn.close()
    print("Done!")

if __name__ == "__main__":
    asyncio.run(main())
