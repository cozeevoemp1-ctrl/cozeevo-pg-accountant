"""
tests/chat_harness.py
======================
Local test harness for the WhatsApp bot. Simulates a phone+message through
the same code path that the real FastAPI webhook uses, without any HTTP or
WhatsApp dependency. Supports chained multi-turn conversations (the reply
to one `send()` can be the setup for the next).

Usage:
    from tests.chat_harness import Session
    s = Session(phone="+917358341775")  # admin/power_user phone from .env
    reply = await s.send("room 112 paid rent")
    reply2 = await s.send("1")           # choose first tenant from disambig
    assert "Payment logged" in reply2

CLI:
    python tests/chat_harness.py                       # interactive REPL
    python tests/chat_harness.py --phone +91...        # use specific phone
"""
from __future__ import annotations

import asyncio
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))
# Reconfigure stdout AND stderr to UTF-8 — emoji in replies crashes cp1252 consoles
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
os.environ.setdefault("PYTHONIOENCODING", "utf-8")
os.makedirs("C:/tmp", exist_ok=True)  # Windows: /tmp/pg_*.log paths

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy import delete

from src.database.db_manager import init_engine, get_session
from src.database.models import PendingAction
from src.whatsapp.chat_api import InboundMessage, _process_message_inner


ADMIN_PHONE = os.getenv("ADMIN_PHONE", "+917845952289")
POWER_USER_PHONE = (os.getenv("POWER_USER_PHONES", "") or "").split(",")[0].strip() or ADMIN_PHONE


async def _boot() -> None:
    """Initialise the DB engine once per process."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL missing from .env")
    init_engine(url)


@dataclass
class Session:
    """One WhatsApp conversation. Remembers the phone so replies are stateful."""
    phone: str = POWER_USER_PHONE
    transcript: list[tuple[str, str]] = field(default_factory=list)

    async def clear_pending(self) -> None:
        """Wipe any leftover pending_actions for this phone — ensures tests start clean.
        Also deletes recent whatsapp_log entries to avoid cross-test pollution
        from the duplicate-log-prevention heuristic in chat_api (which reroutes
        PAYMENT_LOG → QUERY_EXPENSES if last reply said 'saved/logged' within 5 min).
        Clears BOTH the normalized and raw form to handle legacy rows."""
        from src.whatsapp.role_service import _normalize
        from src.database.models import WhatsappLog
        from datetime import datetime, timedelta
        normalized = _normalize(self.phone)
        cutoff = datetime.utcnow() - timedelta(minutes=10)
        async with get_session() as sess:
            await sess.execute(
                delete(PendingAction).where(
                    PendingAction.phone.in_([self.phone, normalized])
                )
            )
            # Purge recent whatsapp_log rows that match either phone format
            await sess.execute(
                delete(WhatsappLog).where(
                    WhatsappLog.from_number.in_([self.phone, normalized]),
                    WhatsappLog.created_at >= cutoff,
                )
            )
            await sess.execute(
                delete(WhatsappLog).where(
                    WhatsappLog.to_number.in_([self.phone, normalized]),
                    WhatsappLog.created_at >= cutoff,
                )
            )
            await sess.commit()

    async def send(self, message: str, media_id: Optional[str] = None,
                   media_type: Optional[str] = None) -> str:
        """Send one message, return bot reply text."""
        body = InboundMessage(
            phone=self.phone,
            message=message,
            message_id=f"harness-{uuid.uuid4().hex[:12]}",
            media_id=media_id,
            media_type=media_type,
        )
        async with get_session() as sess:
            reply = await _process_message_inner(body, sess)
        text = reply.reply if reply and not reply.skip else "<skip>"
        self.transcript.append(("user", message))
        self.transcript.append(("bot", text))
        return text

    def dump(self) -> str:
        out = []
        for who, txt in self.transcript:
            prefix = ">" if who == "user" else "<"
            out.append(f"{prefix} {txt}")
        return "\n".join(out)


async def _repl() -> None:
    """Interactive REPL — type messages, see bot replies."""
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--phone", default=POWER_USER_PHONE)
    p.add_argument("--clear", action="store_true", help="Clear pending_actions first")
    args = p.parse_args()

    await _boot()
    s = Session(phone=args.phone)
    if args.clear:
        await s.clear_pending()
        print(f"[cleared pending for {args.phone}]")

    print(f"Chat harness — phone: {args.phone}")
    print("Commands: /clear to wipe pending, /quit to exit, /dump to print transcript")
    while True:
        try:
            msg = input("> ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if not msg:
            continue
        if msg == "/quit":
            break
        if msg == "/clear":
            await s.clear_pending()
            print("[cleared]")
            continue
        if msg == "/dump":
            print(s.dump())
            continue
        try:
            reply = await s.send(msg)
            print(f"< {reply}")
        except Exception as e:
            print(f"[ERROR] {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(_repl())
