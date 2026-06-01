import type { DbHandle } from "./dbTypes";
import { initSchema } from "./schema";

let _db: DbHandle | null = null;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window;
}

export async function getDb(): Promise<DbHandle> {
  if (_db) return _db;

  if (isTauri()) {
    // Native build — use Tauri's SQLite plugin (persisted to app data dir)
    const Database = (await import("@tauri-apps/plugin-sql")).default;
    _db = await Database.load("sqlite:hoa.db");
  } else {
    // Browser / Preview — use sql.js (in-memory, seeded fresh each session)
    const { getBrowserDb } = await import("./db.browser");
    _db = await getBrowserDb();
  }

  await initSchema(_db);
  return _db;
}
