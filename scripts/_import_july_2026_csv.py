"""One-off: import July 2026 THOR + HULK Yes Bank CSVs into bank_transactions.

Mirrors POST /finance/upload exactly (same parser, same _make_hash dedup, same
classifier, same post-import auto-reconcile + tenant-refund detection) — run
locally because the API needs a browser JWT. Idempotent: re-runs skip dups.

Run:  venv/Scripts/python scripts/_import_july_2026_csv.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.dialects.postgresql import insert as pg_insert

from src.database.db_manager import get_session, init_engine
init_engine(os.environ["DATABASE_URL"])

from src.api.v2.finance import _auto_reconcile, _detect_tenant_refunds, _make_hash
from src.database.models import BankTransaction, BankUpload
from src.parsers.yes_bank import read_yes_bank_csv
from src.rules.pnl_classify import classify_txn

FILES = [
    (r"data\uploads\csv\July thor csv.csv", "THOR"),
    (r"data\uploads\csv\July hulk CSV.csv", "HULK"),
]


async def main() -> None:
    async with get_session() as session:
        for path, account in FILES:
            rows = read_yes_bank_csv(path)
            if not rows:
                print(f"{account}: NO ROWS PARSED from {path}")
                continue
            upload = BankUpload(
                phone="script-july-import",
                file_path=path,
                row_count=len(rows),
                new_count=0,
                from_date=min(r[0] for r in rows),
                to_date=max(r[0] for r in rows),
                status="processed",
                account_name=account,
            )
            session.add(upload)
            await session.flush()

            new = dup = 0
            for txn_date, desc, txn_type, amount, balance in rows:
                norm_desc = (desc or "").strip()
                cat, sub = classify_txn(norm_desc, txn_type)
                stmt = (
                    pg_insert(BankTransaction)
                    .values(
                        upload_id=upload.id, txn_date=txn_date, description=norm_desc,
                        amount=amount, txn_type=txn_type, category=cat, sub_category=sub,
                        unique_hash=_make_hash(txn_date, amount, norm_desc),
                        account_name=account, balance=balance,
                    )
                    .on_conflict_do_nothing(index_elements=["unique_hash"])
                    .returning(BankTransaction.id)
                )
                if await session.scalar(stmt):
                    new += 1
                else:
                    dup += 1
            upload.new_count = new
            print(f"{account}: parsed {len(rows)} rows -> {new} new, {dup} dup "
                  f"({min(r[0] for r in rows)} .. {max(r[0] for r in rows)})")

        await _auto_reconcile(session)
        refunds = await _detect_tenant_refunds(session)
        print(f"tenant refunds auto-reclassified: {refunds}")
        await session.commit()


if __name__ == "__main__":
    asyncio.run(main())
