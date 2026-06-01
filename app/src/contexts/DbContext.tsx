import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getDb } from "../lib/db";

type DbState = "loading" | "ready" | "error";

const DbContext = createContext<DbState>("loading");

export function DbProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<DbState>("loading");

  useEffect(() => {
    getDb()
      .then(() => setState("ready"))
      .catch(() => setState("error"));
  }, []);

  if (state === "loading") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <p className="text-gray-500 text-sm">Initializing database…</p>
      </div>
    );
  }

  if (state === "error") {
    return (
      <div className="flex h-screen items-center justify-center bg-gray-100">
        <p className="text-red-600 text-sm">Failed to open database. Please restart the app.</p>
      </div>
    );
  }

  return <DbContext.Provider value={state}>{children}</DbContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useDb() {
  return useContext(DbContext);
}
