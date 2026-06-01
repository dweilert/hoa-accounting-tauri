import { getDb } from "../lib/db";

export type Announcement = {
  id: number;
  message: string;
  severity: "info" | "warning" | "urgent";
  expires_at: string | null;
  is_active: number;
  created_by: string | null;
  created_at: string;
};

export type AnnouncementFormValues = {
  message: string;
  severity: "info" | "warning" | "urgent";
  expires_at: string;
  is_active: number;
};

export async function listAnnouncements(): Promise<Announcement[]> {
  const db = await getDb();
  return db.select<Announcement[]>(
    "SELECT * FROM dashboard_announcements ORDER BY created_at DESC"
  );
}

export async function listActiveAnnouncements(): Promise<Announcement[]> {
  const db = await getDb();
  return db.select<Announcement[]>(
    `SELECT * FROM dashboard_announcements
     WHERE is_active = 1
       AND (expires_at IS NULL OR expires_at > datetime('now'))
     ORDER BY CASE severity WHEN 'urgent' THEN 1 WHEN 'warning' THEN 2 ELSE 3 END, created_at DESC`
  );
}

export async function createAnnouncement(
  values: AnnouncementFormValues,
  createdBy: string | null
): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO dashboard_announcements (message, severity, expires_at, is_active, created_by)
     VALUES (?, ?, ?, ?, ?)`,
    [
      values.message.trim(),
      values.severity,
      values.expires_at || null,
      values.is_active,
      createdBy,
    ]
  );
  return result.lastInsertId ?? 0;
}

export async function updateAnnouncement(
  id: number,
  values: AnnouncementFormValues
): Promise<void> {
  const db = await getDb();
  await db.execute(
    `UPDATE dashboard_announcements
     SET message = ?, severity = ?, expires_at = ?, is_active = ?
     WHERE id = ?`,
    [values.message.trim(), values.severity, values.expires_at || null, values.is_active, id]
  );
}

export async function deleteAnnouncement(id: number): Promise<void> {
  const db = await getDb();
  await db.execute("DELETE FROM dashboard_announcements WHERE id = ?", [id]);
}
