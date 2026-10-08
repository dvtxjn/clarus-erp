import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import type { User } from "./types";
import { getCurrentUser, login as apiLogin, logout as apiLogout } from "./api";

interface AuthContextValue {
  user: User | null;
  loading: boolean;
  login: (email: string, password: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextValue | undefined>(undefined);

/** Auto-logout (client, 2026-09-30): 30 minutes without activity in any ERP tab. */
export const IDLE_MS = 30 * 60 * 1000;
const ACTIVE_KEY = "last_activity";

export function markActive(): void {
  try {
    localStorage.setItem(ACTIVE_KEY, String(Date.now()));
  } catch {
    /* storage blocked */
  }
}

export function lastActive(): number {
  try {
    return Number(localStorage.getItem(ACTIVE_KEY)) || Date.now();
  } catch {
    return Date.now();
  }
}

function idleTooLong(): boolean {
  return Date.now() - lastActive() > IDLE_MS;
}

/** Forget the login; the login page shows why. */
export function endSession(reason?: string): void {
  apiLogout();
  try {
    if (reason) sessionStorage.setItem("logout_reason", reason);
  } catch {
    /* ignore */
  }
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem("access_token");
    if (!token) {
      setLoading(false);
      return;
    }
    if (idleTooLong()) {
      // came back after the idle limit (e.g. laptop closed overnight): log in again
      endSession("Logged out after 30 minutes without activity.");
      setLoading(false);
      return;
    }
    getCurrentUser()
      .then(setUser)
      .catch(() => localStorage.removeItem("access_token"))
      .finally(() => setLoading(false));
  }, []);

  async function login(email: string, password: string) {
    await apiLogin(email, password);
    markActive();
    const me = await getCurrentUser();
    setUser(me);
  }

  const logout = useCallback(() => {
    apiLogout();
    setUser(null);
  }, []);

  // ended elsewhere: login expired (401), idle timer, or another tab logged out
  useEffect(() => {
    const ended = (e: Event) => {
      endSession((e as CustomEvent<string>).detail);
      setUser(null);
    };
    const otherTab = (e: StorageEvent) => {
      if (e.key === "access_token" && !e.newValue) setUser(null);
    };
    window.addEventListener("auth:ended", ended);
    window.addEventListener("storage", otherTab);
    return () => {
      window.removeEventListener("auth:ended", ended);
      window.removeEventListener("storage", otherTab);
    };
  }, []);

  return <AuthContext.Provider value={{ user, loading, login, logout }}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

/** A view-only login: can look at everything its role allows, can't change anything (the server refuses too). */
export function useReadOnly(): boolean {
  return !!useAuth().user?.read_only;
}
