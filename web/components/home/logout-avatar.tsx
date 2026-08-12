"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { signOut } from "@/lib/auth";
import { Sheet } from "@/components/ui/modal";

function SignOutSheet({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  async function handleSignOut() {
    setLoading(true);
    await signOut();
    router.replace("/login");
  }
  return (
    <Sheet open onClose={onClose} title="Sign out?">
      <div className="flex flex-col gap-3">
        <p className="text-xs text-ink-muted text-center">You will need to log in again to use the app.</p>
        <button onClick={handleSignOut} disabled={loading}
          className="w-full rounded-pill bg-brand-pink py-3 text-white font-bold text-sm active:opacity-80 disabled:opacity-50">
          {loading ? "Signing out…" : "Sign out"}
        </button>
        <button onClick={onClose}
          className="w-full rounded-pill border border-border-strong py-3 text-ink font-semibold text-sm">
          Cancel
        </button>
      </div>
    </Sheet>
  );
}

export function LogoutButton() {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} title="Sign out"
        className="w-9 h-9 rounded-full bg-bg border border-border-strong flex items-center justify-center text-ink-muted active:opacity-70">
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/>
          <polyline points="16 17 21 12 16 7"/>
          <line x1="21" y1="12" x2="9" y2="12"/>
        </svg>
      </button>
      {open && <SignOutSheet onClose={() => setOpen(false)} />}
    </>
  );
}

interface LogoutAvatarProps {
  initial: string;
}

export function LogoutAvatar({ initial }: LogoutAvatarProps) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button onClick={() => setOpen(true)} title="Sign out"
        className="w-10 h-10 rounded-full bg-brand-pink flex items-center justify-center text-white font-bold text-sm active:opacity-70">
        {initial}
      </button>
      {open && <SignOutSheet onClose={() => setOpen(false)} />}
    </>
  );
}
