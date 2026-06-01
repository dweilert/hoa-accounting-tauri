import { useState } from "react";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { insertBankTransaction } from "../repositories/reconciliationRepo";
import type { BankAccount } from "../types/bankAccount";

type ParsedRow = {
  date: string;
  amount: number;
  description: string;
  raw: string;
};

type ColMap = { date: number; amount: number | null; debit: number | null; credit: number | null; description: number };

function detectColumns(headers: string[]): ColMap {
  const h = headers.map((s) => s.toLowerCase().trim());
  const idx = (terms: string[]) => {
    for (const t of terms) {
      const i = h.findIndex((x) => x.includes(t));
      if (i >= 0) return i;
    }
    return -1;
  };
  return {
    date: idx(["date", "trans date", "posted"]),
    amount: idx(["amount", "transaction amount"]),
    debit: idx(["debit", "withdrawal"]),
    credit: idx(["credit", "deposit"]),
    description: idx(["description", "memo", "payee", "narrative", "details"]),
  };
}

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

function rowsToTransactions(rows: string[][], colMap: ColMap): ParsedRow[] {
  return rows.flatMap((row): ParsedRow[] => {
    const date = colMap.date >= 0 ? (row[colMap.date] ?? "").trim() : "";
    const description = colMap.description >= 0 ? (row[colMap.description] ?? "").trim() : "";

    let amount = 0;
    if (colMap.amount !== null && colMap.amount >= 0) {
      amount = parseFloat((row[colMap.amount] ?? "").replace(/[^0-9.\\-]/g, "")) || 0;
    } else {
      const credit = colMap.credit !== null && colMap.credit >= 0
        ? parseFloat((row[colMap.credit] ?? "").replace(/[^0-9.]/g, "")) || 0
        : 0;
      const debit = colMap.debit !== null && colMap.debit >= 0
        ? parseFloat((row[colMap.debit] ?? "").replace(/[^0-9.]/g, "")) || 0
        : 0;
      amount = credit - debit;
    }

    if (!date) return [];
    return [{ date, amount, description, raw: row.join(",") }];
  });
}

export function BankImportScreen() {
  const [accounts, setAccounts] = useState<BankAccount[] | null>(null);
  const [accountId, setAccountId] = useState<number>(0);
  const [step, setStep] = useState<"upload" | "map" | "preview" | "done">("upload");
  const [fileText, setFileText] = useState("");
  const [headers, setHeaders] = useState<string[]>([]);
  const [colMap, setColMap] = useState<ColMap>({ date: -1, amount: null, debit: null, credit: null, description: -1 });
  const [preview, setPreview] = useState<ParsedRow[]>([]);
  const [importing, setImporting] = useState(false);
  const [importedCount, setImportedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);

  // Load accounts lazily
  if (!accounts) {
    listBankAccounts(true).then((a) => {
      setAccounts(a);
      if (a[0]) setAccountId(a[0].id);
    }).catch((e) => setError(String(e)));
  }

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (ev) => {
      const text = ev.target?.result as string;
      setFileText(text);
      const { headers: h } = parseCSV(text);
      setHeaders(h);
      setColMap(detectColumns(h));
      setStep("map");
    };
    reader.readAsText(file);
  }

  function handlePreview() {
    const { rows } = parseCSV(fileText);
    setPreview(rowsToTransactions(rows, colMap));
    setStep("preview");
  }

  async function handleImport() {
    if (!accountId) return;
    setImporting(true);
    try {
      let count = 0;
      for (const row of preview) {
        if (!row.date || isNaN(row.amount)) continue;
        const id = await insertBankTransaction(accountId, row.date, row.amount, row.description);
        if (id > 0) count++;
      }
      setImportedCount(count);
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setImporting(false);
    }
  }

  function reset() {
    setStep("upload");
    setFileText("");
    setHeaders([]);
    setPreview([]);
    setImportedCount(0);
    setError(null);
  }

  const fmt = (n: number) =>
    new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

  return (
    <div className="p-8 max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">Bank Import</h1>
        <p className="text-sm text-gray-500 mt-0.5">
          Import transactions from a CSV bank statement.
        </p>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Step indicators */}
      <div className="flex gap-6 mb-6 text-xs">
        {(["upload", "map", "preview", "done"] as const).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${
              step === s ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500"
            }`}>
              {i + 1}
            </span>
            <span className={step === s ? "text-blue-600 font-medium" : "text-gray-400"}>
              {s === "upload" ? "Upload" : s === "map" ? "Map Columns" : s === "preview" ? "Preview" : "Done"}
            </span>
          </div>
        ))}
      </div>

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
            <select
              value={accountId}
              onChange={(e) => setAccountId(Number(e.target.value))}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              {(accounts ?? []).map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
          </div>
          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
            <input
              type="file"
              accept=".csv,.txt"
              onChange={handleFile}
              className="hidden"
              id="csv-upload"
            />
            <label htmlFor="csv-upload" className="cursor-pointer">
              <div className="text-4xl mb-2">📄</div>
              <p className="text-sm font-medium text-blue-600">Click to select a CSV file</p>
              <p className="text-xs text-gray-400 mt-1">Exported from your bank's online portal</p>
            </label>
          </div>
        </div>
      )}

      {/* Step 2: Column mapping */}
      {step === "map" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            Map your CSV columns. Auto-detected values are shown — adjust if needed.
          </p>
          <div className="grid grid-cols-2 gap-4">
            {(["date", "description", "amount", "debit", "credit"] as const).map((field) => {
              const value = colMap[field] ?? -1;
              return (
                <div key={field}>
                  <label className="block text-xs font-medium text-gray-700 mb-1 capitalize">{field}</label>
                  <select
                    value={String(value)}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      setColMap((p) => ({ ...p, [field]: v < 0 ? (field === "amount" ? null : -1) : v }));
                    }}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="-1">— Not used —</option>
                    {headers.map((h, i) => <option key={i} value={i}>{h}</option>)}
                  </select>
                </div>
              );
            })}
          </div>
          <div className="text-xs text-gray-400 bg-gray-50 p-3 rounded">
            Use <strong>Amount</strong> for a single signed column (+deposit / −withdrawal).
            Use <strong>Debit</strong> + <strong>Credit</strong> for separate columns.
          </div>
          <div className="flex gap-3">
            <button onClick={handlePreview} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
              Preview →
            </button>
            <button onClick={reset} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Back</button>
          </div>
        </div>
      )}

      {/* Step 3: Preview */}
      {step === "preview" && (
        <div className="space-y-4">
          <p className="text-sm text-gray-600">
            {preview.length} transactions parsed. Review and click Import.
          </p>
          <div className="border rounded-lg overflow-hidden max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left text-gray-600">Date</th>
                  <th className="px-3 py-2 text-left text-gray-600">Description</th>
                  <th className="px-3 py-2 text-right text-gray-600">Amount</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {preview.map((r, i) => (
                  <tr key={i} className={!r.date || isNaN(r.amount) ? "opacity-40" : ""}>
                    <td className="px-3 py-1.5 text-gray-600">{r.date}</td>
                    <td className="px-3 py-1.5 text-gray-700">{r.description}</td>
                    <td className={`px-3 py-1.5 text-right font-mono ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>
                      {fmt(r.amount)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex gap-3">
            <button
              onClick={() => void handleImport()}
              disabled={importing}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
            >
              {importing ? "Importing…" : `Import ${preview.length} Transactions`}
            </button>
            <button onClick={() => setStep("map")} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">
              Back
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Done */}
      {step === "done" && (
        <div className="text-center py-8">
          <div className="text-5xl mb-3">✓</div>
          <p className="text-lg font-semibold text-green-700">{importedCount} transactions imported</p>
          <p className="text-sm text-gray-500 mt-1">
            Duplicate transactions were skipped. Go to Bank → Reconciliations to clear them.
          </p>
          <button
            onClick={reset}
            className="mt-4 px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
          >
            Import Another File
          </button>
        </div>
      )}
    </div>
  );
}
