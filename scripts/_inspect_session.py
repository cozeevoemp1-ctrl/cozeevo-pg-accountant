"""Read-only: dump full onboarding session(s) for a tenancy_id or token.
Usage: python scripts/_inspect_session.py 1207 1199
"""
import asyncio
import json
import os
import sys

from dotenv import load_dotenv
from sqlalchemy import select, or_

load_dotenv()

from src.database.db_manager import init_db, get_session
from src.database.models import OnboardingSession


async def main(args):
    await init_db(os.environ["DATABASE_URL"])
    async with get_session() as session:
        tids = [int(a) for a in args if a.isdigit()]
        rows = (await session.execute(
            select(OnboardingSession).where(OnboardingSession.tenancy_id.in_(tids))
        )).scalars().all()
        for obs in rows:
            print(f"\n=== session tenancy_id={obs.tenancy_id} status={obs.status} ===")
            print(f"  created_at={obs.created_at} expires_at={obs.expires_at}")
            print(f"  completed_at={getattr(obs,'completed_at',None)} approved_at={obs.approved_at} approved_by={obs.approved_by_phone}")
            print(f"  id_doc_url={getattr(obs,'id_document_url',None)}")
            print(f"  agreement_url={getattr(obs,'agreement_url',None)}")
            td = json.loads(obs.tenant_data) if obs.tenant_data else {}
            print(f"  tenant_data keys: {sorted(td.keys())}")
            for k in ("name","phone","email","dob","address","permanent_address",
                      "id_type","id_number","emergency_contact","emergency_phone",
                      "occupation","signature","photo"):
                if k in td:
                    v = td[k]
                    v = (v[:40] + "…") if isinstance(v, str) and len(v) > 40 else v
                    print(f"      {k} = {v!r}")


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:] or ["1207", "1199"]))
