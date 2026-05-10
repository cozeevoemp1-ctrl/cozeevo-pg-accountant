"use client";

import { useRouter } from "next/navigation";
import { signOut } from "@/lib/auth";

interface LogoutAvatarProps {
  initial: string;
}

export function LogoutAvatar({ initial }: LogoutAvatarProps) {
  const router = useRouter();

  async function handleSignOut() {
    await signOut();
    router.replace("/login");
  }

  return (
    <button
      onClick={handleSignOut}
      title="Sign out"
      className="w-10 h-10 rounded-full bg-brand-pink flex items-center justify-center text-white font-bold text-sm active:opacity-70"
    >
      {initial}
    </button>
  );
}
