"""
Local intent classifier — embeddings + nearest-neighbour vote (spec 06).

Replaces the Claude Haiku intent fallback with a small multilingual ONNX
embedding model that runs on the VPS CPU (no paid API, no network).

Training examples are the labelled bot test sets. The golden set is held out
for evaluation (scripts/eval_intent_embed.py) and never enters the index.

Index is built lazily on first use and cached to data/intent_index.npz;
it is rebuilt automatically when any source file is newer than the cache.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
TRAIN_FILES = [ROOT / "tests" / "scenarios_500.json", ROOT / "tests" / "edge_test_cases.json"]
HELDOUT_FILE = ROOT / "tests" / "golden_test_cases.json"
CACHE = ROOT / "data" / "intent_index.npz"

MODEL_NAME = os.getenv("INTENT_EMBED_MODEL", "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2")
TOP_K = 5

# Labels that describe conversation state, not a message's own intent.
_NON_INTENTS = {"CONFIRMATION", "CANCEL", "SELECT_OPTION", "PENDING", ""}

_lock = threading.Lock()
_model = None
_index: dict | None = None


def role_group(role: str) -> str:
    """Collapse bot roles into the three intent vocabularies."""
    role = (role or "").lower()
    if role == "tenant":
        return "tenant"
    if role == "lead":
        return "lead"
    return "staff"  # admin, owner, receptionist, power_user, key_user


def _first_turns(path: Path) -> list[tuple[str, str, str]]:
    """(text, role_group, intent) from a multi-turn case file — first turn only
    (later turns depend on pending state, not on the text alone)."""
    rows = []
    for case in json.loads(path.read_text(encoding="utf-8")):
        turns = case.get("turns") or []
        if turns:
            t = turns[0]
            rows.append((t.get("input", ""), role_group(t.get("role", "")), t.get("expected_intent", "")))
    return rows


def load_examples(paths: list[Path]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):  # scenarios_500.json: {"meta":…, "scenarios":[…]}
            for s in data.get("scenarios", []):
                rows.append((s.get("message", ""), role_group(s.get("role", "")), s.get("expected_intent", "")))
        else:
            rows += _first_turns(p)
    return [(t.strip(), g, i.upper()) for t, g, i in rows if t and t.strip() and i.upper() not in _NON_INTENTS]


def _get_model():
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding(MODEL_NAME)
        logger.info("[IntentEmbed] loaded %s", MODEL_NAME)
    return _model


def embed(texts: list[str]) -> np.ndarray:
    vecs = np.array(list(_get_model().embed([t.lower() for t in texts])), dtype=np.float32)
    return vecs / np.linalg.norm(vecs, axis=1, keepdims=True)


def _build() -> dict:
    rows = load_examples(TRAIN_FILES)
    texts, groups, labels = zip(*rows)
    idx = {"vecs": embed(list(texts)), "groups": np.array(groups), "labels": np.array(labels),
           "texts": np.array(texts), "model": np.array(MODEL_NAME)}
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(CACHE, **idx)
    logger.info("[IntentEmbed] built index: %d examples", len(rows))
    return idx


def _get_index() -> dict:
    global _index
    if _index is None:
        with _lock:
            if _index is None:
                fresh = (CACHE.exists()
                         and all(CACHE.stat().st_mtime >= p.stat().st_mtime for p in TRAIN_FILES))
                if fresh:
                    loaded = dict(np.load(CACHE))
                    fresh = str(loaded.get("model")) == MODEL_NAME
                _index = loaded if fresh else _build()
    return _index


def classify(text: str, role: str) -> dict:
    """Returns {"intent": str, "confidence": float, "neighbours": [(text, intent, sim)…]}.

    Confidence = similarity-weighted vote share of the winning intent among the
    top-k neighbours, scaled by the best neighbour's similarity.
    """
    idx = _get_index()
    mask = idx["groups"] == role_group(role)
    if not text.strip() or not mask.any():
        return {"intent": "UNKNOWN", "confidence": 0.0, "neighbours": []}
    vecs, labels, texts = idx["vecs"][mask], idx["labels"][mask], idx["texts"][mask]
    sims = vecs @ embed([text])[0]
    top = np.argsort(-sims)[:TOP_K]
    votes: dict[str, float] = {}
    for i in top:
        votes[labels[i]] = votes.get(labels[i], 0.0) + float(sims[i])
    best = max(votes, key=votes.get)
    share = votes[best] / sum(votes.values())
    conf = round(share * float(sims[top[0]]), 3)
    return {
        "intent": best,
        "confidence": conf,
        "neighbours": [(str(texts[i]), str(labels[i]), round(float(sims[i]), 3)) for i in top],
    }
