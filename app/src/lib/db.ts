import type { DbHandle } from "./dbTypes";
import { initSchema } from "./schema";
import { readConfig } from "./config";

let _db: DbHandle | null = null;

export function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function resetDb(): void {
  _db = null;
}

export async function getDb(): Promise<DbHandle> {
  if (_db) return _db;

  if (isTauri()) {
    const config = await readConfig();
    if (!config?.db_path) {
      throw new Error(
        "No database configured. Add a db_path entry to ~/hoa-system/tauri/config.json"
      );
    }
    const Database = (await import("@tauri-apps/plugin-sql")).default;
    _db = await Database.load(`sqlite:${config.db_path}`);
  } else {
    const { getBrowserDb } = await import("./db.browser");
    _db = await getBrowserDb();
  }

  await initSchema(_db);
  return _db;
}
