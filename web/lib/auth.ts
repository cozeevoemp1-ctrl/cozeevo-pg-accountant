import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "./supabase";

export interface AuthSession {
  user: User;
  session: Session;
  phone: string;
  role: "admin" | "staff" | "tenant";
}

export async function signInWithPhone(phone: string): Promise<{ error: string | null }> {
  const client = supabase();
  const { error } = await client.auth.signInWithOtp({ phone });
  return { error: error?.message ?? null };
}

export async function verifyOtp(
  phone: string,
  token: string,
): Promise<{ data: AuthSession | null; error: string | null }> {
  const client = supabase();
  const { data, error } = await client.auth.verifyOtp({
    phone,
    token,
    type: "sms",
  });
  if (error || !data.session) {
    return { data: null, error: error?.message ?? "OTP verification failed" };
  }
  const meta = data.user?.user_metadata ?? {};
  return {
    data: {
      user: data.user!,
      session: data.session,
      phone: data.user?.phone ?? phone,
      role: (meta.role as AuthSession["role"]) ?? "tenant",
    },
    error: null,
  };
}

export async function getSession(): Promise<AuthSession | null> {
  const client = supabase();
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

export async function signOut(): Promise<void> {
  await supabase().auth.signOut();
}
