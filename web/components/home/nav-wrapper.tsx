"use client";

import { usePathname } from "next/navigation";
import { HomeTabBar } from "./home-tab-bar";

// Nav is hidden on focused form/action pages — they have their own header + back button.
// /tenants (hub list) keeps nav; /tenants/[id]/edit does not.
function hideNav(pathname: string): boolean {
  if (pathname === "/login") return true;
  return false;
}

export function NavWrapper() {
  const pathname = usePathname();
  if (hideNav(pathname)) return null;
  return <HomeTabBar />;
}
