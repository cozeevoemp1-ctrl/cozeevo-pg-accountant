"""
Manual scripted conversation — exercises the whole demo flow (pricing,
availability, visit booking) via handle_demo_message() directly, with no
WhatsApp/Meta involved. Useful to sanity-check the bot before wiring up the
real test number.

Usage:
    py -3 -m demo.havenly_stays.seed
    py -3 -m demo.havenly_stays.test_conversation
"""
from __future__ import annotations

import asyncio

from demo.havenly_stays.db import init_db
from demo.havenly_stays.handler import handle_demo_message

PHONE = "917845952289"

SCRIPT = [
    "hi",
    "what are your prices?",
    "single",
    "is a room available from september?",
    "I'd like to book a visit",
    "Kiran",
    "kiran.test@example.com",
    "28 august 4pm",
    "yes",
]


async def main():
    await init_db()
    for turn in SCRIPT:
        reply = await handle_demo_message(PHONE, turn)
        print(f"> {turn}")
        print(f"< {reply}\n")


if __name__ == "__main__":
    asyncio.run(main())
