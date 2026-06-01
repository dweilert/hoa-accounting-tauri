import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { loadSession, clearSession, getRawSession, type SessionUser } from "../lib/auth";

type AuthState =
  | { status: "loading" }
  | { status: "no_users" }
  | { status: "unauthenticated" }
  | { status: "authenticated"; user: SessionUser };

type AuthContextValue = {
  state: AuthState;
  login: (user: SessionUser) => void;
  logout: () => void;
  refresh: () => void;
};

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<AuthState>({ status: "loading" });
  const expiryTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function scheduleExpiry() {
    if (expiryTimer.current) clearTimeout(expiryTimer.current);
    const raw = getRawSession();
    if (!raw) return;
    const ms = raw.expiresAt - Date.now();
    if (ms <= 0) return;
    expiryTimer.current = setTimeout(() => {
      clearSession();
      setState({ status: "unauthenticated" });
    }, ms);
  }

  function refresh() {
    const session = loadSession();
    if (session) {
      setState({ status: "authenticated", user: session });
      scheduleExpiry();
    } else {
      setState({ status: "unauthenticated" });
    }
  }

  useEffect(() => {
    refresh();
    return () => { if (expiryTimer.current) clearTimeout(expiryTimer.current); };
  }, []);

  function login(user: SessionUser) {
    setState({ status: "authenticated", user });
    scheduleExpiry();
  }

  function logout() {
    if (expiryTimer.current) clearTimeout(expiryTimer.current);
    clearSession();
    setState({ status: "unauthenticated" });
  }

  return (
    <AuthContext.Provider value={{ state, login, logout, refresh }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}

export function useCurrentUser(): SessionUser | null {
  const { state } = useAuth();
  return state.status === "authenticated" ? state.user : null;
}
