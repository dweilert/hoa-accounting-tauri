import { useEffect, useState } from "react";
import { getDb, getConfiguredDbPath, setConfiguredDbPath, DEFAULT_DB_PATH } from "../lib/db";

const IS_TAURI = typeof window !== "undefined" && "__TAURI__" in window;

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
  const [path, setPath] = useState(getConfiguredDbPath());
  const [manualPath, setManualPath] = useState(getConfiguredDbPath());
  const [saved, setSaved] = useState(false);
  const [reloadNeeded, setReloadNeeded] = useState(false);

  async function pickFile() {
    // Tauri dialog — open a file picker for .db files
    try {
      const { open } = await import("@tauri-apps/plugin-dialog");
      const selected = await open({
        title: "Select HOA Database File",
        filters: [{ name: "SQLite Database", extensions: ["db", "sqlite", "sqlite3"] }],
        multiple: false,
      });
      if (typeof selected === "string" && selected) {
        // Tauri SQL plugin expects "sqlite:/absolute/path" for absolute paths
        const tauriPath = selected.startsWith("sqlite:") ? selected : `sqlite:${selected}`;
        setManualPath(tauriPath);
        applyPath(tauriPath);
      }
    } catch (e) {
      alert(`Could not open file picker: ${String(e)}`);
    }
  }

  function applyPath(p: string) {
    setConfiguredDbPath(p);
    setPath(p);
    setSaved(true);
    setReloadNeeded(true);
    setTimeout(() => setSaved(false), 3000);
  }

  function handleManualApply() {
    applyPath(manualPath);
  }

  function resetToDefault() {
    setManualPath(DEFAULT_DB_PATH);
    applyPath(DEFAULT_DB_PATH);
  }

  const isDefault = path === DEFAULT_DB_PATH;

  return (
    <div className="bg-white border rounded-lg p-5 space-y-3">
      <div>
        <h2 className="font-semibold text-gray-800 text-sm">Database File</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Point the app at an existing HOA database. Restart or reload the app after changing.
        </p>
      </div>

      <div className="flex items-center gap-2">
        <input
          type="text"
          value={manualPath}
          onChange={(e) => setManualPath(e.target.value)}
          placeholder="sqlite:hoa.db or sqlite:/path/to/hoa_accounting.db"
          className="flex-1 border border-gray-300 rounded px-3 py-1.5 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
        <button
          onClick={handleManualApply}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 whitespace-nowrap"
        >
          Apply
        </button>
        <button
          onClick={() => void pickFile()}
          className="px-3 py-1.5 text-xs border border-gray-300 text-gray-600 rounded hover:bg-gray-50 whitespace-nowrap"
        >
          Browse…
        </button>
      </div>

      {!isDefault && (
        <button onClick={resetToDefault} className="text-xs text-gray-400 hover:text-gray-600 hover:underline">
          Reset to default (sqlite:hoa.db)
        </button>
      )}

      {saved && <p className="text-xs text-green-600">✓ Path saved.</p>}
      {reloadNeeded && (
        <p className="text-xs text-amber-600">
          ⚠ Reload or restart the app to connect to the new database.
        </p>
      )}

      <div className="text-xs text-gray-400 bg-gray-50 rounded p-2 space-y-1">
        <p><strong>Current path:</strong> <span className="font-mono">{path}</span></p>
        <p>
          To use the existing HOA database, set the path to{" "}
          <code className="bg-gray-100 px-1 rounded">sqlite:/Users/bob/hoa-system/data/hoa_accounting.db</code>
        </p>
      </div>
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
            to your existing HOA database at{" "}
            <code className="bg-blue-100 px-1 rounded">/Users/bob/hoa-system/data/hoa_accounting.db</code>.
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
