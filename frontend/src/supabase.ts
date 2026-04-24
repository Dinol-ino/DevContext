import { createClient, type AuthChangeEvent, type Session, type User } from "@supabase/supabase-js";

import type { UserProfile } from "./types";

export const supabaseUrl = import.meta.env.VITE_SUPABASE_URL?.trim() ?? "";
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY?.trim() ?? "";

export const isSupabaseConfigured = Boolean(supabaseUrl && supabaseAnonKey);

const supabase = isSupabaseConfigured
  ? createClient(supabaseUrl, supabaseAnonKey, {
      auth: {
        autoRefreshToken: true,
        detectSessionInUrl: true,
        persistSession: true,
      },
    })
  : null;

function mapUser(user: User): UserProfile {
  const metadata = user.user_metadata;
  const fullName =
    (typeof metadata?.full_name === "string" && metadata.full_name) ||
    (typeof metadata?.name === "string" && metadata.name) ||
    user.email ||
    "DevContextIQ User";
  const avatarUrl = typeof metadata?.avatar_url === "string" ? metadata.avatar_url : null;

  return {
    id: user.id,
    email: user.email ?? "unknown@devcontextiq",
    fullName,
    avatarUrl,
  };
}

export async function getCurrentUser(): Promise<UserProfile | null> {
  if (!supabase) {
    return null;
  }

  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user) {
    return null;
  }
  return mapUser(data.user);
}

export function subscribeToAuthChanges(
  callback: (user: UserProfile | null, event: AuthChangeEvent, session: Session | null) => void,
): () => void {
  if (!supabase) {
    return () => undefined;
  }

  const { data } = supabase.auth.onAuthStateChange((event, session) => {
    callback(session?.user ? mapUser(session.user) : null, event, session);
  });

  return () => {
    data.subscription.unsubscribe();
  };
}

export async function signInWithGoogle(): Promise<{ ok: boolean; error?: string }> {
  if (!supabase) {
    return {
      ok: false,
      error: "Supabase auth is not configured. Set VITE_SUPABASE_URL and VITE_SUPABASE_ANON_KEY.",
    };
  }

  const { error } = await supabase.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: window.location.href,
      queryParams: {
        access_type: "offline",
        prompt: "consent",
      },
    },
  });

  if (error) {
    return { ok: false, error: error.message };
  }

  return { ok: true };
}

export async function signOutUser(): Promise<void> {
  if (!supabase) {
    return;
  }

  await supabase.auth.signOut();
}
