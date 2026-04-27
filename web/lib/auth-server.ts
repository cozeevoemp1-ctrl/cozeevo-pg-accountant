import type { AuthSession } from "./auth";
import { createSupabaseServer } from "./supabase-server";

export async function getSession(): Promise<AuthSession | null> {
  const client = await createSupabaseServer();
  const { data } = await client.auth.getSession();
  if (!data.session) return null;
  const meta = data.session.user.user_metadata ?? {};
  return {
    user: data.session.user,
    session: data.session,
    phone: data.session.user.phone ?? "",
    role: (meta.role as AuthSession["role"]) ?? "tenant",
  };
}
