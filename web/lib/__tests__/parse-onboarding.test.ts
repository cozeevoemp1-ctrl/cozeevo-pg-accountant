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
