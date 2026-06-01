import { createContext, useEffect, useState, type ReactNode } from "react";
import { getDb } from "../lib/db";

type DbState = { status: "loading" } | { status: "ready" } | { status: "error"; message: string };

const DbContext = createContext<DbState>({ status: "loading" });

export function DbProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DbState>({ status: "loading" });

  useEffect(() => {
    getDb()
      .then(() => setState({ status: "ready" }))
      .catch((e: unknown) => setState({ status: "error", message: String(e) }));
  }, []);

  if (state.status === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <p className="text-gray-500 text-sm">Initializing database…</p>
      </div>
    );
  }

  if (state.status === "error") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <div className="max-w-lg text-center space-y-2">
          <p className="text-red-600 text-sm font-semibold">Failed to open database</p>
          <p className="text-red-500 text-xs font-mono bg-red-50 rounded p-3 text-left break-all">{state.message}</p>
        </div>
      </div>
    );
  }

  return <DbContext.Provider value={state}>{children}</DbContext.Provider>;
}
