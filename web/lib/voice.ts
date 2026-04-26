"use client";

import { useCallback, useRef, useState } from "react";

export type RecorderState = "idle" | "requesting" | "recording" | "stopped" | "error";

export interface VoiceRecorderControls {
  state: RecorderState;
  audioBlob: Blob | null;
  mimeType: string;
  start: () => Promise<void>;
  stop: () => void;
  reset: () => void;
  error: string | null;
}

const PREFERRED_MIME = "audio/webm;codecs=opus";
const FALLBACK_MIME = "audio/mp4";

function getSupportedMime(): string {
  if (typeof MediaRecorder === "undefined") return PREFERRED_MIME;
  if (MediaRecorder.isTypeSupported(PREFERRED_MIME)) return PREFERRED_MIME;
  if (MediaRecorder.isTypeSupported(FALLBACK_MIME)) return FALLBACK_MIME;
  return "";
}

export function useVoiceRecorder(): VoiceRecorderControls {
  const [state, setState] = useState<RecorderState>("idle");
  const [audioBlob, setAudioBlob] = useState<Blob | null>(null);
  const [error, setError] = useState<string | null>(null);

  const recorderRef = useRef<MediaRecorder | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const mimeRef = useRef<string>(PREFERRED_MIME);

  const start = useCallback(async () => {
    setError(null);
    setAudioBlob(null);
    setState("requesting");

    let stream: MediaStream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setError("Microphone permission denied");
      setState("error");
      return;
    }

    streamRef.current = stream;
    chunksRef.current = [];
    mimeRef.current = getSupportedMime();

    const recorder = new MediaRecorder(
      stream,
      mimeRef.current ? { mimeType: mimeRef.current } : undefined,
    );
    recorderRef.current = recorder;

    recorder.ondataavailable = (e) => {
      if (e.data.size > 0) chunksRef.current.push(e.data);
    };

    recorder.onstop = () => {
      const blob = new Blob(chunksRef.current, { type: mimeRef.current || "audio/webm" });
      setAudioBlob(blob);
      setState("stopped");
      stream.getTracks().forEach((t) => t.stop());
    };

    recorder.onerror = () => {
      setError("Recording failed");
      setState("error");
      stream.getTracks().forEach((t) => t.stop());
    };

    recorder.start(250); // collect chunks every 250ms
    setState("recording");
  }, []);

  const stop = useCallback(() => {
    if (recorderRef.current?.state === "recording") {
      recorderRef.current.stop();
    }
  }, []);

  const reset = useCallback(() => {
    recorderRef.current?.stop();
    streamRef.current?.getTracks().forEach((t) => t.stop());
    recorderRef.current = null;
    streamRef.current = null;
    chunksRef.current = [];
    setAudioBlob(null);
    setError(null);
    setState("idle");
  }, []);

  return { state, audioBlob, mimeType: mimeRef.current, start, stop, reset, error };
}
