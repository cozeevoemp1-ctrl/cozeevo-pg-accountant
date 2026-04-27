"use client";

import { useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { TabBar } from "@/components/ui/tab-bar";
import { VoiceSheet } from "@/components/voice/voice-sheet";
import type { PaymentIntent } from "@/lib/api";

export function HomeTabBar() {
  const router = useRouter();
  const pathname = usePathname();
  const [voiceOpen, setVoiceOpen] = useState(false);

  function handleIntent(intent: PaymentIntent) {
    setVoiceOpen(false);
    // Pass intent as search params to payment page
    const params = new URLSearchParams();
    if (intent.amount != null) params.set("amount", String(intent.amount));
    if (intent.method) params.set("method", intent.method);
    if (intent.for_type) params.set("for_type", intent.for_type);
    if (intent.tenant_name) params.set("tenant_name", intent.tenant_name);
    if (intent.tenant_room) params.set("tenant_room", intent.tenant_room);
    router.push(`/payment/new?${params.toString()}`);
  }

  return (
    <>
      <TabBar
        activeKey={
          pathname === "/"                   ? "home"       :
          pathname.startsWith("/payment")    ? "payment"    :
          pathname.startsWith("/collection") ? "collection" :
          pathname.startsWith("/onboarding") || pathname.startsWith("/checkin") ? "tenants" :
          "home"
        }
        items={[
          {
            key: "home",
            label: "Home",
            icon: "🏠",
            onClick: () => router.push("/"),
          },
          {
            key: "payments",
            label: "Payments",
            icon: "📋",
            onClick: () => router.push("/payment/new"),
          },
          {
            key: "voice",
            label: "Voice",
            icon: <MicSvg />,
            isCta: true,
            onClick: () => setVoiceOpen(true),
          },
          {
            key: "collection",
            label: "Collection",
            icon: "📊",
            onClick: () => router.push("/collection/breakdown"),
          },
          {
            key: "tenants",
            label: "Tenants",
            icon: "👤",
            onClick: () => router.push("/onboarding/new"),
          },
        ]}
      />

      {voiceOpen && (
        <VoiceSheet onClose={() => setVoiceOpen(false)} onPaymentIntent={handleIntent} />
      )}
    </>
  );
}

function MicSvg() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor" />
      <path d="M5 10a7 7 0 0 0 14 0" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="12" y1="17" x2="12" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
      <line x1="8" y1="21" x2="16" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round" />
    </svg>
  );
}
