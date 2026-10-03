import { useEffect, useState } from "react";
import { PageLayout } from "../components/PageLayout";
import { getDb } from "../lib/db";
import { readConfig, writeConfig } from "../lib/config";
import { pushDbBackup } from "../lib/s3";
import { appAlert } from "../components/AppDialogs";

const IS_TAURI = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

// ── Settings types ─────────────────────────────────────────────────────────────

type OrgSettings = {
  org_name: string;
  fiscal_year_start_month: string;
  currency: string;
  timezone: string;
};

type DuesSettings = {
  dues_cycle: string;
  dues_amount: string;
  dues_days_before_due: string;
  dues_days_before_late: string;
};

const ORG_DEFAULTS: OrgSettings = {
  org_name: "",
  fiscal_year_start_month: "1",
  currency: "USD",
  timezone: "America/Chicago",
};

const DUES_DEFAULTS: DuesSettings = {
  dues_cycle: "MONTHLY",
  dues_amount: "",
  dues_days_before_due: "30",
  dues_days_before_late: "15",
};

const MONTH_NAMES = [
  "January", "February", "March", "April", "May", "June",
  "July", "August", "September", "October", "November", "December",
];

const DUES_CYCLES = [
  { value: "MONTHLY",     label: "Monthly" },
  { value: "QUARTERLY",   label: "Quarterly" },
  { value: "SEMI_ANNUAL", label: "Semi-Annual" },
  { value: "ANNUAL",      label: "Annual" },
];

// ── Persistence helpers ────────────────────────────────────────────────────────

async function ensureSettingsTable(): Promise<void> {
  const db = await getDb();
  await db.execute(`CREATE TABLE IF NOT EXISTS app_settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)`);
}

async function loadAllSettings(): Promise<{ org: OrgSettings; dues: DuesSettings }> {
  const db = await getDb();
  await ensureSettingsTable();
  const rows = await db.select<Array<{ key: string; value: string }>>("SELECT key, value FROM app_settings");
  const map = new Map(rows.map((r) => [r.key, r.value]));
  return {
    org: {
      org_name:                map.get("org_name")                ?? ORG_DEFAULTS.org_name,
      fiscal_year_start_month: map.get("fiscal_year_start_month") ?? ORG_DEFAULTS.fiscal_year_start_month,
      currency:                map.get("currency")                ?? ORG_DEFAULTS.currency,
      timezone:                map.get("timezone")                ?? ORG_DEFAULTS.timezone,
    },
    dues: {
      dues_cycle:             map.get("dues_cycle")             ?? DUES_DEFAULTS.dues_cycle,
      dues_amount:            map.get("dues_amount")            ?? DUES_DEFAULTS.dues_amount,
      dues_days_before_due:   map.get("dues_days_before_due")   ?? DUES_DEFAULTS.dues_days_before_due,
      dues_days_before_late:  map.get("dues_days_before_late")  ?? DUES_DEFAULTS.dues_days_before_late,
    },
  };
}

async function persistSettings(entries: Record<string, string>): Promise<void> {
  const db = await getDb();
  await ensureSettingsTable();
  for (const [key, value] of Object.entries(entries)) {
    await db.execute(
      "INSERT INTO app_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
      [key, value]
    );
  }
}

// ── Tab: Data / Database ───────────────────────────────────────────────────────

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
        <button onClick={handleSave}
          className="px-3 py-1.5 text-xs bg-blue-600 text-white rounded hover:bg-blue-700 whitespace-nowrap">
          Save
        </button>
      </div>
      {saved && <p className="text-xs text-green-600">✓ Saved — restart to reconnect.</p>}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  );
}

const EXPORT_TABLES = [
  "lots", "owners", "lot_ownership", "bank_accounts", "categories", "vendors",
  "assessments", "payments", "deposit_batches", "vendor_bills", "bill_payments",
  "bank_transactions", "bank_reconciliations", "budgets", "budget_lines",
  "opening_balances", "income_batches", "audit_log",
];

function DatabaseAdminSection() {
  const [vacuumResult, setVacuumResult]     = useState<string | null>(null);
  const [integrityResult, setIntegrityResult] = useState<string | null>(null);
  const [running, setRunning]               = useState<"vacuum" | "integrity" | "export" | null>(null);
  const [exportTable, setExportTable]       = useState(EXPORT_TABLES[0] ?? "lots");

  async function handleVacuum() {
    setRunning("vacuum"); setVacuumResult(null);
    try { const db = await getDb(); await db.execute("VACUUM"); setVacuumResult("✓ VACUUM completed."); }
    catch (e) { setVacuumResult(`✗ ${String(e)}`); }
    finally { setRunning(null); }
  }

  async function handleIntegrity() {
    setRunning("integrity"); setIntegrityResult(null);
    try {
      const db = await getDb();
      const rows = await db.select<{ integrity_check: string }[]>("PRAGMA integrity_check");
      const msg = rows.map((r) => r.integrity_check).join(", ");
      setIntegrityResult(msg === "ok" ? "✓ Integrity check passed." : `Issues: ${msg}`);
    } catch (e) { setIntegrityResult(`✗ ${String(e)}`); }
    finally { setRunning(null); }
  }

  async function handleExport() {
    setRunning("export");
    try {
      const db = await getDb();
      const rows = await db.select<Record<string, unknown>[]>(`SELECT * FROM ${exportTable}`);
      if (rows.length === 0) { await appAlert(`No rows in ${exportTable}.`); return; }
      const headers = Object.keys(rows[0] ?? {});
      const escape = (v: unknown) => {
        const s = v === null || v === undefined ? "" : String(v);
        return s.includes(",") || s.includes('"') || s.includes("\n") ? `"${s.replace(/"/g, '""')}"` : s;
      };
      const csv = [headers.join(","), ...rows.map((r) => headers.map((h) => escape(r[h])).join(","))].join("\n");
      const blob = new Blob([csv], { type: "text/csv" });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a"); a.href = url; a.download = `${exportTable}_export.csv`; a.click();
      URL.revokeObjectURL(url);
    } catch (e) { await appAlert(String(e)); }
    finally { setRunning(null); }
  }

  return (
    <div className="bg-white border rounded-lg p-5 space-y-4">
      <h2 className="font-semibold text-gray-800 text-sm">Database Admin</h2>
      <div className="flex flex-wrap gap-3 items-start">
        <div>
          <button onClick={() => void handleVacuum()} disabled={running !== null}
            className="px-3 py-1.5 text-xs bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50">
            {running === "vacuum" ? "Running…" : "VACUUM"}
          </button>
          {vacuumResult && <p className={`mt-1 text-xs ${vacuumResult.startsWith("✓") ? "text-green-700" : "text-red-600"}`}>{vacuumResult}</p>}
          <p className="text-xs text-gray-400 mt-0.5">Reclaim space, rebuild indexes</p>
        </div>
        <div>
          <button onClick={() => void handleIntegrity()} disabled={running !== null}
            className="px-3 py-1.5 text-xs bg-gray-600 text-white rounded hover:bg-gray-700 disabled:opacity-50">
            {running === "integrity" ? "Checking…" : "Integrity Check"}
          </button>
          {integrityResult && <p className={`mt-1 text-xs ${integrityResult.startsWith("✓") ? "text-green-700" : "text-red-600"}`}>{integrityResult}</p>}
          <p className="text-xs text-gray-400 mt-0.5">Verify database structure</p>
        </div>
      </div>
      <div className="border-t pt-3">
        <p className="text-xs font-medium text-gray-700 mb-2">Export Table to CSV</p>
        <div className="flex items-center gap-2">
          <select value={exportTable} onChange={(e) => setExportTable(e.target.value)}
            className="border border-gray-300 rounded px-2 py-1.5 text-xs bg-white">
            {EXPORT_TABLES.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <button onClick={() => void handleExport()} disabled={running !== null}
            className="px-3 py-1.5 text-xs bg-teal-600 text-white rounded hover:bg-teal-700 disabled:opacity-50">
            {running === "export" ? "Exporting…" : "Download CSV"}
          </button>
        </div>
      </div>
    </div>
  );
}

function S3BackupSection() {
  const [running, setRunning] = useState(false);
  const [result, setResult]   = useState<{ ok: boolean; message: string } | null>(null);

  async function handleBackup() {
    setRunning(true); setResult(null);
    const r = await pushDbBackup();
    setResult(r); setRunning(false);
  }

  return (
    <div className="bg-white border rounded-lg p-5 space-y-3">
      <div>
        <h2 className="font-semibold text-gray-800 text-sm">Database Backup (S3)</h2>
        <p className="text-xs text-gray-500 mt-0.5">
          Encrypts and uploads the HOA database to Amazon S3. Requires{" "}
          <code className="bg-gray-100 px-1 rounded">~/hoa-system/tauri/s3_config.json</code>.
        </p>
      </div>
      <button onClick={handleBackup} disabled={running}
        className="px-4 py-2 bg-indigo-600 text-white text-sm rounded hover:bg-indigo-700 disabled:opacity-50">
        {running ? "Backing up…" : "Backup to S3 Now"}
      </button>
      {result && (
        <p className={`text-xs ${result.ok ? "text-green-700" : "text-red-600"}`}>
          {result.ok ? "✓ " : "✗ "}{result.message}
        </p>
      )}
    </div>
  );
}

function DataTab() {
  return (
    <div className="space-y-5 max-w-xl">
      {IS_TAURI ? (
        <>
          <DbPathSection />
          <S3BackupSection />
        </>
      ) : (
        <div className="bg-blue-50 border border-blue-200 rounded-lg p-4">
          <p className="text-xs text-blue-700 font-medium">Preview mode — in-memory database</p>
          <p className="text-xs text-blue-600 mt-1">
            Database file configuration is only available in the native desktop app.
          </p>
        </div>
      )}
      <DatabaseAdminSection />
    </div>
  );
}

// ── Tab: Organization ──────────────────────────────────────────────────────────

function OrgTab({ initial }: { initial: OrgSettings }) {
  const [settings, setSettings] = useState<OrgSettings>(initial);
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const set = <K extends keyof OrgSettings>(k: K, v: OrgSettings[K]) =>
    setSettings((p) => ({ ...p, [k]: v }));

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setSaved(false);
    try {
      await persistSettings(settings as unknown as Record<string, string>);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSave} className="space-y-5 max-w-xl">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="bg-white border rounded-lg p-5 space-y-4">
        <h2 className="font-semibold text-gray-800 text-sm">Organization</h2>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">HOA / Organization Name</label>
          <input type="text" value={settings.org_name} onChange={(e) => set("org_name", e.target.value)}
            placeholder="e.g. Sunny Acres HOA"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      <div className="bg-white border rounded-lg p-5 space-y-4">
        <h2 className="font-semibold text-gray-800 text-sm">Fiscal Year</h2>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Fiscal Year Start Month</label>
          <select value={settings.fiscal_year_start_month} onChange={(e) => set("fiscal_year_start_month", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            {MONTH_NAMES.map((m, i) => <option key={i + 1} value={String(i + 1)}>{m}</option>)}
          </select>
        </div>
      </div>

      <div className="bg-white border rounded-lg p-5 space-y-4">
        <h2 className="font-semibold text-gray-800 text-sm">Regional</h2>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Currency</label>
          <select value={settings.currency} onChange={(e) => set("currency", e.target.value)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
            <option value="USD">USD — US Dollar</option>
            <option value="CAD">CAD — Canadian Dollar</option>
            <option value="EUR">EUR — Euro</option>
            <option value="GBP">GBP — British Pound</option>
          </select>
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Timezone</label>
          <input type="text" value={settings.timezone} onChange={(e) => set("timezone", e.target.value)}
            placeholder="e.g. America/Chicago"
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
        </div>
      </div>

      <div className="flex items-center gap-4">
        <button type="submit" disabled={saving}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && <span className="text-sm text-green-600">✓ Saved</span>}
      </div>
    </form>
  );
}

// ── Tab: Default Dues ──────────────────────────────────────────────────────────

function DuesTab({ initial }: { initial: DuesSettings }) {
  const [settings, setSettings] = useState<DuesSettings>(initial);
  const [saving, setSaving]     = useState(false);
  const [saved, setSaved]       = useState(false);
  const [error, setError]       = useState<string | null>(null);

  const set = <K extends keyof DuesSettings>(k: K, v: DuesSettings[K]) =>
    setSettings((p) => ({ ...p, [k]: v }));

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true); setSaved(false);
    try {
      await persistSettings(settings as unknown as Record<string, string>);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) { setError(String(e)); }
    finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSave} className="space-y-5 max-w-xl">
      {error && <p className="text-sm text-red-600">{error}</p>}

      <div className="bg-white border rounded-lg p-5 space-y-4">
        <div>
          <h2 className="font-semibold text-gray-800 text-sm">Default Dues</h2>
          <p className="text-xs text-gray-500 mt-0.5">
            Used as defaults when billing lots. Individual billing runs can override these.
          </p>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Billing Cycle</label>
            <select value={settings.dues_cycle} onChange={(e) => set("dues_cycle", e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {DUES_CYCLES.map((c) => <option key={c.value} value={c.value}>{c.label}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Amount Per Lot</label>
            <div className="relative">
              <span className="absolute left-3 top-1/2 -translate-y-1/2 text-gray-400 text-sm">$</span>
              <input type="number" step="0.01" min="0" value={settings.dues_amount}
                onChange={(e) => set("dues_amount", e.target.value)}
                placeholder="0.00"
                className="w-full border border-gray-300 rounded pl-6 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>
        </div>

        <div className="border-t pt-4 grid grid-cols-2 gap-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Days Before Due</label>
            <p className="text-xs text-gray-400 mb-1.5">Days after assessment date that payment is due</p>
            <div className="relative">
              <input type="number" min="0" step="1" value={settings.dues_days_before_due}
                onChange={(e) => set("dues_days_before_due", e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">days</span>
            </div>
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Days Before Late</label>
            <p className="text-xs text-gray-400 mb-1.5">Days after due date before a late fee applies</p>
            <div className="relative">
              <input type="number" min="0" step="1" value={settings.dues_days_before_late}
                onChange={(e) => set("dues_days_before_late", e.target.value)}
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <span className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">days</span>
            </div>
          </div>
        </div>

        {settings.dues_amount && settings.dues_days_before_due && settings.dues_days_before_late && (
          <div className="bg-gray-50 rounded p-3 text-xs text-gray-600 border">
            <span className="font-medium">Summary: </span>
            {DUES_CYCLES.find((c) => c.value === settings.dues_cycle)?.label ?? settings.dues_cycle} dues of{" "}
            <span className="font-medium">${Number(settings.dues_amount).toFixed(2)}</span> per lot,
            due <span className="font-medium">{settings.dues_days_before_due} days</span> after billing,
            late fee after <span className="font-medium">{settings.dues_days_before_late} days</span> past due.
          </div>
        )}
      </div>

      <div className="flex items-center gap-4">
        <button type="submit" disabled={saving}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50">
          {saving ? "Saving…" : "Save"}
        </button>
        {saved && <span className="text-sm text-green-600">✓ Saved</span>}
      </div>
    </form>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

type TabKey = "data" | "org" | "dues";

const TABS: { key: TabKey; label: string }[] = [
  { key: "data", label: "Data / Database" },
  { key: "org",  label: "Organization" },
  { key: "dues", label: "Default Dues" },
];

export function SettingsScreen() {
  const [tab, setTab]       = useState<TabKey>("org");
  const [org, setOrg]       = useState<OrgSettings>(ORG_DEFAULTS);
  const [dues, setDues]     = useState<DuesSettings>(DUES_DEFAULTS);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState<string | null>(null);

  useEffect(() => {
    loadAllSettings()
      .then(({ org, dues }) => { setOrg(org); setDues(dues); })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;

  return (
    <PageLayout title="Settings" subtitle="Organization configuration and database tools." helpId="settings">
      <div>
        {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

        <div className="flex gap-1 border-b border-gray-200 mb-6">
          {TABS.map((t) => (
            <button key={t.key} onClick={() => setTab(t.key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors -mb-px ${
                tab === t.key
                  ? "border-blue-600 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}>
              {t.label}
            </button>
          ))}
        </div>

        {tab === "data" && <DataTab />}
        {tab === "org"  && <OrgTab  initial={org} />}
        {tab === "dues" && <DuesTab initial={dues} />}
      </div>
    </PageLayout>
  );
}
