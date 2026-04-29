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
- checkin_date (string, ISO date YYYY-MM-DD — only populate if the receptionist explicitly mentions a date, otherwise null)
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
  const raw = data.choices?.[0]?.message?.content
  if (!raw) throw new Error("Groq returned empty content")
  let parsed: OnboardingParseResult
  try {
    parsed = JSON.parse(raw) as OnboardingParseResult
  } catch {
    throw new Error(`Groq returned invalid JSON: ${raw.slice(0, 200)}`)
  }
  // Merge over emptyOnboardingFields so any LLM-omitted keys default to null (not undefined)
  parsed.fields = { ...emptyOnboardingFields(), ...parsed.fields }
  return parsed
}
