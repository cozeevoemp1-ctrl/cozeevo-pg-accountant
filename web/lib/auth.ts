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
  const { error } = await supabase().auth.signInWithPassword({ email, password });
  return { error: error?.message ?? null };
}


export async function signOut(): Promise<void> {
  await supabase().auth.signOut();
}
