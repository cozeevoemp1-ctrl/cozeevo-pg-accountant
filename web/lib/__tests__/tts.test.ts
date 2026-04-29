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
    Object.defineProperty(window, "speechSynthesis", {
      value: { speak: mockSpeak, cancel: vi.fn() },
      writable: true,
      configurable: true,
    })
    vi.stubGlobal("SpeechSynthesisUtterance", vi.fn().mockReturnValue({}))

    await speakText("Fallback test.")

    expect(mockSpeak).toHaveBeenCalled()
  })

  it("uses browser fallback when NEXT_PUBLIC_OPENAI_API_KEY is missing", async () => {
    delete process.env.NEXT_PUBLIC_OPENAI_API_KEY

    const mockSpeak = vi.fn()
    Object.defineProperty(window, "speechSynthesis", {
      value: { speak: mockSpeak, cancel: vi.fn() },
      writable: true,
      configurable: true,
    })
    vi.stubGlobal("SpeechSynthesisUtterance", vi.fn().mockReturnValue({}))

    await speakText("No key test.")

    expect(mockSpeak).toHaveBeenCalled()
  })
})
