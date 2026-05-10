import type { Session, User } from "@supabase/supabase-js";
import { supabase } from "./supabase";

export interface AuthSession {
  user: User;
  session: Session;
  phone: string;
  role: "admin" | "staff" | "tenant";
}

export async function signInWithEmail(
  email: string,
  password: string,
): Promise<{ error: string | null }> {
  try {
    const timeout = new Promise<never>((_, reject) =>
      setTimeout(() => reject(new Error("Connection timed out. Check your internet and try again.")), 10000)
    );
    const { error } = await Promise.race([
      supabase().auth.signInWithPassword({ email, password }),
      timeout,
    ]);
    return { error: error?.message ?? null };
  } catch (e) {
    return { error: e instanceof Error ? e.message : "Login failed. Try again." };
  }
}


export async function signOut(): Promise<void> {
  await supabase().auth.signOut();
}

export async function resetPasswordForEmail(email: string): Promise<{ error: string | null }> {
  const redirectTo = `${window.location.origin}/auth/callback?next=/auth/update-password`;
  const { error } = await supabase().auth.resetPasswordForEmail(email, { redirectTo });
  return { error: error?.message ?? null };
}
