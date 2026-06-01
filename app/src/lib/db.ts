import Database from "@tauri-apps/plugin-sql";
import { initSchema } from "./schema";

let _db: Database | null = null;

export async function getDb(): Promise<Database> {
  if (_db) return _db;
  _db = await Database.load("sqlite:hoa.db");
  await initSchema(_db);
  return _db;
}
