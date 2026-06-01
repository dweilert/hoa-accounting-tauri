import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { readConfig, writeConfig } from "../lib/config";

const IS_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type OrgSettings = {
  org_name: string;
  fiscal_year_start_month: string;
  currency: string;
  timezone: string;
};

const DEFAULTS: OrgSettings = {
  org_name: "",
  fiscal_year_start_month: "1",
  currency: "USD",
  timezone: "America/Chicago",
};

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

async function ensureSettingsTable(): Promise<void> {
  const db = await getDb();
  await db.execute(`
    CREATE TABLE IF NOT EXISTS app_settings (
      key   TEXT PRIMARY KEY,
      value TEXT NOT NULL
    )
  `);
}

async function loadSettings(): Promise<OrgSettings> {
  const db = await getDb();
  await ensureSettingsTable();
  const rows = await db.select<Array<{ key: string; value: string }>>("SELECT key, value FROM app_settings");
  const map = new Map(rows.map((r) => [r.key, r.value]));
  return {
    org_name: map.get("org_name") ?? DEFAULTS.org_name,
    fiscal_year_start_month: map.get("fiscal_year_start_month") ?? DEFAULTS.fiscal_year_start_month,
    currency: map.get("currency") ?? DEFAULTS.currency,
    timezone: map.get("timezone") ?? DEFAULTS.timezone,
  };
}

async function saveSettings(settings: OrgSettings): Promise<void> {
  const db = await getDb();
  await ensureSettingsTable();
  for (const [key, value] of Object.entries(settings)) {
    await db.execute(
      "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
      [key, value]
    );
  }
}

// ── Database path section ─────────────────────────────────────────────────────

function DbPathSection() {
  const [path, setPath] = useState("");
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    readConfig().then((cfg) => { if (cfg?.db_path) setPath(cfg.db_path); });
  }, []);

  async function handleSave() {
    if (!path.trim()) return;
    try {
      const existing = await readConfig();
      await writeConfig({ ...existing, db_path: path.trim() });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(String(e));
    }
  }

  return (
    <div className="bg-white border rounded-lg p-5 space-y-3">
      <div>
        <h2 className="font-semibold text-gray-800 text-sm">Database File</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Absolute path to the HOA database. Saved to{" "}
          <code className="bg-gray-100 px-1 rounded">~/hoa-system/tauri/config.json</code>.
          Restart the app after changing.
        </p>
      </div>
      <div className="flex items-center gap-2">
        <input
          type="text"
          value={path}
          onChange={(e) => setPath(e.target.value)}
          placeholder="/Users/you/hoa-system/tauri/hoa.db"
          className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={handleSave}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 whitespace-nowrap"
        >
          Save
        </button>
      </div>
      {saved && <p className="text-xs text-green-600">✓ Saved to config.json — restart to reconnect.</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function SettingsScreen() {
  const [settings, setSettings] = useState<OrgSettings>(DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSettings()
      .then((s) => setSettings(s))
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  const set = <K extends keyof OrgSettings>(k: K, v: OrgSettings[K]) =>
    setSettings((p) => ({ ...p, [k]: v }));

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    setSaved(false);
    try {
      await saveSettings(settings);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  const inp = (label: string, field: keyof OrgSettings, placeholder?: string) => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        type="text"
        value={settings[field]}
        onChange={(e) => set(field, e.target.value)}
        placeholder={placeholder}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;

  return (
    <div className="p-8 max-w-xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Settings</h1>
        <p className="text-sm text-gray-500 mt-0.5">Organization configuration.</p>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Database path — native app only */}
      {IS_TAURI && (
        <div className="mb-5">
          <DbPathSection />
        </div>
      )}
      {!IS_TAURI && (
        <div className="mb-5 bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-xs text-blue-700 font-medium">Preview mode — in-memory database</p>
          <p className="text-xs text-blue-600 mt-1">
            The Preview panel uses an in-memory database that resets on reload. Database file
            configuration is only available in the native desktop app. Run{" "}
            <code className="bg-blue-100 px-1 rounded">npm run tauri:dev</code> to connect
            to your HOA database configured in{" "}
            <code className="bg-blue-100 px-1 rounded">~/hoa-system/tauri/config.json</code>.
          </p>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-5">
        <div className="bg-white border rounded-lg p-5 space-y-4">
          <h2 className="font-semibold text-gray-800 text-sm">Organization</h2>
          {inp("HOA / Organization Name", "org_name", "e.g. Sunny Acres HOA")}
        </div>

        <div className="bg-white border rounded-lg p-5 space-y-4">
          <h2 className="font-semibold text-gray-800 text-sm">Fiscal Year</h2>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Fiscal Year Start Month</label>
            <select
              value={settings.fiscal_year_start_month}
              onChange={(e) => set("fiscal_year_start_month", e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {MONTH_NAMES.map((m, i) => (
                <option key={i + 1} value={String(i + 1)}>{m}</option>
              ))}
            </select>
          </div>
        </div>

        <div className="bg-white border rounded-lg p-5 space-y-4">
          <h2 className="font-semibold text-gray-800 text-sm">Regional</h2>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Currency</label>
            <select
              value={settings.currency}
              onChange={(e) => set("currency", e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="USD">USD — US Dollar</option>
              <option value="CAD">CAD — Canadian Dollar</option>
              <option value="EUR">EUR — Euro</option>
              <option value="GBP">GBP — British Pound</option>
            </select>
          </div>
          {inp("Timezone", "timezone", "e.g. America/Chicago")}
        </div>

        <div className="flex items-center gap-4">
          <button
            type="submit"
            disabled={saving}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save Settings"}
          </button>
          {saved && <span className="text-sm text-green-600">✓ Saved</span>}
        </div>
      </form>
    </div>
  );
}
