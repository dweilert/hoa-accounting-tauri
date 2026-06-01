import type { DbHandle } from "./dbTypes";

// sql.js Database type — imported lazily so it never loads in the Tauri build
type SqlJsDb = import("sql.js").Database;

class BrowserDatabase implements DbHandle {
  private db: SqlJsDb;

  constructor(db: SqlJsDb) {
    this.db = db;
  }

  static async open(): Promise<BrowserDatabase> {
    // Dynamic import keeps sql.js out of the Tauri bundle entirely
    const initSqlJs = (await import("sql.js")).default;
    const SQL = await initSqlJs({
      // WASM file is copied to public/ by scripts/copy-sqljs-wasm.cjs
      locateFile: (file: string) => `/${file}`,
    });
    return new BrowserDatabase(new SQL.Database());
  }

  async execute(
    sql: string,
    params: unknown[] = []
  ): Promise<{ rowsAffected: number; lastInsertId?: number }> {
    if (params.length === 0) {
      // No params — may be a multi-statement DDL block; exec() handles that
      this.db.exec(sql);
      return { rowsAffected: 0 };
    }

    const stmt = this.db.prepare(sql);
    try {
      stmt.run(params as Parameters<typeof stmt.run>[0]);
      const rowsAffected = this.db.getRowsModified();
      const rows = this.db.exec("SELECT last_insert_rowid()");
      const raw = rows[0]?.values[0]?.[0];
      const result: { rowsAffected: number; lastInsertId?: number } = { rowsAffected };
      if (typeof raw === "number") result.lastInsertId = raw;
      return result;
    } finally {
      stmt.free();
    }
  }

  async select<T>(sql: string, params: unknown[] = []): Promise<T> {
    const stmt = this.db.prepare(sql);
    try {
      if (params.length > 0) {
        stmt.bind(params as Parameters<typeof stmt.bind>[0]);
      }
      const rows: Record<string, unknown>[] = [];
      while (stmt.step()) {
        rows.push(stmt.getAsObject() as Record<string, unknown>);
      }
      return rows as unknown as T;
    } finally {
      stmt.free();
    }
  }
}

let _instance: BrowserDatabase | null = null;

export async function getBrowserDb(): Promise<DbHandle> {
  if (!_instance) _instance = await BrowserDatabase.open();
  return _instance;
}
