"use client";

/**
 * App business-rule config served by GET /api/v2/app/config — never hardcode
 * these in UI code (spec rule 6). Fetched once per session and cached.
 *
 * DEFAULTS below are a network-failure fallback only, mirroring the backend's
 * current values; the fetched values always win.
 */
import { useEffect, useState } from "react";
import { fetchAppConfig, type AppConfig } from "./api";

const DEFAULTS: AppConfig = { notice_by_day: 5, total_beds: 0 };

let cached: AppConfig | null = null;
let inflight: Promise<AppConfig> | null = null;

export async function getAppConfig(): Promise<AppConfig> {
  if (cached) return cached;
  if (!inflight) {
    inflight = fetchAppConfig()
      .then((c) => (cached = c))
      .catch(() => (cached = DEFAULTS)); // offline fallback — backend wins when reachable
  }
  return inflight;
}

/** React hook: returns fallback defaults until the fetch resolves. */
export function useAppConfig(): AppConfig {
  const [config, setConfig] = useState<AppConfig>(cached ?? DEFAULTS);
  useEffect(() => {
    let alive = true;
    getAppConfig().then((c) => {
      if (alive) setConfig(c);
    });
    return () => {
      alive = false;
    };
  }, []);
  return config;
}
