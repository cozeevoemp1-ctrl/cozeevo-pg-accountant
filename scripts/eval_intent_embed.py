"""
Evaluate the local embedding intent classifier on the held-out golden set (spec 06).

    venv/Scripts/python scripts/eval_intent_embed.py                # local model only
    venv/Scripts/python scripts/eval_intent_embed.py --haiku        # + Claude Haiku baseline
    INTENT_EMBED_MODEL=minishlab/potion-multilingual-128M venv/Scripts/python scripts/eval_intent_embed.py

Golden messages are synthetic test inputs (no tenant data).
"""
import argparse
import asyncio
import os
import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from src.services import intent_embed as ie  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--haiku", action="store_true", help="also score Claude Haiku on the same set")
    ap.add_argument("--show", type=int, default=15, help="misses to print")
    args = ap.parse_args()

    train_labels = {(g, i) for _, g, i in ie.load_examples(ie.TRAIN_FILES)}
    rows = ie.load_examples([ie.HELDOUT_FILE])
    seen = [r for r in rows if (r[1], r[2]) in train_labels]
    print(f"model: {ie.MODEL_NAME}")
    print(f"held-out: {len(rows)} messages, {len(seen)} with a label present in training data")

    t0 = time.perf_counter()
    ie.classify("warmup", "admin")
    print(f"load + index: {time.perf_counter() - t0:.1f}s")

    t0 = time.perf_counter()
    preds = [ie.classify(t, g) for t, g, _ in rows]
    ms = (time.perf_counter() - t0) / len(rows) * 1000
    hits = [p["intent"] == i for p, (_, _, i) in zip(preds, rows)]
    hits_seen = [h for h, r in zip(hits, rows) if (r[1], r[2]) in train_labels]
    print(f"local: {sum(hits)}/{len(rows)} = {sum(hits)/len(rows):.1%} | "
          f"on seen labels {sum(hits_seen)}/{len(hits_seen)} = {sum(hits_seen)/max(len(hits_seen),1):.1%} | "
          f"{ms:.0f} ms/msg")

    # accuracy if we only trust the model above a confidence threshold
    for th in (0.4, 0.5, 0.6, 0.7):
        kept = [(h, p) for h, p in zip(hits, preds) if p["confidence"] >= th]
        if kept:
            print(f"  conf>={th}: answers {len(kept)}/{len(rows)}, accuracy {sum(h for h, _ in kept)/len(kept):.1%}")

    misses = [(r, p) for r, p, h in zip(rows, preds, hits) if not h]
    print("\nmisses (expected <- got @conf):")
    for (t, g, i), p in misses[: args.show]:
        print(f"  [{g}] {t[:60]!r}: {i} <- {p['intent']} @{p['confidence']}")
    print("most-missed expected labels:", Counter(i for (_, _, i), _ in misses).most_common(8))

    if args.haiku:
        from src.llm_gateway.claude_client import get_claude_client
        ai = get_claude_client()
        role_for = {"staff": "admin", "tenant": "tenant", "lead": "lead"}

        async def run():
            out = []
            for t, g, _ in rows:
                r = await ai.detect_whatsapp_intent(t, role_for[g])
                out.append(str(r.get("intent", "UNKNOWN")).upper())
            return out

        t0 = time.perf_counter()
        h = asyncio.run(run())
        ms = (time.perf_counter() - t0) / len(rows) * 1000
        hh = sum(a == r[2] for a, r in zip(h, rows))
        print(f"\nhaiku: {hh}/{len(rows)} = {hh/len(rows):.1%} | {ms:.0f} ms/msg")


if __name__ == "__main__":
    main()
