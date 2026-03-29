"""
Import WhatsApp chat exports into ActivityLog table.

Parses 3 chat files (~8900 messages), filters noise, classifies operational
messages via Groq, and inserts into Supabase activity_log with dedup.

Usage:
    python scripts/import_whatsapp_chats.py                # full run
    python scripts/import_whatsapp_chats.py --dry-run      # parse + classify, no DB write
    python scripts/import_whatsapp_chats.py --parse-only   # just parse, show stats
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import httpx
from loguru import logger

# ── Config ────────────────────────────────────────────────────────────────────

CHAT_FILES = [
    {
        "path": "data/whatsapp_chats/cozeevo_working/_chat.txt",
        "group": "working",
        "property": None,  # mixed THOR/HULK
    },
    {
        "path": "data/whatsapp_chats/cozeevo_partners/_chat.txt",
        "group": "partners",
        "property": None,
    },
    {
        "path": "WhatsApp Chat - Reception Updates (2)/_chat.txt",
        "group": "reception",
        "property": None,
    },
]

# Sender → short name + phone (for logged_by field)
SENDER_MAP = {
    "Paisanurture.in, CFP (Certified Financial Planner)": ("Kiran", "917845952289"),
    "Paisanurture.in": ("Kiran", "917845952289"),
    "Pk": ("PK", "917358341775"),
    "Gundoos": ("Gundoos", ""),
    "Prabhakaran Pemmasani": ("Prabhakaran", "919444296681"),
    "Akhil Reddy": ("Akhil", ""),
    "loki": ("Loki", ""),
    "Chandu Laksmis Brother": ("Chandu", ""),
    "Naresh Receptionist": ("Naresh", ""),
    "Cozeevo": ("Cozeevo", "917845952289"),  # Kiran's other account
}

# Messages that are pure noise — skip without sending to Groq
SKIP_PATTERNS = [
    r"^‎?Messages and calls are end-to-end",
    r"^‎?.+ created this group",
    r"^‎?.+ added .+",
    r"^‎?.+ left$",
    r"^‎?.+ removed .+",
    r"^‎?.+ changed the subject",
    r"^‎?.+ changed this group",
    r"^‎?.+ changed the group",
    r"^‎?You were added",
    r"^‎?Your security code",
    r"^‎?Waiting for this message",
    r"^‎?This message was deleted",
    r"^‎?You deleted this message",
    r"^‎?<This message was edited>$",
    r"^‎?null$",
    # Short replies (no operational value)
    r"^(ok|okay|okkk*|yes|yeah|yea|yep|no|nah|nope|hmm+|haa|ha|lol|😂|👍|👍🏻|🙏|ohh?|ah+|sure|done|noted|fine|good|great|nice|cool|alright|right|correct|perfect|true|hm+)\.?!?$",
    # Greetings
    r"^(hi|hello|hey|good\s*morning|good\s*night|good\s*evening|gm|gn|morning)\.?!?$",
    # Thank you
    r"^(thanks?|thank\s*you|ty|thx|thanku)\.?!?$",
]
SKIP_RE = [re.compile(p, re.IGNORECASE) for p in SKIP_PATTERNS]

# Photo/video only (no text) — skip
MEDIA_ONLY_RE = re.compile(r"^‎?<attached:\s*\S+>$")

# Extract text from text+media lines: "Iron <attached: 00000034-PHOTO...>"
MEDIA_STRIP_RE = re.compile(r"\s*‎?<attached:\s*\S+>\s*")

# Multiline continuation: lines that don't start with [date] belong to previous message
MSG_START_RE = re.compile(r"^‎?\[(\d{2}\.\d{2}\.\d{2}),\s*(\d{2}:\d{2}:\d{2})\]\s*(.+?):\s(.+)$", re.DOTALL)

# Room number extraction
ROOM_RE = re.compile(r"\b(?:room\s*(?:no\.?\s*)?)?([2-9]\d{2}[A-Za-z]?)\b", re.IGNORECASE)

# Amount extraction
AMOUNT_RE = re.compile(r"\b(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*(?:k\b|rs\.?|rupees?|/-|₹)?", re.IGNORECASE)
AMOUNT_K_RE = re.compile(r"\b(\d+(?:\.\d+)?)\s*k\b", re.IGNORECASE)

# Property detection
PROPERTY_RE = re.compile(r"\b(thor|hulk)\b", re.IGNORECASE)


# ── Step 1: Parse chat file ──────────────────────────────────────────────────

def parse_chat_file(filepath: str) -> list[dict]:
    """Parse WhatsApp chat export into structured messages."""
    root = Path(__file__).resolve().parent.parent
    full_path = root / filepath
    if not full_path.exists():
        logger.warning(f"Chat file not found: {full_path}")
        return []

    with open(full_path, "r", encoding="utf-8") as f:
        raw_lines = f.readlines()

    messages = []
    current = None

    for line in raw_lines:
        line = line.rstrip("\n")
        match = MSG_START_RE.match(line)
        if match:
            # Save previous message
            if current:
                messages.append(current)
            date_str, time_str, sender, text = match.groups()
            try:
                dt = datetime.strptime(f"{date_str} {time_str}", "%d.%m.%y %H:%M:%S")
            except ValueError:
                continue
            current = {
                "datetime": dt,
                "sender_raw": sender.strip(),
                "text": text.strip(),
            }
        elif current:
            # Continuation line — append to current message
            current["text"] += "\n" + line

    # Don't forget the last message
    if current:
        messages.append(current)

    return messages


# ── Step 2: Filter noise ────────────────────────────────────────────────────

def filter_messages(messages: list[dict]) -> tuple[list[dict], dict]:
    """Filter out system messages, media-only, short replies. Returns (kept, stats)."""
    stats = {"total": len(messages), "system": 0, "media_only": 0, "short_skip": 0, "kept": 0}
    kept = []

    for msg in messages:
        text = msg["text"].strip()
        # Remove BOM/invisible chars at start
        text = text.lstrip("\u200e").lstrip("\u200f").lstrip("\ufeff").strip()

        # Check if media-only (no text content)
        if MEDIA_ONLY_RE.match(text):
            stats["media_only"] += 1
            continue

        # Strip media attachment from text+media lines, keep the text
        text = MEDIA_STRIP_RE.sub("", text).strip()
        if not text:
            stats["media_only"] += 1
            continue

        # Strip "<This message was edited>" suffix
        text = text.replace("‎<This message was edited>", "").strip()
        if not text:
            stats["system"] += 1
            continue

        # Check skip patterns
        skip = False
        for pat in SKIP_RE:
            if pat.match(text):
                skip = True
                break
        if skip:
            stats["short_skip"] += 1
            continue

        # Skip very short messages (1-2 chars) unless they look like room numbers
        if len(text) <= 2 and not ROOM_RE.match(text):
            stats["short_skip"] += 1
            continue

        # Map sender
        sender_info = SENDER_MAP.get(msg["sender_raw"])
        if not sender_info:
            # Unknown sender — still keep, use raw name
            sender_info = (msg["sender_raw"], "")

        msg["text_clean"] = text
        msg["sender_name"] = sender_info[0]
        msg["sender_phone"] = sender_info[1]
        kept.append(msg)

    stats["kept"] = len(kept)
    return kept, stats


# ── Step 3: Classify with Groq ───────────────────────────────────────────────

# ── Regex-first classification (no API calls) ────────────────────────────────

# Pattern → (action, log_type)  — checked in order, first match wins
CLASSIFY_RULES: list[tuple[re.Pattern, str, str]] = [
    # SKIP patterns — casual chat, questions, opinions with no action
    (re.compile(r"^(which|what|where|when|how|why|who)\b.{0,60}\??$", re.I), "SKIP", ""),
    (re.compile(r"^(I think|I guess|I feel|maybe|probably|hopefully|I hope|I was|I am|I will|I have)\b.{0,40}$", re.I), "SKIP", ""),
    (re.compile(r"^(let me|let us|we should|we need to think|we can|can we|shall we|should we)\b.{0,40}$", re.I), "SKIP", ""),
    (re.compile(r"^@\u2068.+\u2069\s*$"), "SKIP", ""),  # just a mention, no text
    (re.compile(r"^(https?://\S+)$"), "SKIP", ""),  # bare URL only
    # Conversational / vague
    (re.compile(r"^(ya|yaa|yep|yup|nope|nah|haan|haa|accha|theek|thik|sahi|pata|bol|bolo|batao)\b", re.I), "SKIP", ""),
    (re.compile(r"^(she|he|they|it|that|this|those|these)\s+(is|are|was|were|will|can|has|have)\b.{0,30}$", re.I), "SKIP", ""),
    (re.compile(r"^(no\s*no|not\s*yet|not\s*now|not\s*sure|no\s*idea|no\s*problem|no\s*issue|will\s*do|will\s*check|coming|came|went|going|gone)\b.{0,20}$", re.I), "SKIP", ""),
    (re.compile(r"^(oh|ah|hmm|haha|lol|ok\s+mam|ok\s+sir|noted\s+sir|noted\s+mam|sure\s+sir|sure\s+mam|yes\s+sir|yes\s+mam)\b", re.I), "SKIP", ""),
    (re.compile(r"^(it'?s\s+(fine|good|ok|done|ready|working|fixed))\b", re.I), "SKIP", ""),
    (re.compile(r"^(already|don'?t|didn'?t|won'?t|can'?t|couldn'?t|isn'?t|wasn'?t)\b.{0,30}$", re.I), "SKIP", ""),

    # KEEP patterns — operational messages
    # Payments
    (re.compile(r"\b(paid|payment|received|collected|rent\s*-?\s*\d|deposit|advance|token|balance\s*\d|refund)", re.I), "KEEP", "payment"),
    # Maintenance
    (re.compile(r"\b(not working|broken|repair|fix|plumber|electrician|carpenter|leak|crack|damage|issue with|problem with|complaint|water\s*heater|geyser|ac\s*not|fan\s*not|light\s*not|wifi\s*not|internet\s*not|lift\s*not|generator|diesel|power\s*cut|power\s*back)", re.I), "KEEP", "maintenance"),
    # Purchases / Deliveries
    (re.compile(r"\b(order|ordered|delivered|bought|purchase|buy|bring|need to get|get\s+\d+|arrived|dispatched|received\s+\d+|quotation|quote|invoice|vendor|supplier)", re.I), "KEEP", "purchase"),
    (re.compile(r"\b(dispensers?|chairs?|tables?|mattress|bed|curtain|wardrobe|shoe\s*rack|fridge|tv|television|ac\s*unit|washing\s*machine|iron|carpet|mirror|pillow|blanket|towel|bucket|mop|broom)", re.I), "KEEP", "supply"),
    # Staff
    (re.compile(r"\b(receptionist|kitchen\s*master|cook|chef|cleaning|housekeep|security|guard|staff|salary|recruit|hire|resign|fired|absent|leave|joining|interview)", re.I), "KEEP", "staff"),
    # Utility
    (re.compile(r"\b(electricity|eb\s*bill|water\s*bill|water\s*tanker|internet\s*bill|wifi\s*bill|gas\s*bill|gas\s*cylinder|bescom|bwssb)", re.I), "KEEP", "utility"),
    # Checkout / Notice
    (re.compile(r"\b(vacat|checkout|check\s*out|leaving|moving\s*out|notice|last\s*day|shifting|relocat)", re.I), "KEEP", "checkout"),
    # Check-in / New tenant
    (re.compile(r"\b(check\s*in|checkin|move\s*in|new\s*tenant|new\s*guest|onboard|joining\s*date|move\s*in\s*date|rent\s*details)", re.I), "KEEP", "note"),
    # Complaints
    (re.compile(r"\b(noisy|noise|dirty|cockroach|pest|smell|stink|food\s*quality|bad\s*food|cold\s*food|unhygien)", re.I), "KEEP", "complaint"),
    # Tasks / Decisions / Instructions
    (re.compile(r"\b(please\s+(do|make|check|clean|call|ask|tell|send|update|enter|arrange|furnish|prepare|clear|turn))", re.I), "KEEP", "note"),
    (re.compile(r"\b(need to|needs to|have to|make sure|dont forget|don'?t forget|ensure|must\s+\w+|should\s+\w+\s+the)", re.I), "KEEP", "note"),
    (re.compile(r"\b(drill|install|paint|shift|move|clean|sweep|mop|furnish|arrange|set\s*up)\b", re.I), "KEEP", "maintenance"),
    # Room/bed related
    (re.compile(r"\b(room\s*\d{2,3}|bed\s*\d|vacant|occupied|available|empty\s*room|ready\s*the\s*room|keep\s*it\s*ready)", re.I), "KEEP", "note"),
    # Pricing / Rates
    (re.compile(r"\b(\d+k\b|\d{4,6}\s*(rent|per\s*month|monthly|deposit|maintenance|for\s+room))", re.I), "KEEP", "note"),
    # Leads / Visitors
    (re.compile(r"\b(lead|enquir|inquiry|foot\s*fall|walk\s*in|visitor|visit|prospect|show\s*room|tour)", re.I), "KEEP", "visitor"),
    # Excel / Records
    (re.compile(r"\b(update\s*(in\s*)?excel|enter\s*(in\s*)?excel|bill|receipt|invoice|write\s*a\s*bill)", re.I), "KEEP", "note"),
    # Food / Kitchen
    (re.compile(r"\b(breakfast|lunch|dinner|snack|food|menu|kitchen|cook|tiffin|mess|dining)", re.I), "KEEP", "note"),
    # Amounts mentioned (likely financial)
    (re.compile(r"\b\d+k\b|\b\d{4,6}\b.*\b(rs|rupee|paid|cost|price|charge|bill|total|amount)", re.I), "KEEP", "note"),
]

# Additional SKIP patterns for short/low-value messages
SKIP_SHORT_RE = [
    re.compile(r"^.{1,15}$"),  # Very short (under 15 chars) AND no keywords above matched
]


def classify_local(messages: list[dict]) -> tuple[list[dict], list[dict]]:
    """
    Classify messages using regex rules. Returns (classified, ambiguous).
    Ambiguous messages get sent to Groq.
    """
    classified = []
    ambiguous = []

    for msg in messages:
        text = msg["text_clean"]
        matched = False

        for pattern, action, log_type in CLASSIFY_RULES:
            if pattern.search(text):
                msg["action"] = action
                msg["log_type"] = log_type
                msg["room"] = _extract_room(text)
                msg["amount"] = _extract_amount(text)
                msg["property_name"] = _extract_property(text)
                classified.append(msg)
                matched = True
                break

        if not matched:
            # No keyword match — keep as note (Groq at query time handles context)
            # Short msgs without keywords are likely conversational → SKIP
            if len(text) < 40:
                msg["action"] = "SKIP"
                msg["log_type"] = ""
            else:
                msg["action"] = "KEEP"
                msg["log_type"] = "note"
                msg["room"] = _extract_room(text)
                msg["amount"] = _extract_amount(text)
                msg["property_name"] = _extract_property(text)
            classified.append(msg)

    return classified, ambiguous


# ── Groq for ambiguous messages only ─────────────────────────────────────────

CLASSIFY_PROMPT = """You are classifying WhatsApp messages from a PG (paying guest hostel) operations group.

For each message, decide:
1. Is it OPERATIONAL (purchases, maintenance, decisions, tasks, vendors, complaints, payments, check-ins, check-outs, pricing, staff issues, leads) or SKIP (casual chat, opinions with no action, personal chat, repeated info, vague messages)?
2. If OPERATIONAL, classify the log_type as one of: delivery, purchase, maintenance, utility, supply, staff, visitor, payment, complaint, checkout, note
3. Extract room number if mentioned (e.g., "301", "609", "502")
4. Extract amount if mentioned (e.g., "25000", "15k" = 15000, "2k" = 2000)
5. Extract property if mentioned (THOR or HULK)

Return a JSON array with one object per message:
{{"idx": 0, "action": "KEEP" or "SKIP", "log_type": "...", "room": null or "301", "amount": null or 25000, "property": null or "THOR"}}

Messages:
{messages}

Return ONLY the JSON array, no explanation."""

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"
BATCH_SIZE = 40  # larger batches since fewer messages now


async def classify_batch(messages: list[dict], batch_idx: int, api_key: str) -> list[dict]:
    """Send a batch of ambiguous messages to Groq for classification."""
    msg_text = "\n".join(
        f"[{i}] ({m['sender_name']}, {m['datetime'].strftime('%Y-%m-%d')}): {m['text_clean'][:200]}"
        for i, m in enumerate(messages)
    )

    prompt = CLASSIFY_PROMPT.format(messages=msg_text)
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 4096,
    }

    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(GROQ_URL, headers=headers, json=payload)
                if resp.status_code == 429:
                    wait = min(int(resp.headers.get("retry-after", 10)), 60)
                    logger.warning(f"Batch {batch_idx}: rate limited, waiting {wait}s")
                    await asyncio.sleep(wait)
                    continue
                resp.raise_for_status()
                content = resp.json()["choices"][0]["message"]["content"].strip()
                # Strip markdown fences
                content = content.lstrip("```json").lstrip("```").rstrip("```").strip()
                return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Batch {batch_idx}: JSON parse error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return [{"idx": i, "action": "KEEP", "log_type": "note", "room": None, "amount": None, "property": None} for i in range(len(messages))]
        except Exception as e:
            logger.warning(f"Batch {batch_idx}: error (attempt {attempt+1}): {e}")
            if attempt == 2:
                return [{"idx": i, "action": "KEEP", "log_type": "note", "room": None, "amount": None, "property": None} for i in range(len(messages))]
            await asyncio.sleep(3)

    return []


async def classify_all(messages: list[dict]) -> list[dict]:
    """Classify all messages using regex rules. No Groq needed at import time.
    Groq is used at QUERY time instead (smart activity queries)."""
    classified, _unused = classify_local(messages)
    keep = sum(1 for m in classified if m["action"] == "KEEP")
    skip = sum(1 for m in classified if m["action"] == "SKIP")
    logger.info(f"Classified: KEEP={keep} | SKIP={skip}")
    return classified


def _extract_room(text: str) -> Optional[str]:
    m = ROOM_RE.search(text)
    return m.group(1) if m else None


def _extract_amount(text: str) -> Optional[float]:
    # Check "Xk" first
    m = AMOUNT_K_RE.search(text)
    if m:
        return float(m.group(1)) * 1000
    # Check plain numbers > 100, cap at 10M (skip room number lists)
    for m in AMOUNT_RE.finditer(text):
        val = float(m.group(1).replace(",", ""))
        if 100 <= val <= 10_000_000:
            return val
    return None


def _extract_property(text: str) -> Optional[str]:
    m = PROPERTY_RE.search(text)
    return m.group(1).upper() if m else None


# ── Step 4: Insert into DB ──────────────────────────────────────────────────

def make_dedup_hash(dt: datetime, sender: str, text: str) -> str:
    """Same dedup logic as the live system."""
    key = f"{dt.strftime('%Y-%m-%d')}|{sender}|{text[:100].lower().strip()}"
    return hashlib.sha256(key.encode()).hexdigest()


async def insert_to_db(messages: list[dict], dry_run: bool = False) -> dict:
    """Insert classified messages into activity_log table using batch inserts."""
    from sqlalchemy import text as sql_text
    from src.database.db_manager import init_engine, get_session

    kept = [m for m in messages if m.get("action") == "KEEP"]
    stats = {"to_insert": len(kept), "inserted": 0, "duplicates": 0, "errors": 0}

    if dry_run:
        logger.info(f"DRY RUN: would insert {len(kept)} records")
        return stats

    # Init engine from env
    db_url = os.getenv("DATABASE_URL", "")
    if not db_url:
        logger.error("DATABASE_URL not set in .env")
        return stats

    init_engine(db_url)

    # Prepare all rows
    rows = []
    for msg in kept:
        dedup = make_dedup_hash(msg["datetime"], msg["sender_name"], msg["text_clean"])
        rows.append({
            "created_at": msg["datetime"],
            "logged_by": msg["sender_phone"] or msg["sender_name"],
            "log_type": msg.get("log_type", "note"),
            "room": msg.get("room"),
            "description": msg["text_clean"][:500],
            "amount": msg.get("amount"),
            "source": "chat_import",
            "property_name": msg.get("property_name"),
            "dedup_hash": dedup,
        })

    # Insert one by one with individual connections (avoid transaction cascade)
    BATCH = 50
    async with get_session() as session:
        for i in range(0, len(rows), BATCH):
            batch = rows[i:i+BATCH]
            for row in batch:
                try:
                    await session.execute(
                        sql_text("""
                            INSERT INTO activity_log
                            (created_at, logged_by, log_type, room, description, amount,
                             source, property_name, dedup_hash)
                            VALUES (:created_at, :logged_by, :log_type, :room, :description,
                                    :amount, :source, :property_name, :dedup_hash)
                        """),
                        row
                    )
                    stats["inserted"] += 1
                except Exception as e:
                    err_msg = str(e)
                    if "duplicate" in err_msg.lower() or "unique" in err_msg.lower():
                        stats["duplicates"] += 1
                    else:
                        stats["errors"] += 1
                        if stats["errors"] <= 5:
                            logger.warning(f"Insert error: {err_msg[:150]}")
                    # Rollback the failed statement so session stays usable
                    await session.rollback()

            # Commit after each batch
            await session.commit()
            done = min(i + BATCH, len(rows))
            logger.info(f"  DB progress: {done}/{len(rows)} (inserted: {stats['inserted']}, dup: {stats['duplicates']})")

    return stats


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Import WhatsApp chats to ActivityLog")
    parser.add_argument("--dry-run", action="store_true", help="Classify but don't insert")
    parser.add_argument("--parse-only", action="store_true", help="Only parse and show stats")
    args = parser.parse_args()

    all_messages = []
    for chat in CHAT_FILES:
        logger.info(f"\n{'='*60}")
        logger.info(f"Parsing: {chat['path']} ({chat['group']})")
        raw = parse_chat_file(chat["path"])
        filtered, stats = filter_messages(raw)
        # Tag with group
        for m in filtered:
            m["chat_group"] = chat["group"]
        all_messages.extend(filtered)
        logger.info(f"  Total: {stats['total']} | System: {stats['system']} | "
                     f"Media-only: {stats['media_only']} | Short: {stats['short_skip']} | "
                     f"Kept: {stats['kept']}")

    logger.info(f"\n{'='*60}")
    logger.info(f"TOTAL messages after filtering: {len(all_messages)}")

    if args.parse_only:
        # Show sample
        logger.info("\n--- Sample messages ---")
        for m in all_messages[:20]:
            logger.info(f"  [{m['datetime']}] {m['sender_name']}: {m['text_clean'][:80]}")
        return

    # Classify with Groq
    classified = await classify_all(all_messages)
    keep_count = sum(1 for m in classified if m.get("action") == "KEEP")
    skip_count = sum(1 for m in classified if m.get("action") == "SKIP")
    logger.info(f"\nClassification: KEEP={keep_count} | SKIP={skip_count}")

    # Show type breakdown
    from collections import Counter
    type_counts = Counter(m.get("log_type", "note") for m in classified if m.get("action") == "KEEP")
    logger.info("Log types: " + ", ".join(f"{t}={c}" for t, c in type_counts.most_common()))

    # Insert to DB
    db_stats = await insert_to_db(classified, dry_run=args.dry_run)
    logger.info(f"\nDB: inserted={db_stats['inserted']} | duplicates={db_stats['duplicates']} | errors={db_stats['errors']}")

    if not args.dry_run and db_stats["inserted"] > 0:
        logger.info(f"\nDone! {db_stats['inserted']} activity logs imported from WhatsApp chats.")
        logger.info("You can now query them: 'how many TVs do we need?' / 'what did Prabhakaran report?'")


if __name__ == "__main__":
    asyncio.run(main())
