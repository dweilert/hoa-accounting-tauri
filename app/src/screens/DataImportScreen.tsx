import { useState } from "react";
import { PageLayout } from "../components/PageLayout";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type ImportTarget = "lots" | "owners" | "payments";

type FieldDef = { key: string; label: string; required: boolean; hint?: string };

const FIELD_DEFS: Record<ImportTarget, FieldDef[]> = {
  lots: [
    { key: "lot_number",       label: "Lot Number",    required: true,  hint: "e.g. 101" },
    { key: "street_address_1", label: "Street Address",required: false },
    { key: "city",             label: "City",          required: false },
    { key: "state",            label: "State",         required: false },
    { key: "postal_code",      label: "ZIP",           required: false },
  ],
  owners: [
    { key: "display_name",     label: "Display Name",  required: true,  hint: "Full name for mailing" },
    { key: "first_name",       label: "First Name",    required: false },
    { key: "last_name",        label: "Last Name",     required: false },
    { key: "email",            label: "Email",         required: false },
    { key: "phone",            label: "Phone",         required: false },
    { key: "mailing_address_1",label: "Address",       required: false },
    { key: "city",             label: "City",          required: false },
    { key: "state",            label: "State",         required: false },
    { key: "postal_code",      label: "ZIP",           required: false },
    { key: "lot_number",       label: "Lot Number",    required: false, hint: "Links owner to an existing lot" },
  ],
  payments: [
    { key: "lot_number",       label: "Lot Number",    required: true },
    { key: "payment_date",     label: "Payment Date",  required: true,  hint: "YYYY-MM-DD" },
    { key: "amount",           label: "Amount",        required: true,  hint: "Positive number" },
    { key: "check_number",     label: "Check / Ref #", required: false },
    { key: "memo",             label: "Memo",          required: false },
  ],
};

// ── CSV parse ─────────────────────────────────────────────────────────────────

function parseCSV(text: string): { headers: string[]; rows: string[][] } {
  const lines = text.trim().split(/\r?\n/);
  const parse = (line: string) => {
    const result: string[] = [];
    let cur = "";
    let inQuote = false;
    for (const ch of line) {
      if (ch === '"') { inQuote = !inQuote; continue; }
      if (ch === "," && !inQuote) { result.push(cur.trim()); cur = ""; continue; }
      cur += ch;
    }
    result.push(cur.trim());
    return result;
  };
  const headers = parse(lines[0] ?? "");
  const rows = lines.slice(1).filter((l) => l.trim()).map(parse);
  return { headers, rows };
}

function autoDetect(headers: string[], fields: FieldDef[]): Record<string, number> {
  const h = headers.map((s) => s.toLowerCase().trim());
  const result: Record<string, number> = {};
  for (const f of fields) {
    const terms = [f.key.toLowerCase(), f.label.toLowerCase(), ...f.key.toLowerCase().split("_")];
    const idx = h.findIndex((hh) => terms.some((t) => hh.includes(t)));
    if (idx >= 0) result[f.key] = idx;
  }
  return result;
}

// ── Import logic ──────────────────────────────────────────────────────────────

type PreviewRow = { _rowNum: number; _error?: string; [key: string]: string | number | undefined };

function buildPreviewRows(
  rows: string[][],
  mapping: Record<string, number>,
  fields: FieldDef[]
): PreviewRow[] {
  return rows.map((row, i) => {
    const obj: PreviewRow = { _rowNum: i + 2 };
    for (const f of fields) {
      const colIdx = mapping[f.key];
      obj[f.key] = colIdx !== undefined && colIdx >= 0 ? (row[colIdx] ?? "").trim() : "";
    }
    const missing = fields.filter((f) => f.required && !obj[f.key]);
    if (missing.length > 0) obj._error = `Missing: ${missing.map((f) => f.label).join(", ")}`;
    return obj;
  });
}

async function importLots(rows: PreviewRow[]): Promise<{ inserted: number; skipped: number }> {
  const db = await getDb();
  let inserted = 0, skipped = 0;
  for (const r of rows) {
    if (r._error) { skipped++; continue; }
    try {
      await db.execute(
        `INSERT OR IGNORE INTO lots (lot_number, street_address_1, city, state, postal_code)
         VALUES (?,?,?,?,?)`,
        [r.lot_number, r.street_address_1 || null, r.city || null, r.state || null, r.postal_code || null]
      );
      inserted++;
    } catch { skipped++; }
  }
  return { inserted, skipped };
}

async function importOwners(rows: PreviewRow[]): Promise<{ inserted: number; skipped: number }> {
  const db = await getDb();
  let inserted = 0, skipped = 0;
  for (const r of rows) {
    if (r._error) { skipped++; continue; }
    try {
      const result = await db.execute(
        `INSERT INTO owners (display_name, first_name, last_name, email, phone, mailing_address_1, city, state, postal_code)
         VALUES (?,?,?,?,?,?,?,?,?)`,
        [r.display_name, r.first_name || null, r.last_name || null, r.email || null, r.phone || null,
         r.mailing_address_1 || null, r.city || null, r.state || null, r.postal_code || null]
      );
      const ownerId = result.lastInsertId as number;
      // Link to lot if lot_number provided
      if (r.lot_number) {
        const lotRows = await db.select<{ id: number }[]>(
          "SELECT id FROM lots WHERE lot_number=? LIMIT 1", [r.lot_number]
        );
        if (lotRows[0]) {
          await db.execute(
            `INSERT OR IGNORE INTO lot_ownership (lot_id, owner_id, start_date, ownership_percent)
             VALUES (?,?,date('now'),100)`,
            [lotRows[0].id, ownerId]
          );
        }
      }
      inserted++;
    } catch { skipped++; }
  }
  return { inserted, skipped };
}

async function importPayments(rows: PreviewRow[]): Promise<{ inserted: number; skipped: number }> {
  const db = await getDb();
  // Find or create a default import deposit batch
  let batchId: number;
  const batchRows = await db.select<{ id: number }[]>(
    "SELECT id FROM deposit_batches WHERE status='OPEN' ORDER BY id DESC LIMIT 1"
  );
  if (batchRows[0]) {
    batchId = batchRows[0].id;
  } else {
    // Find first bank account
    const acctRows = await db.select<{ id: number }[]>("SELECT id FROM bank_accounts WHERE active_flag=1 LIMIT 1");
    if (!acctRows[0]) throw new Error("No active bank account found — add one first.");
    const result = await db.execute(
      `INSERT INTO deposit_batches (bank_account_id, deposit_date, status, description)
       VALUES (?,date('now'),'OPEN','CSV Import')`,
      [acctRows[0].id]
    );
    batchId = result.lastInsertId as number;
  }

  let inserted = 0, skipped = 0;
  for (const r of rows) {
    if (r._error) { skipped++; continue; }
    const amount = parseFloat(String(r.amount ?? ""));
    if (isNaN(amount) || amount <= 0) { skipped++; continue; }
    try {
      const lotRows = await db.select<{ id: number }[]>(
        "SELECT id FROM lots WHERE lot_number=? LIMIT 1", [r.lot_number]
      );
      if (!lotRows[0]) { skipped++; continue; }
      await db.execute(
        `INSERT INTO payments (lot_id, deposit_batch_id, payment_date, amount, check_number, memo)
         VALUES (?,?,?,?,?,?)`,
        [lotRows[0].id, batchId, r.payment_date, amount, r.check_number || null, r.memo || null]
      );
      inserted++;
    } catch { skipped++; }
  }
  return { inserted, skipped };
}

// ── Screen ────────────────────────────────────────────────────────────────────

type Step = "choose" | "upload" | "map" | "preview" | "done";

export function DataImportScreen() {
  const [step, setStep] = useState<Step>("choose");
  const [target, setTarget] = useState<ImportTarget>("lots");
  const [fileText, setFileText] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, number>>({});
  const [preview, setPreview] = useState<PreviewRow[]>([]);
  const [result, setResult] = useState<{ inserted: number; skipped: number } | null>(null);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fields = FIELD_DEFS[target];
  const validRows = preview.filter((r) => !r._error);
  const badRows = preview.filter((r) => r._error);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      setFileText(text);
      const { headers: h } = parseCSV(text);
      setHeaders(h);
      setMapping(autoDetect(h, fields));
      setStep("map");
    };
    reader.readAsText(file);
  }

  function handleBuildPreview() {
    const { rows } = parseCSV(fileText);
    setPreview(buildPreviewRows(rows, mapping, fields));
    setStep("preview");
  }

  async function handleImport() {
    setImporting(true);
    setError(null);
    try {
      let r: { inserted: number; skipped: number };
      if (target === "lots") r = await importLots(validRows);
      else if (target === "owners") r = await importOwners(validRows);
      else r = await importPayments(validRows);
      setResult(r);
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setImporting(false);
    }
  }

  function reset() {
    setStep("choose");
    setFileText("");
    setHeaders([]);
    setMapping({});
    setPreview([]);
    setResult(null);
    setError(null);
  }

  const STEP_LABELS: Step[] = ["choose", "upload", "map", "preview"];
  const stepIdx = STEP_LABELS.indexOf(step);

  return (
    <PageLayout title="Data Import" subtitle="Bulk import lots, owners, or payments from CSV." helpId="dataImport">
    <div className="max-w-4xl">
      {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

      {step !== "done" && (
        <div className="flex gap-4 mb-6 text-xs">
          {(["Target", "Upload", "Map", "Preview"] as const).map((label, i) => (
            <div key={label} className="flex items-center gap-1.5">
              <span className={`w-5 h-5 rounded-full flex items-center justify-center font-bold ${i <= stepIdx ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500"}`}>
                {i + 1}
              </span>
              <span className={i === stepIdx ? "text-blue-600 font-medium" : "text-gray-400"}>{label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Step 1: Choose target */}
      {step === "choose" && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">What would you like to import?</p>
          {(["lots","owners","payments"] as ImportTarget[]).map((t) => (
            <button
              key={t}
              onClick={() => { setTarget(t); setStep("upload"); }}
              className="w-full text-left px-4 py-3 bg-white border rounded-lg hover:bg-blue-50 hover:border-blue-300 transition-colors"
            >
              <p className="font-semibold text-gray-900 capitalize">{t}</p>
              <p className="text-xs text-gray-500 mt-0.5">
                {t === "lots" ? "Import lot numbers and addresses from a spreadsheet." :
                 t === "owners" ? "Import owner names, contact info, and optionally link to lots." :
                 "Import historical payment records by lot number."}
              </p>
            </button>
          ))}
        </div>
      )}

      {/* Step 2: Upload */}
      {step === "upload" && (
        <div className="space-y-4">
          <div className="bg-blue-50 border border-blue-200 rounded p-3 text-xs text-blue-800">
            <p className="font-semibold mb-1">Expected columns for {target} import:</p>
            <p>{fields.map((f) => `${f.label}${f.required ? " *" : ""}`).join(", ")}</p>
            <p className="mt-1 text-blue-600">* = required. Column names don't need to match exactly — you'll map them in the next step.</p>
          </div>
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
            <input type="file" accept=".csv,.txt" onChange={handleFile} className="hidden" id="import-upload" />
            <label htmlFor="import-upload" className="cursor-pointer">
              <div className="text-4xl mb-2">📄</div>
              <p className="text-sm font-medium text-blue-600">Click to select a CSV file</p>
              <p className="text-xs text-gray-400 mt-1">Exported from Excel, Google Sheets, or any spreadsheet</p>
            </label>
          </div>
          <button onClick={() => setStep("choose")} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
        </div>
      )}

      {/* Step 3: Map columns */}
      {step === "map" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">Map your CSV columns to the import fields. Auto-detected values are shown.</p>
          <div className="bg-white border rounded-lg p-4 space-y-3">
            {fields.map((f) => (
              <div key={f.key} className="grid grid-cols-2 gap-4 items-center">
                <div>
                  <p className="text-sm font-medium text-gray-700">
                    {f.label}{f.required && <span className="text-red-500 ml-1">*</span>}
                  </p>
                  {f.hint && <p className="text-xs text-gray-400">{f.hint}</p>}
                </div>
                <select
                  value={mapping[f.key] !== undefined ? String(mapping[f.key]) : "-1"}
                  onChange={(e) => setMapping((p) => ({ ...p, [f.key]: Number(e.target.value) }))}
                  className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="-1">— Not mapped —</option>
                  {headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
                </select>
              </div>
            ))}
          </div>
          <div className="flex gap-3">
            <button onClick={handleBuildPreview} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
              Preview →
            </button>
            <button onClick={reset} className="text-sm text-gray-500 hover:text-gray-800">Cancel</button>
          </div>
        </div>
      )}

      {/* Step 4: Preview */}
      {step === "preview" && (
        <div className="space-y-4">
          <div className="flex gap-4 text-sm">
            <span className="text-green-700 font-medium">{validRows.length} valid rows</span>
            {badRows.length > 0 && <span className="text-red-600">{badRows.length} rows with errors (will be skipped)</span>}
          </div>

          <div className="border rounded-lg overflow-hidden max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b sticky top-0">
                <tr>
                  <th className="px-2 py-2 text-left text-gray-600">#</th>
                  {fields.map((f) => (
                    <th key={f.key} className="px-2 py-2 text-left text-gray-600">{f.label}</th>
                  ))}
                  <th className="px-2 py-2 text-left text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {preview.map((row) => (
                  <tr key={row._rowNum} className={row._error ? "bg-red-50" : ""}>
                    <td className="px-2 py-1.5 text-gray-400">{row._rowNum}</td>
                    {fields.map((f) => (
                      <td key={f.key} className="px-2 py-1.5 text-gray-700 max-w-[8rem] truncate">
                        {row[f.key] || <span className="text-gray-300">—</span>}
                      </td>
                    ))}
                    <td className="px-2 py-1.5">
                      {row._error
                        ? <span className="text-red-600 text-xs">{row._error}</span>
                        : <span className="text-green-600 text-xs">✓</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => void handleImport()}
              disabled={importing || validRows.length === 0}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {importing ? "Importing…" : `Import ${validRows.length} Row${validRows.length !== 1 ? "s" : ""}`}
            </button>
            <button onClick={() => setStep("map")} className="text-sm text-gray-500 hover:text-gray-800">← Back</button>
          </div>
        </div>
      )}

      {/* Done */}
      {step === "done" && result && (
        <div className="text-center py-10">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-xl font-semibold text-green-700 mb-2">Import Complete</h2>
          <p className="text-sm text-gray-700">
            <strong>{result.inserted}</strong> {target} imported successfully.
            {result.skipped > 0 && <> <strong>{result.skipped}</strong> rows skipped (errors or duplicates).</>}
          </p>
          <div className="mt-6 flex justify-center gap-3">
            <button onClick={reset} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
              Import More
            </button>
          </div>
        </div>
      )}
    </div>
    </PageLayout>
  );
}
