import { getDb } from "../lib/db";

export type HoaSettings = {
  hoa_name: string;
  fiscal_year_start_month: number; // 1–12
  timezone: string;
  setup_complete: boolean;
};

export async function getHoaSettings(): Promise<HoaSettings> {
  const db = await getDb();
  const rows = await db.select<{ key: string; value: string }[]>(
    "SELECT key, value FROM app_settings WHERE key IN ('hoa_name','fiscal_year_start_month','timezone','setup_complete')"
  );
  const map = new Map(rows.map((r) => [r.key, r.value]));
  return {
    hoa_name: map.get("hoa_name") ?? "",
    fiscal_year_start_month: Number(map.get("fiscal_year_start_month") ?? "1"),
    timezone: map.get("timezone") ?? "America/Chicago",
    setup_complete: map.get("setup_complete") === "1",
  };
}

export async function saveSetting(key: string, value: string): Promise<void> {
  const db = await getDb();
  await db.execute(
    "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
    [key, value]
  );
}

export async function saveHoaIdentity(
  hoaName: string,
  fiscalYearStartMonth: number,
  timezone: string
): Promise<void> {
  await saveSetting("hoa_name", hoaName);
  await saveSetting("fiscal_year_start_month", String(fiscalYearStartMonth));
  await saveSetting("timezone", timezone);
}

export async function markSetupComplete(): Promise<void> {
  await saveSetting("setup_complete", "1");
}

export async function isSetupComplete(): Promise<boolean> {
  const db = await getDb();
  const rows = await db.select<{ value: string }[]>(
    "SELECT value FROM app_settings WHERE key = 'setup_complete'"
  );
  return rows[0]?.value === "1";
}
