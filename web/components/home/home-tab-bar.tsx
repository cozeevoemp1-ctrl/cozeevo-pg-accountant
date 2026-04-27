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
    const params = new URLSearchParams();
    if (intent.amount != null) params.set("amount", String(intent.amount));
    if (intent.method) params.set("method", intent.method);
    if (intent.for_type) params.set("for_type", intent.for_type);
    if (intent.tenant_name) params.set("tenant_name", intent.tenant_name);
    if (intent.tenant_room) params.set("tenant_room", intent.tenant_room);
    router.push(`/payment/new?${params.toString()}`);
  }

  const active =
    pathname === "/"                     ? "home"       :
    pathname.startsWith("/payment")      ? "payments"   :
    pathname.startsWith("/collection")   ? "collection" :
    pathname.startsWith("/tenants") || pathname.startsWith("/onboarding") || pathname.startsWith("/checkin") ? "manage" :
    pathname.startsWith("/reminders")    ? "reminders"  :
    "home";

  return (
    <>
      <TabBar
        activeKey={active}
        items={[
          {
            key: "home",
            label: "Home",
            icon: <HomeIcon />,
            onClick: () => router.push("/"),
          },
          {
            key: "payments",
            label: "Payments",
            icon: <PayIcon />,
            onClick: () => router.push("/payment/new"),
          },
          {
            key: "voice",
            label: "Voice",
            icon: <MicIcon />,
            isCta: true,
            onClick: () => setVoiceOpen(true),
          },
          {
            key: "collection",
            label: "Collection",
            icon: <ChartIcon />,
            onClick: () => router.push("/collection/breakdown"),
          },
          {
            key: "manage",
            label: "Manage",
            icon: <ManageIcon />,
            onClick: () => router.push("/tenants"),
          },
        ]}
      />
      {voiceOpen && (
        <VoiceSheet onClose={() => setVoiceOpen(false)} onPaymentIntent={handleIntent} />
      )}
    </>
  );
}

function HomeIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <path d="M3 12L12 3l9 9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M9 21V12h6v9" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
      <path d="M5 10v11h14V10" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
}

function PayIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="2" y="5" width="20" height="14" rx="3" stroke="currentColor" strokeWidth="2"/>
      <path d="M2 10h20" stroke="currentColor" strokeWidth="2"/>
      <path d="M6 15h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  );
}

function MicIcon() {
  return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="9" y="2" width="6" height="12" rx="3" fill="currentColor"/>
      <path d="M5 10a7 7 0 0 0 14 0" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="12" y1="17" x2="12" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <line x1="8" y1="21" x2="16" y2="21" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
    </svg>
  );
}

function ChartIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <rect x="3" y="12" width="4" height="9" rx="1" fill="currentColor" opacity="0.6"/>
      <rect x="10" y="7" width="4" height="14" rx="1" fill="currentColor"/>
      <rect x="17" y="3" width="4" height="18" rx="1" fill="currentColor" opacity="0.6"/>
    </svg>
  );
}

function ManageIcon() {
  return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="9" cy="7" r="4" stroke="currentColor" strokeWidth="2"/>
      <path d="M3 21v-2a7 7 0 0 1 12-4.9" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/>
      <circle cx="18" cy="18" r="3" stroke="currentColor" strokeWidth="2"/>
      <path d="M18 15v-1M18 22v-1M15 18h-1M22 18h-1" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round"/>
    </svg>
  );
}
