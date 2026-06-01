import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { loadSession, clearSession, type SessionUser } from "../lib/auth";

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

  function refresh() {
    const session = loadSession();
    if (session) {
      setState({ status: "authenticated", user: session });
    } else {
      // Will be set to no_users or unauthenticated by the consumer
      setState({ status: "unauthenticated" });
    }
  }

  useEffect(() => {
    refresh();
  }, []);

  function login(user: SessionUser) {
    setState({ status: "authenticated", user });
  }

  function logout() {
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
