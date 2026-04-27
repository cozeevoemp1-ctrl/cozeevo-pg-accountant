"use client";

import { useCallback, useRef, useState } from "react";

export type SpeechState = "idle" | "requesting" | "recording" | "stopped" | "unsupported" | "error";

export interface SpeechControls {
  state: SpeechState;
  transcript: string;
  start: () => void;
  stop: () => void;
  reset: () => void;
  error: string | null;
}

// SpeechRecognition is not in the default TS lib — declare it locally.
interface SR extends EventTarget {
  lang: string;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((e: { error: string }) => void) | null;
  onresult: ((e: { results: SpeechRecognitionResultList }) => void) | null;
}

interface SRConstructor {
  new (): SR;
}

function getSR(): SRConstructor | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, unknown>;
  return (w["SpeechRecognition"] as SRConstructor | undefined) ??
    (w["webkitSpeechRecognition"] as SRConstructor | undefined) ??
    null;
}

export function useSpeechInput(): SpeechControls {
  const [state, setState] = useState<SpeechState>("idle");
  const [transcript, setTranscript] = useState("");
  const [error, setError] = useState<string | null>(null);
  const recRef = useRef<SR | null>(null);

  const start = useCallback(() => {
    const SR = getSR();
    if (!SR) {
      setState("unsupported");
      setError("Speech recognition not supported — use Chrome on Android.");
      return;
    }

    setError(null);
    setTranscript("");
    setState("requesting");

    const rec = new SR();
    rec.lang = "en-IN";
    rec.interimResults = false;
    rec.maxAlternatives = 1;
    recRef.current = rec;

    rec.onstart = () => setState("recording");

    rec.onresult = (e) => {
      const text = Array.from(e.results)
        .map((r) => r[0].transcript)
        .join(" ")
        .trim();
      setTranscript(text);
    };

    rec.onerror = (e) => {
      if (e.error === "no-speech") {
        setError("No speech detected — try again.");
      } else if (e.error === "not-allowed") {
        setError("Microphone permission denied.");
      } else {
        setError(`Recognition error: ${e.error}`);
      }
      setState("error");
    };

    rec.onend = () => {
      setState((s) => (s === "recording" || s === "requesting" ? "stopped" : s));
    };

    rec.start();
  }, []);

  const stop = useCallback(() => {
    recRef.current?.stop();
  }, []);

  const reset = useCallback(() => {
    recRef.current?.abort();
    recRef.current = null;
    setTranscript("");
    setError(null);
    setState("idle");
  }, []);

  return { state, transcript, start, stop, reset, error };
}
