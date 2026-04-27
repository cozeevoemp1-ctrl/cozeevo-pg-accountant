"use client";

import { usePathname } from "next/navigation";
import { HomeTabBar } from "./home-tab-bar";

/** Renders the persistent nav on all pages except /login and /onboarding (public forms). */
export function NavWrapper() {
  const pathname = usePathname();
  if (pathname === "/login" || pathname.startsWith("/onboarding")) return null;
  return <HomeTabBar />;
}
