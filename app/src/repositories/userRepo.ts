import { getDb } from "../lib/db";
import { hashPassword } from "../lib/auth";

export type LocalUser = {
  id: number;
  email: string;
  display_name: string;
  role: "admin" | "reports";
  password_hash: string;
  is_active: number;
  last_login_at: string | null;
  created_at: string;
};

export async function countActiveUsers(): Promise<number> {
  const db = await getDb();
  const rows = await db.select<[{ n: number }]>(
    "SELECT COUNT(*) as n FROM local_users WHERE is_active = 1"
  );
  return rows[0]?.n ?? 0;
}

export async function listUsers(): Promise<LocalUser[]> {
  const db = await getDb();
  return db.select<LocalUser[]>(
    "SELECT * FROM local_users ORDER BY email"
  );
}

export async function getUserByEmail(email: string): Promise<LocalUser | null> {
  const db = await getDb();
  const rows = await db.select<LocalUser[]>(
    "SELECT * FROM local_users WHERE email = ? COLLATE NOCASE",
    [email]
  );
  return rows[0] ?? null;
}

export async function createUser(
  email: string,
  displayName: string,
  role: "admin" | "reports",
  password: string
): Promise<number> {
  const db = await getDb();
  const hash = await hashPassword(password);
  const result = await db.execute(
    "INSERT INTO local_users (email, display_name, role, password_hash) VALUES (?, ?, ?, ?)",
    [email.trim().toLowerCase(), displayName.trim(), role, hash]
  );
  return result.lastInsertId ?? 0;
}

export async function updateUser(
  id: number,
  displayName: string,
  role: "admin" | "reports",
  isActive: boolean
): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE local_users SET display_name = ?, role = ?, is_active = ? WHERE id = ?",
    [displayName.trim(), role, isActive ? 1 : 0, id]
  );
}

export async function setPassword(id: number, password: string): Promise<void> {
  const db = await getDb();
  const hash = await hashPassword(password);
  await db.execute(
    "UPDATE local_users SET password_hash = ? WHERE id = ?",
    [hash, id]
  );
}

export async function recordLogin(id: number): Promise<void> {
  const db = await getDb();
  await db.execute(
    "UPDATE local_users SET last_login_at = datetime('now') WHERE id = ?",
    [id]
  );
}

export async function deleteUser(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM local_users WHERE id = ?", [id]);
}
