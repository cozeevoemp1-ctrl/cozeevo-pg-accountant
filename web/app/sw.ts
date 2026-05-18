import { defaultCache } from "@serwist/next/worker";
import type { PrecacheEntry, SerwistGlobalConfig } from "serwist";
import { Serwist, NetworkFirst, ExpirationPlugin } from "serwist";

declare global {
  interface WorkerGlobalScope extends SerwistGlobalConfig {
    __SW_MANIFEST: (PrecacheEntry | string)[] | undefined;
  }
}

declare const self: WorkerGlobalScope & typeof globalThis;

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
  runtimeCaching: [pagesNetworkFirst, ...defaultCache],
});

serwist.addEventListeners();
