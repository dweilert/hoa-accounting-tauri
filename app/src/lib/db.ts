import type { DbHandle } from "./dbTypes";
import { initSchema } from "./schema";

let _db: DbHandle | null = null;

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI__" in window;
}

// Key used in localStorage to remember the configured database path.
export const DB_PATH_KEY = "hoa_db_path";

// Default to the existing HOA database created by the Python app.
// Users on other machines should set a custom path in Admin → Settings.
export const DEFAULT_DB_PATH = "sqlite:/Users/bob/hoa-system/data/hoa_accounting.db";

export function getConfiguredDbPath(): string {
  // Always use DEFAULT_DB_PATH; localStorage override disabled until
  // the Settings screen can reliably write a new path post-login.
  return DEFAULT_DB_PATH;
}

export function setConfiguredDbPath(path: string): void {
  localStorage.setItem(DB_PATH_KEY, path);
  _db = null; // force reconnect on next getDb() call
}

export function resetDb(): void {
  _db = null;
}

export async function getDb(): Promise<DbHandle> {
  if (_db) return _db;

  if (isTauri()) {
    // Native build — use Tauri's SQLite plugin.
    // Path is configurable via Settings; defaults to hoa.db in the app-data dir.
    const Database = (await import("@tauri-apps/plugin-sql")).default;
    _db = await Database.load(getConfiguredDbPath());
  } else {
    // Browser / Preview — use sql.js (in-memory; no file access in browser context).
    const { getBrowserDb } = await import("./db.browser");
    _db = await getBrowserDb();
  }

  await initSchema(_db);
  return _db;
}
