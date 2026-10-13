# Spec 06 — Local AI models (replace Claude Haiku)

## Goal
No paid AI API on the product path. Receipt OCR, Aadhaar autofill and the WhatsApp intent
fallback run on our own server with small ONNX models. Kozzy will be sold to PG customers
who will not have Anthropic credit, so the stack must work without it.

## Design decisions
- **Server-side only.** WhatsApp traffic arrives at the server through Meta, and staff and
  tenant phones are mid-range Android. On-device or in-browser models were rejected.
- **VPS budget:** 1 vCPU, 3.8 GB RAM, no GPU. LLMs and VLMs don't fit; ONNX OCR and
  embeddings (100–300 MB each) do.
- **OCR:** `rapidocr-onnxruntime` (PP-OCRv4 mobile). One singleton, lazy load,
  `asyncio.Semaphore(1)` + threadpool.
- **Aadhaar:** decode the Secure QR with `zxing-cpp` first (signed by UIDAI, exact), then
  fall back to OCR. Check the 12-digit number with Verhoeff.
- **Intent:** `fastembed` + `paraphrase-multilingual-MiniLM-L12-v2`. Classify by
  nearest-neighbour vote over the labelled test sets. No LLM.
- **Kept on Groq** (free tier, text only): `manage_conversation`, `answer_from_logs`,
  form-edit replies, Whisper voice transcription.
- **Retired:** checkout-form photo over WhatsApp. Staff use the PWA checkout.
- **Env flags:** `OCR_BACKEND=haiku|local|shadow` and `INTENT_BACKEND=haiku|local|shadow`.
  Shadow runs both and logs the differences.
- Return shapes stay identical to today's Haiku functions, so callers don't change.

## Implementation
1. Dependencies: `rapidocr-onnxruntime`, `zxing-cpp`, `fastembed`. Add 2 GB swap on the VPS.
2. `src/services/local_ocr.py` — `ocr_lines(image_bytes) -> list[str]`.
3. `src/services/receipt_parse.py` — `parse_receipt(lines)`, which returns the keys
   `_claude_read_image` returns today. Wire into `receipt_handler.py` `_claude_read_image`,
   `payments.py` `_ocr_receipt_full` and `_ocr_transaction_id` (reuse, no second pass).
4. `src/services/aadhaar_extract.py` — `extract(image_bytes, side)`. Wire into
   `onboarding_router.py` `/extract-id`.
5. `scripts/build_intent_index.py` → `data/intent_index.npz` from `tests/scenarios_500.json`
   + `tests/edge_test_cases.json`. `tests/golden_test_cases.json` is held out.
6. `src/services/intent_embed.py` — `classify(text, role)`. Replace `_call_haiku` in
   `claude_client.detect_whatsapp_intent`.
7. Retire the image + CHECKOUT route (`chat_api.py`, `owner_handler.py`) with a fixed reply.
8. Once local is verified: remove the Anthropic code paths and `ANTHROPIC_API_KEY`, and update docs.

## Out of scope
- Voice transcription and the generative Groq paths.
- Removing dead code: the `form_extractor` tenant prompt, `claude_client.detect_intent`,
  `services/voice.py`, `services/intent_voice.py`.
- The broken PWA `/api/voice/*` calls.
- KYC rules and `name_match.py`.
- Any PWA UI change.

## Verification checklist
- [ ] Receipts: about 30 real screenshots (local, gitignored); at least 95% exact amounts;
      `tests/test_receipt_parse.py`
- [ ] Aadhaar: about 10 real cards; QR decode rate; Verhoeff; name match still enforced
- [ ] Intent: held-out golden accuracy at least the Haiku baseline (94.8%);
      `python tests/eval_golden.py`
- [ ] VPS: `free -h` after model load; OCR at most about 2 s per image; 1 week of shadow mode
- [ ] Anthropic usage dashboard shows zero calls after cutover
