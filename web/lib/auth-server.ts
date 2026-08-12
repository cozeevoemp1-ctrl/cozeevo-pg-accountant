import type { AuthSession } from "./auth";
import { createSupabaseServer } from "./supabase-server";

export async function getSession(): Promise<AuthSession | null> {
  const client = await createSupabaseServer();
  const { data } = await client.auth.getSession();
  if (!data.session) return null;
  // role from app_metadata ONLY (admin-API-writable). user_metadata is
  // self-editable via supabase.auth.updateUser() → never trust it for privilege.
  const appMeta = data.session.user.app_metadata ?? {};
  return {
    user: data.session.user,
    session: data.session,
    phone: data.session.user.phone ?? "",
    role: (appMeta.role as AuthSession["role"]) ?? "tenant",
  };
}
