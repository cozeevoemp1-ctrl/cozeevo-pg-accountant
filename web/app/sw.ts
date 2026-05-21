import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { Serwist, NetworkFirst, NetworkOnly, ExpirationPlugin } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: WorkerGlobalScope & typeof globalThis;

// Never cache cross-origin API calls — pass them straight to the network.
// Catches: api.getkozzy.com (FastAPI), *.supabase.co (auth token refresh, DB).
// Without this, SW strategies in defaultCache can intercept and silently fail
// DELETE/PATCH/POST requests, producing "Failed to fetch" in the browser.
const crossOriginNetworkOnly = {
  matcher: ({ sameOrigin }: { sameOrigin: boolean }) => !sameOrigin,
  handler: new NetworkOnly(),
};

// HTML pages use NetworkFirst so post-deploy Server Action IDs always match the live build.
// defaultCache uses StaleWhileRevalidate for pages (serves old cache instantly after deploy → broken Server Actions).
const pagesNetworkFirst = {
  matcher: ({ request, url: { pathname }, sameOrigin }: { request: Request; url: URL; sameOrigin: boolean }) =>
    sameOrigin &&
    !pathname.startsWith("/api/") &&
    (request.mode === "navigate" ||
      request.headers.get("Content-Type")?.includes("text/html") === true),
  handler: new NetworkFirst({
    cacheName: "pages",
    plugins: [new ExpirationPlugin({ maxEntries: 32, maxAgeSeconds: 86400 })],
    networkTimeoutSeconds: 5,
  }),
};

const serwist = new Serwist({
  precacheEntries: self.__SW_MANIFEST,
  skipWaiting: true,
  clientsClaim: true,
  navigationPreload: true,
  runtimeCaching: [crossOriginNetworkOnly, pagesNetworkFirst, ...defaultCache],
});

serwist.addEventListeners();
