# Voice Onboarding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a mic button to `/onboarding/new` that lets Lokesh speak tenant details naturally, uses Groq LLM to extract all form fields, speaks a confirmation back via OpenAI TTS, and pre-fills the form — with multi-turn support for missing fields.

**Architecture:** Pure client-side. `OnboardingVoiceSheet` component manages the multi-turn state machine (recording → extracting → speaking → confirm). `lib/parse-onboarding.ts` calls Groq LLM with the transcript + already-captured fields and returns merged fields + a natural confirmation sentence. `lib/tts.ts` calls OpenAI TTS and plays the audio, falling back to browser `speechSynthesis`. No backend changes.

**Tech Stack:** Next.js 15, React 18, Vitest + jsdom, browser SpeechRecognition API (existing `useSpeechInput` hook), Groq REST API (`llama-3.3-70b-versatile`), OpenAI REST API (`tts-1`, voice `nova`)

---

## File Map

| File | Action | Responsibility |
|------|--------|----------------|
| `web/.env.local` | Edit | Add `NEXT_PUBLIC_GROQ_API_KEY` + `NEXT_PUBLIC_OPENAI_API_KEY` |
| `web/.env.local.example` | Edit | Same keys, no values |
| `web/lib/parse-onboarding.ts` | Create | Groq LLM extraction — types + `parseOnboardingFields()` |
| `web/lib/tts.ts` | Create | OpenAI TTS + browser fallback — `speakText()` |
| `web/lib/__tests__/parse-onboarding.test.ts` | Create | Unit tests for extraction (mocked fetch) |
| `web/lib/__tests__/tts.test.ts` | Create | Unit tests for TTS (mocked fetch + Audio) |
| `web/components/voice/onboarding-voice-sheet.tsx` | Create | Bottom sheet component — multi-turn state machine |
| `web/app/onboarding/new/page.tsx` | Edit | Mic button in header + wire `OnboardingVoiceSheet` |

---

## Task 1: Environment variables

**Files:**
- Edit: `web/.env.local`
- Edit: `web/.env.local.example`

- [ ] **Step 1: Add keys to `.env.local`**

Open `web/.env.local` and add these two lines at the end:

```
NEXT_PUBLIC_GROQ_API_KEY=<your-groq-api-key>
NEXT_PUBLIC_OPENAI_API_KEY=<your-openai-api-key>
```

The Groq key is the same value as the server-side `GROQ_API_KEY` already in `/opt/pg-accountant/.env` on VPS. Get the OpenAI key from platform.openai.com → API keys.

- [ ] **Step 2: Add placeholder keys to `.env.local.example`**

Open `web/.env.local.example` and add:

```
NEXT_PUBLIC_GROQ_API_KEY=
NEXT_PUBLIC_OPENAI_API_KEY=
```

- [ ] **Step 3: Commit**

```bash
cd web
git add .env.local.example
git commit -m "chore: add NEXT_PUBLIC_GROQ_API_KEY + NEXT_PUBLIC_OPENAI_API_KEY env vars"
```

(Do NOT git add `.env.local` — it has real keys.)

---

## Task 2: `lib/parse-onboarding.ts` — types + Groq extraction

**Files:**
- Create: `web/lib/parse-onboarding.ts`

- [ ] **Step 1: Create the file with types and the extraction function**

Create `web/lib/parse-onboarding.ts`:

```typescript
const GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"

export interface OnboardingFields {
  room_number: string | null
  sharing_type: string | null
  tenant_phone: string | null
  checkin_date: string | null
  monthly_rent: number | null
  security_deposit: number | null
  maintenance_fee: number | null
  booking_amount: number | null
  advance_mode: string | null
  lock_in_months: number | null
  future_rent: number | null
  future_rent_after_months: number | null
}

export interface OnboardingParseResult {
  fields: OnboardingFields
  confirmation: string
  missing: string[]
}

export function emptyOnboardingFields(): OnboardingFields {
  return {
    room_number: null, sharing_type: null, tenant_phone: null,
    checkin_date: null, monthly_rent: null, security_deposit: null,
    maintenance_fee: null, booking_amount: null, advance_mode: null,
    lock_in_months: null, future_rent: null, future_rent_after_months: null,
  }
}

function buildPrompt(transcript: string, existing: OnboardingFields): string {
  const today = new Date().toISOString().slice(0, 10)
  return `You are a helpful PG receptionist assistant for Kozzy co-living.

Today's date: ${today}
Already captured: ${JSON.stringify(existing)}

Receptionist just said: "${transcript}"

Extract or update any of these fields:
- room_number (string, e.g. "101", "G20")
- sharing_type ("single", "double", "triple", or "premium")
- tenant_phone (string, 10-digit Indian mobile, no country code)
- checkin_date (string, ISO date YYYY-MM-DD, default to today if not mentioned)
- monthly_rent (number in rupees, convert "k" = 1000, "lakh" = 100000)
- security_deposit (number in rupees)
- maintenance_fee (number in rupees/month)
- booking_amount (number in rupees advance paid now)
- advance_mode ("cash", "upi", or "bank")
- lock_in_months (number)
- future_rent (number in rupees, if a rent increase is mentioned)
- future_rent_after_months (number of months before increase kicks in)

Rules:
- Keep existing field values unless the new speech explicitly changes them
- Use null for fields not yet mentioned
- Write a short natural confirmation (2 sentences max) of what was captured and what is still missing. Sound like a helpful human assistant, not a robot.
- All monetary values must be numbers in rupees (e.g. "12k" → 12000)

Return ONLY valid JSON with this exact shape:
{"fields": {...}, "confirmation": "...", "missing": ["field1", ...]}`
}

export async function parseOnboardingFields(
  transcript: string,
  existing: OnboardingFields
): Promise<OnboardingParseResult> {
  const key = process.env.NEXT_PUBLIC_GROQ_API_KEY
  if (!key) throw new Error("NEXT_PUBLIC_GROQ_API_KEY is not set")

  const res = await fetch(GROQ_URL, {
    method: "POST",
    headers: {
      "Authorization": `Bearer ${key}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      model: "llama-3.3-70b-versatile",
      messages: [{ role: "user", content: buildPrompt(transcript, existing) }],
      response_format: { type: "json_object" },
      temperature: 0.1,
    }),
  })

  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new Error(`Groq API error ${res.status}: ${body}`)
  }

  const data = await res.json() as { choices: { message: { content: string } }[] }
  const parsed = JSON.parse(data.choices[0].message.content) as OnboardingParseResult
  return parsed
}
```

- [ ] **Step 2: Commit**

```bash
cd web
git add lib/parse-onboarding.ts
git commit -m "feat(voice): add parseOnboardingFields — Groq LLM extraction"
```

---

## Task 3: Unit tests for `parse-onboarding.ts`

**Files:**
- Create: `web/lib/__tests__/parse-onboarding.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `web/lib/__tests__/parse-onboarding.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest"
import { parseOnboardingFields, emptyOnboardingFields } from "../parse-onboarding"

function mockGroqResponse(result: object) {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: true,
    json: async () => ({
      choices: [{ message: { content: JSON.stringify(result) } }]
    }),
  }))
}

describe("parseOnboardingFields", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    process.env.NEXT_PUBLIC_GROQ_API_KEY = "test-key"
  })

  it("returns extracted fields and confirmation", async () => {
    mockGroqResponse({
      fields: {
        ...emptyOnboardingFields(),
        room_number: "201",
        tenant_phone: "9876543210",
        monthly_rent: 12000,
      },
      confirmation: "Got it — room 201, phone 9876543210, rent 12,000. Still need deposit.",
      missing: ["security_deposit", "maintenance_fee"],
    })

    const result = await parseOnboardingFields(
      "room 201 phone 9876543210 rent 12k",
      emptyOnboardingFields()
    )

    expect(result.fields.room_number).toBe("201")
    expect(result.fields.tenant_phone).toBe("9876543210")
    expect(result.fields.monthly_rent).toBe(12000)
    expect(result.confirmation).toContain("room 201")
    expect(result.missing).toContain("security_deposit")
  })

  it("preserves existing fields not mentioned in new speech", async () => {
    const existing = {
      ...emptyOnboardingFields(),
      room_number: "101",
      monthly_rent: 10000,
    }
    mockGroqResponse({
      fields: { ...existing, security_deposit: 15000 },
      confirmation: "Added deposit 15,000. Room 101, rent 10,000 already captured.",
      missing: ["tenant_phone"],
    })

    const result = await parseOnboardingFields("deposit 15k", existing)

    expect(result.fields.room_number).toBe("101")
    expect(result.fields.monthly_rent).toBe(10000)
    expect(result.fields.security_deposit).toBe(15000)
  })

  it("throws when NEXT_PUBLIC_GROQ_API_KEY is missing", async () => {
    delete process.env.NEXT_PUBLIC_GROQ_API_KEY
    await expect(
      parseOnboardingFields("room 101", emptyOnboardingFields())
    ).rejects.toThrow("NEXT_PUBLIC_GROQ_API_KEY is not set")
  })

  it("throws on non-ok Groq response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 429,
      text: async () => "rate limited",
    }))

    await expect(
      parseOnboardingFields("room 101", emptyOnboardingFields())
    ).rejects.toThrow("Groq API error 429")
  })
})
```

- [ ] **Step 2: Run tests — expect them to pass**

```bash
cd web && npx vitest run lib/__tests__/parse-onboarding.test.ts
```

Expected: 4 tests pass. (The function is already implemented in Task 2.)

- [ ] **Step 3: Commit**

```bash
cd web
git add lib/__tests__/parse-onboarding.test.ts
git commit -m "test(voice): unit tests for parseOnboardingFields"
```

---

## Task 4: `lib/tts.ts` — OpenAI TTS + fallback

**Files:**
- Create: `web/lib/tts.ts`

- [ ] **Step 1: Create the file**

Create `web/lib/tts.ts`:

```typescript
const TTS_URL = "https://api.openai.com/v1/audio/speech"

export async function speakText(text: string): Promise<void> {
  const key = process.env.NEXT_PUBLIC_OPENAI_API_KEY
  if (!key) {
    browserSpeak(text)
    return
  }

  try {
    const res = await fetch(TTS_URL, {
      method: "POST",
      headers: {
        "Authorization": `Bearer ${key}`,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ model: "tts-1", voice: "nova", input: text }),
    })
    if (!res.ok) throw new Error(`TTS error ${res.status}`)

    const blob = await res.blob()
    const url = URL.createObjectURL(blob)
    const audio = new Audio(url)
    audio.onended = () => URL.revokeObjectURL(url)
    await audio.play()
  } catch {
    browserSpeak(text)
  }
}

function browserSpeak(text: string): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return
  const utterance = new SpeechSynthesisUtterance(text)
  utterance.lang = "en-IN"
  window.speechSynthesis.cancel()
  window.speechSynthesis.speak(utterance)
}
```

- [ ] **Step 2: Commit**

```bash
cd web
git add lib/tts.ts
git commit -m "feat(voice): add speakText — OpenAI TTS with browser fallback"
```

---

## Task 5: Unit tests for `tts.ts`

**Files:**
- Create: `web/lib/__tests__/tts.test.ts`

- [ ] **Step 1: Write the tests**

Create `web/lib/__tests__/tts.test.ts`:

```typescript
import { describe, it, expect, vi, beforeEach } from "vitest"
import { speakText } from "../tts"

describe("speakText", () => {
  beforeEach(() => {
    vi.unstubAllGlobals()
    process.env.NEXT_PUBLIC_OPENAI_API_KEY = "test-key"
  })

  it("calls OpenAI TTS and plays audio on success", async () => {
    const mockBlob = new Blob(["audio"], { type: "audio/mpeg" })
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      blob: async () => mockBlob,
    }))

    const mockPlay = vi.fn().mockResolvedValue(undefined)
    const mockAudio = { onended: null as unknown, play: mockPlay }
    vi.stubGlobal("Audio", vi.fn().mockReturnValue(mockAudio))
    vi.stubGlobal("URL", { createObjectURL: vi.fn().mockReturnValue("blob:test"), revokeObjectURL: vi.fn() })

    await speakText("Got it, room 201.")

    expect(fetch).toHaveBeenCalledWith(
      "https://api.openai.com/v1/audio/speech",
      expect.objectContaining({ method: "POST" })
    )
    expect(mockPlay).toHaveBeenCalled()
  })

  it("falls back to browser speechSynthesis when OpenAI fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 500 }))

    const mockSpeak = vi.fn()
    vi.stubGlobal("window", {
      speechSynthesis: { speak: mockSpeak, cancel: vi.fn() },
    })
    vi.stubGlobal("SpeechSynthesisUtterance", vi.fn().mockReturnValue({}))

    await speakText("Fallback test.")

    expect(mockSpeak).toHaveBeenCalled()
  })

  it("uses browser fallback when NEXT_PUBLIC_OPENAI_API_KEY is missing", async () => {
    delete process.env.NEXT_PUBLIC_OPENAI_API_KEY

    const mockSpeak = vi.fn()
    vi.stubGlobal("window", {
      speechSynthesis: { speak: mockSpeak, cancel: vi.fn() },
    })
    vi.stubGlobal("SpeechSynthesisUtterance", vi.fn().mockReturnValue({}))

    await speakText("No key test.")

    expect(mockSpeak).toHaveBeenCalled()
  })
})
```

- [ ] **Step 2: Run tests — expect them to pass**

```bash
cd web && npx vitest run lib/__tests__/tts.test.ts
```

Expected: 3 tests pass.

- [ ] **Step 3: Commit**

```bash
cd web
git add lib/__tests__/tts.test.ts
git commit -m "test(voice): unit tests for speakText TTS"
```

---

## Task 6: `OnboardingVoiceSheet` component

**Files:**
- Create: `web/components/voice/onboarding-voice-sheet.tsx`

- [ ] **Step 1: Create the component**

Create `web/components/voice/onboarding-voice-sheet.tsx`:

```typescript
"use client"

import { useEffect, useRef, useState } from "react"
import { useSpeechInput } from "@/lib/voice"
import {
  parseOnboardingFields,
  emptyOnboardingFields,
  type OnboardingFields,
  type OnboardingParseResult,
} from "@/lib/parse-onboarding"
import { speakText } from "@/lib/tts"

interface OnboardingVoiceSheetProps {
  onClose: () => void
  onConfirm: (fields: OnboardingFields) => void
}

type SheetStep = "recording" | "extracting" | "speaking" | "confirm" | "error"

const REQUIRED: (keyof OnboardingFields)[] = ["room_number", "tenant_phone", "monthly_rent"]

const FIELD_LABELS: Record<string, string> = {
  room_number: "Room",
  sharing_type: "Sharing",
  tenant_phone: "Phone",
  checkin_date: "Check-in",
  monthly_rent: "Rent (₹/mo)",
  security_deposit: "Deposit (₹)",
  maintenance_fee: "Maintenance (₹/mo)",
  booking_amount: "Booking advance (₹)",
  advance_mode: "Advance via",
  lock_in_months: "Lock-in (months)",
  future_rent: "Future rent (₹)",
  future_rent_after_months: "Increase after (months)",
}

const MONEY_FIELDS = new Set([
  "monthly_rent", "security_deposit", "maintenance_fee",
  "booking_amount", "future_rent",
])

function formatValue(key: string, value: unknown): string {
  if (MONEY_FIELDS.has(key)) return `₹${Number(value).toLocaleString("en-IN")}`
  return String(value)
}

export function OnboardingVoiceSheet({ onClose, onConfirm }: OnboardingVoiceSheetProps) {
  const speech = useSpeechInput()
  const [step, setStep] = useState<SheetStep>("recording")
  const [partialFields, setPartialFields] = useState<OnboardingFields>(emptyOnboardingFields())
  const [parseResult, setParseResult] = useState<OnboardingParseResult | null>(null)
  const [errorMsg, setErrorMsg] = useState("")
  const startedRef = useRef(false)

  useEffect(() => {
    if (!startedRef.current) {
      startedRef.current = true
      speech.start()
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => {
    if (speech.state === "stopped" && speech.transcript) {
      handleExtract(speech.transcript)
    }
    if (speech.state === "error" || speech.state === "unsupported") {
      setErrorMsg(speech.error ?? "Microphone error — check permissions.")
      setStep("error")
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [speech.state])

  async function handleExtract(transcript: string) {
    setStep("extracting")
    try {
      const result = await parseOnboardingFields(transcript, partialFields)
      setPartialFields(result.fields)
      setParseResult(result)
      setStep("speaking")
      await speakText(result.confirmation)
      setStep("confirm")
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Parsing failed — try again.")
      setStep("error")
    }
  }

  function handleRecordAgain() {
    speech.reset()
    startedRef.current = true
    setStep("recording")
    speech.start()
  }

  const requiredMet = REQUIRED.every((k) => partialFields[k] !== null)

  return (
    <div className="fixed inset-0 z-50 bg-black/60 flex items-end">
      <div className="w-full bg-surface rounded-t-3xl px-5 pt-5 pb-10 min-h-[65vh] flex flex-col max-h-[90vh] overflow-y-auto">
        <div className="w-12 h-1 bg-[#E2DEDD] rounded-full mx-auto mb-5 flex-shrink-0" />

        {step === "recording" && (
          <RecordingView
            state={speech.state}
            hasPartial={Object.values(partialFields).some((v) => v !== null)}
            onStop={() => speech.stop()}
            onCancel={onClose}
          />
        )}

        {(step === "extracting" || step === "speaking") && (
          <ProcessingView label={step === "extracting" ? "Understanding…" : "Confirming details…"} />
        )}

        {step === "confirm" && parseResult && (
          <ConfirmView
            fields={partialFields}
            missing={parseResult.missing}
            requiredMet={requiredMet}
            onRecordAgain={handleRecordAgain}
            onConfirm={() => onConfirm(partialFields)}
            onCancel={onClose}
          />
        )}

        {step === "error" && (
          <ErrorView
            message={errorMsg}
            onRetry={handleRecordAgain}
            onClose={onClose}
          />
        )}
      </div>
    </div>
  )
}

// ── Sub-views ───────────────────────────────────────────────────────────────

function RecordingView({
  state, hasPartial, onStop, onCancel,
}: {
  state: string; hasPartial: boolean; onStop: () => void; onCancel: () => void
}) {
  const isActive = state === "recording"
  return (
    <div className="flex flex-col items-center gap-6 flex-1 pt-4">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">
        {state === "requesting" ? "Requesting microphone…" : isActive ? "Listening…" : "Starting…"}
      </p>
      <div className={`w-24 h-24 rounded-full bg-brand-pink flex items-center justify-center shadow-xl ${isActive ? "animate-pulse" : ""}`}>
        <svg width="40" height="40" viewBox="0 0 24 24" fill="none">
          <rect x="9" y="2" width="6" height="12" rx="3" fill="white" />
          <path d="M5 10a7 7 0 0 0 14 0" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="12" y1="17" x2="12" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
          <line x1="8" y1="21" x2="16" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
        </svg>
      </div>
      <p className="text-sm text-ink-muted text-center max-w-xs">
        {hasPartial
          ? "Say what's still missing — I'll add it to what I already have."
          : "Say something like: \"Room 201, phone 9876543210, rent 12k, deposit 15k\""}
      </p>
      <div className="flex gap-3 w-full mt-auto">
        <button onClick={onCancel} className="flex-1 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Cancel</button>
        <button onClick={onStop} disabled={!isActive} className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold disabled:opacity-40">Done</button>
      </div>
    </div>
  )
}

function ProcessingView({ label }: { label: string }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <div className="w-10 h-10 rounded-full border-4 border-brand-pink border-t-transparent animate-spin" />
      <p className="text-sm text-ink-muted">{label}</p>
    </div>
  )
}

function ConfirmView({
  fields, missing, requiredMet, onRecordAgain, onConfirm, onCancel,
}: {
  fields: OnboardingFields
  missing: string[]
  requiredMet: boolean
  onRecordAgain: () => void
  onConfirm: () => void
  onCancel: () => void
}) {
  const captured = (Object.entries(fields) as [string, unknown][])
    .filter(([, v]) => v !== null)

  return (
    <div className="flex flex-col gap-4 flex-1">
      <p className="text-xs font-semibold text-ink-muted uppercase tracking-wide">Captured</p>

      {captured.length === 0 ? (
        <p className="text-sm text-ink-muted">Nothing captured yet — try again.</p>
      ) : (
        <div className="flex flex-col">
          {captured.map(([key, value]) => (
            <div key={key} className="flex items-center justify-between py-2 border-b border-[#F0EDE9]">
              <span className="text-xs text-ink-muted">{FIELD_LABELS[key] ?? key}</span>
              <span className="text-sm font-semibold text-ink">{formatValue(key, value)}</span>
            </div>
          ))}
        </div>
      )}

      {missing.length > 0 && (
        <p className="text-xs text-status-warn font-medium">
          Still need: {missing.map((m) => FIELD_LABELS[m] ?? m).join(", ")}
        </p>
      )}

      {!requiredMet && (
        <p className="text-[10px] text-ink-muted">
          Room, phone, and rent are required before filling the form.
        </p>
      )}

      <div className="flex gap-2 mt-auto">
        <button onClick={onCancel} className="py-3 px-4 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Cancel</button>
        <button onClick={onRecordAgain} className="flex-1 py-3 rounded-pill border-2 border-brand-pink text-sm font-semibold text-brand-pink">Record again</button>
        <button onClick={onConfirm} disabled={!requiredMet} className="flex-1 py-3 rounded-pill bg-brand-pink text-white text-sm font-bold disabled:opacity-40">Fill Form</button>
      </div>
    </div>
  )
}

function ErrorView({ message, onRetry, onClose }: { message: string; onRetry: () => void; onClose: () => void }) {
  return (
    <div className="flex flex-col items-center gap-4 flex-1 justify-center">
      <p className="text-sm text-status-warn text-center">{message}</p>
      <div className="flex gap-3">
        <button onClick={onClose} className="px-6 py-3 rounded-pill border border-[#E2DEDD] text-sm font-semibold text-ink-muted">Close</button>
        <button onClick={onRetry} className="px-6 py-3 rounded-pill bg-brand-pink text-white text-sm font-semibold">Try again</button>
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Commit**

```bash
cd web
git add components/voice/onboarding-voice-sheet.tsx
git commit -m "feat(voice): OnboardingVoiceSheet component — multi-turn state machine"
```

---

## Task 7: Wire into `/onboarding/new/page.tsx`

**Files:**
- Edit: `web/app/onboarding/new/page.tsx`

The current page has a header section and the form. You need to:
1. Add `showVoiceSheet` state
2. Add a mic button to the header
3. Add `handleVoiceConfirm` callback that maps `OnboardingFields` → all form state setters
4. Render `OnboardingVoiceSheet` conditionally

- [ ] **Step 1: Add the import at the top of the file**

In `web/app/onboarding/new/page.tsx`, add this import after the existing imports:

```typescript
import { OnboardingVoiceSheet } from "@/components/voice/onboarding-voice-sheet"
import type { OnboardingFields } from "@/lib/parse-onboarding"
```

- [ ] **Step 2: Add `showVoiceSheet` state inside `NewOnboardingPage`**

After the existing `const [success, setSuccess] = useState(...)` line, add:

```typescript
const [showVoiceSheet, setShowVoiceSheet] = useState(false)
```

- [ ] **Step 3: Add `handleVoiceConfirm` inside `NewOnboardingPage`**

Add this function after the `checkRoomOccupancy` function:

```typescript
function handleVoiceConfirm(fields: OnboardingFields) {
  if (fields.room_number)           { setRoomNumber(fields.room_number); checkRoomOccupancy(fields.room_number) }
  if (fields.sharing_type)          setSharingType(fields.sharing_type)
  if (fields.tenant_phone)          setTenantPhone(fields.tenant_phone)
  if (fields.checkin_date)          setCheckinDate(fields.checkin_date)
  if (fields.monthly_rent != null)  setRent(String(fields.monthly_rent))
  if (fields.security_deposit != null) setDeposit(String(fields.security_deposit))
  if (fields.maintenance_fee != null)  setMaintenance(String(fields.maintenance_fee))
  if (fields.booking_amount != null)   setBooking(String(fields.booking_amount))
  if (fields.advance_mode)          setAdvanceMode(fields.advance_mode as "cash" | "upi" | "bank")
  if (fields.lock_in_months != null)   setLockIn(String(fields.lock_in_months))
  if (fields.future_rent != null)      setFutureRent(String(fields.future_rent))
  if (fields.future_rent_after_months != null) setFutureRentMonths(String(fields.future_rent_after_months))
  setShowVoiceSheet(false)
}
```

- [ ] **Step 4: Add the mic button to the header**

Find the existing header block:

```typescript
<div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
  <button onClick={() => router.back()}
    className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
    aria-label="Back">←</button>
  <h1 className="text-lg font-extrabold text-ink">New Tenant Onboarding</h1>
</div>
```

Replace it with:

```typescript
<div className="flex items-center gap-3 px-5 pt-12 pb-4 bg-surface border-b border-[#F0EDE9]">
  <button onClick={() => router.back()}
    className="w-9 h-9 rounded-full bg-bg flex items-center justify-center text-ink-muted font-bold"
    aria-label="Back">←</button>
  <h1 className="text-lg font-extrabold text-ink flex-1">New Tenant Onboarding</h1>
  <button
    type="button"
    onClick={() => setShowVoiceSheet(true)}
    className="w-9 h-9 rounded-full bg-brand-pink flex items-center justify-center shadow-sm active:opacity-80"
    aria-label="Fill by voice"
  >
    <svg width="18" height="18" viewBox="0 0 24 24" fill="none">
      <rect x="9" y="2" width="6" height="12" rx="3" fill="white" />
      <path d="M5 10a7 7 0 0 0 14 0" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <line x1="12" y1="17" x2="12" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
      <line x1="8" y1="21" x2="16" y2="21" stroke="white" strokeWidth="2" strokeLinecap="round" />
    </svg>
  </button>
</div>
```

- [ ] **Step 5: Render `OnboardingVoiceSheet` at the bottom of the returned JSX**

Just before the closing `</main>` tag at the very end of the returned JSX (not inside the success screen), add:

```typescript
{showVoiceSheet && (
  <OnboardingVoiceSheet
    onClose={() => setShowVoiceSheet(false)}
    onConfirm={handleVoiceConfirm}
  />
)}
```

- [ ] **Step 6: Commit**

```bash
cd web
git add app/onboarding/new/page.tsx
git commit -m "feat(voice): wire OnboardingVoiceSheet into /onboarding/new — mic button + pre-fill"
```

---

## Task 8: Manual smoke test + deploy

- [ ] **Step 1: Run all PWA tests**

```bash
cd web && npm test
```

Expected: all existing tests pass, plus the 7 new tests from Tasks 3 + 5.

- [ ] **Step 2: Start local dev server**

```bash
cd web && npm run dev
```

Open `http://localhost:3000/onboarding/new` in Chrome (Chrome required — SpeechRecognition is Chrome-only on Android).

- [ ] **Step 3: Smoke test the golden path**

1. Tap the pink mic button in the header
2. Say: *"Room 201, phone 9876543210, rent 12 thousand, deposit 15k, maintenance 500"*
3. Tap Done
4. Wait for the voice confirmation (OpenAI TTS should speak back naturally)
5. Check the confirm sheet shows: Room 201, Phone 9876543210, Rent ₹12,000, Deposit ₹15,000, Maintenance ₹500
6. Tap "Fill Form"
7. Verify all 5 fields are pre-filled in the form

- [ ] **Step 4: Smoke test multi-turn**

1. Tap mic, say only: *"Room 305, rent 10k"*
2. Tap Done — bot should say something like *"Got room 305, rent 10,000. Still need phone and deposit."*
3. Confirm sheet shows 2 fields, "Fill Form" is disabled
4. Tap "Record again", say: *"Phone 9123456789, deposit 12k"*
5. Tap Done — bot confirms all four
6. "Fill Form" button is now enabled
7. Tap — form pre-fills all 4 fields

- [ ] **Step 5: Build check**

```bash
cd web && npm run build
```

Expected: build succeeds with no errors.

- [ ] **Step 6: Deploy to VPS**

```bash
git push
ssh kozzy "cd /opt/pg-accountant && git pull && npm --prefix web run build && systemctl restart kozzy-pwa"
```

- [ ] **Step 7: Final commit if any fixes were needed**

```bash
git add -A && git commit -m "fix(voice): smoke test fixes for onboarding voice sheet"
git push
```
