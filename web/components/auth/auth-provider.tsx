"use client";

import {
  createContext,
  useContext,
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { supabase } from "@/lib/supabase";
import type { AuthSession } from "@/lib/auth";

interface AuthContextValue {
  session: AuthSession | null;
  loading: boolean;
}

const AuthContext = createContext<AuthContextValue>({
  session: null,
  loading: true,
});

export function AuthProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<AuthSession | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const client = supabase();

    // Load initial session
    client.auth.getSession().then(({ data }) => {
      if (data.session) {
        const meta = data.session.user.user_metadata ?? {};
        setSession({
          user: data.session.user,
          session: data.session,
          phone: data.session.user.phone ?? "",
          role: (meta.role as AuthSession["role"]) ?? "tenant",
        });
      }
      setLoading(false);
    });

    // Listen for auth state changes
    const { data: listener } = client.auth.onAuthStateChange((_event, sb_session) => {
      if (sb_session) {
        const meta = sb_session.user.user_metadata ?? {};
        setSession({
          user: sb_session.user,
          session: sb_session,
          phone: sb_session.user.phone ?? "",
          role: (meta.role as AuthSession["role"]) ?? "tenant",
        });
      } else {
        setSession(null);
      }
      setLoading(false);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  return (
    <AuthContext.Provider value={{ session, loading }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  return useContext(AuthContext);
}
