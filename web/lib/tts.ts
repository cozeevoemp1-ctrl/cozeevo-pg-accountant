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
