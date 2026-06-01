import { useState, useEffect } from "react";
import { PageLayout } from "../components/PageLayout";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import {
  insertBankTransaction, getExistingDedupKeys,
  createImportBatch, finalizeImportBatch,
  undoImportBatch,
} from "../repositories/reconciliationRepo";
import type { BankAccount } from "../types/bankAccount";

// ── OFX Parser ────────────────────────────────────────────────────────────────

type OFXTransaction = {
  trntype: string;
  dtposted: string;
  trnamt: number;
  fitid: string;
  name: string;
  memo: string;
};

function parseOFXDate(raw: string): string {
  // YYYYMMDDHHMMSS[.mmm][±ZZZ:ZZ] — take first 8 chars
  const d = raw.slice(0, 8);
  if (d.length === 8) {
    return `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`;
  }
  return raw;
}

function extractTag(block: string, tag: string): string {
  // Handle both <TAG>VALUE</TAG> and <TAG>VALUE\n formats
  const closeRe = new RegExp(`<${tag}>([^<]+)</${tag}>`, "i");
  const openRe = new RegExp(`<${tag}>([^<\r\n]+)`, "i");
  return (closeRe.exec(block)?.[1] ?? openRe.exec(block)?.[1] ?? "").trim();
}

function parseOFX(text: string): OFXTransaction[] {
  // Find all <STMTTRN>...</STMTTRN> blocks (or open-tag format)
  const transactions: OFXTransaction[] = [];

  // Split on STMTTRN occurrences — works for both SGML and XML OFX
  const blocks = text.split(/<\/?STMTTRN>/i).filter((_, i) => i % 2 === 1);

  for (const block of blocks) {
    const trntype = extractTag(block, "TRNTYPE");
    const dtraw = extractTag(block, "DTPOSTED");
    const amtStr = extractTag(block, "TRNAMT");
    const fitid = extractTag(block, "FITID");
    const name = extractTag(block, "NAME") || extractTag(block, "PAYEE");
    const memo = extractTag(block, "MEMO");

    if (!dtraw || !amtStr) continue;

    const rawAmt = parseFloat(amtStr.replace(/[, ]/g, ""));
    if (isNaN(rawAmt)) continue;

    // For debit-only OFX: DEBIT type means negative
    let amount = rawAmt;
    if (trntype.toUpperCase() === "DEBIT" && amount > 0) amount = -amount;
    if (trntype.toUpperCase() === "CHECK" && amount > 0) amount = -amount;

    transactions.push({
      trntype,
      dtposted: parseOFXDate(dtraw),
      trnamt: amount,
      fitid,
      name,
      memo,
    });
  }

  return transactions;
}

function buildDedupKey(fitid: string, date: string, amount: number): string {
  return fitid ? `ofx-${fitid}` : `ofx-${date}-${amount}`;
}

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

// ── Screen ────────────────────────────────────────────────────────────────────

type Step = "upload" | "preview" | "done";

export function OFXImportScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [accountId, setAccountId] = useState<number>(0);
  const [step, setStep] = useState<Step>("upload");
  const [filename, setFilename] = useState<string | null>(null);
  const [transactions, setTransactions] = useState<(OFXTransaction & { isDuplicate?: boolean })[]>([]);
  const [importing, setImporting] = useState(false);
  const [lastBatchId, setLastBatchId] = useState<number | null>(null);
  const [importedCount, setImportedCount] = useState(0);
  const [skippedCount, setSkippedCount] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);

  useEffect(() => {
    listBankAccounts(true)
      .then((a) => { setAccounts(a); if (a[0]) setAccountId(a[0].id); })
      .catch((e) => setError(String(e)));
  }, []);

  function handleFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    setFilename(file.name);
    setParseError(null);
    const reader = new FileReader();
    reader.onload = async (ev) => {
      const text = ev.target?.result as string;
      try {
        const parsed = parseOFX(text);
        if (parsed.length === 0) {
          setParseError("No transactions found in this file. Make sure it is a valid OFX or QFX file.");
          return;
        }
        // Check for duplicates
        const existing = await getExistingDedupKeys(accountId).catch(() => new Set<string>());
        const marked = parsed.map((t) => ({
          ...t,
          isDuplicate: existing.has(buildDedupKey(t.fitid, t.dtposted, t.trnamt)),
        }));
        setTransactions(marked);
        setStep("preview");
      } catch (err) {
        setParseError(`Parse error: ${String(err)}`);
      }
    };
    reader.readAsText(file);
  }

  async function handleImport() {
    if (!accountId) return;
    setImporting(true);
    try {
      const batchId = await createImportBatch(accountId, filename);
      let imported = 0, skipped = 0;
      for (const t of transactions) {
        if (t.isDuplicate) { skipped++; continue; }
        const desc = [t.name, t.memo].filter(Boolean).join(" — ") || t.trntype;
        const dedupKey = buildDedupKey(t.fitid, t.dtposted, t.trnamt);
        const id = await insertBankTransaction(accountId, t.dtposted, t.trnamt, desc, dedupKey, batchId);
        if (id > 0) imported++;
        else skipped++;
      }
      await finalizeImportBatch(batchId, imported, skipped);
      setLastBatchId(batchId);
      setImportedCount(imported);
      setSkippedCount(skipped);
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setImporting(false);
    }
  }

  async function handleUndoLast() {
    if (!lastBatchId) return;
    if (!confirm(`Undo this import (${importedCount} transactions)?`)) return;
    try {
      const removed = await undoImportBatch(lastBatchId);
      alert(`Removed ${removed} transaction${removed !== 1 ? "s" : ""}.`);
      setLastBatchId(null);
      reset();
    } catch (e) {
      alert(String(e));
    }
  }

  function reset() {
    setStep("upload");
    setFilename(null);
    setTransactions([]);
    setImportedCount(0);
    setSkippedCount(0);
    setParseError(null);
    setError(null);
  }

  const newTxns = transactions.filter((t) => !t.isDuplicate);
  const dupTxns = transactions.filter((t) => t.isDuplicate);

  return (
    <PageLayout title="OFX / QFX Import" subtitle="Import transactions from an OFX or QFX bank file." helpId="ofxImport">
    <div className="max-w-4xl">
      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Step indicators */}
      <div className="flex gap-6 mb-6 text-xs">
        {(["upload","preview","done"] as const).map((s, i) => (
          <div key={s} className="flex items-center gap-2">
            <span className={`w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold ${step === s ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500"}`}>
              {i + 1}
            </span>
            <span className={step === s ? "text-blue-600 font-medium" : "text-gray-400"}>
              {s === "upload" ? "Upload" : s === "preview" ? "Preview" : "Done"}
            </span>
          </div>
        ))}
      </div>

      {/* Step 1: Upload */}
      {step === "upload" && (
        <div className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Bank Account</label>
            <select value={accountId} onChange={(e) => setAccountId(Number(e.target.value))}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
          </div>

          {parseError && (
            <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{parseError}</div>
          )}

          <div className="border-2 border-dashed border-gray-300 rounded-lg p-8 text-center">
            <input type="file" accept=".ofx,.qfx,.ofc" onChange={handleFile} className="hidden" id="ofx-upload" />
            <label htmlFor="ofx-upload" className="cursor-pointer">
              <div className="text-4xl mb-2">🏦</div>
              <p className="text-sm font-medium text-blue-600">Click to select an OFX or QFX file</p>
              <p className="text-xs text-gray-400 mt-1">
                Downloaded from your bank's "Export" or "Download Transactions" option.
                Most US banks support OFX (Open Financial Exchange) or QFX (Quicken) format.
              </p>
            </label>
          </div>
        </div>
      )}

      {/* Step 2: Preview */}
      {step === "preview" && (
        <div className="space-y-4">
          <div className="flex gap-4 text-sm">
            <span className="text-green-700 font-medium">{newTxns.length} new</span>
            {dupTxns.length > 0 && (
              <span className="text-amber-600">{dupTxns.length} already imported (will be skipped)</span>
            )}
            {filename && <span className="text-gray-400 ml-auto">{filename}</span>}
          </div>

          <div className="border rounded-lg overflow-hidden max-h-96 overflow-y-auto">
            <table className="w-full text-xs">
              <thead className="bg-gray-50 border-b sticky top-0">
                <tr>
                  <th className="px-3 py-2 text-left text-gray-600">Date</th>
                  <th className="px-3 py-2 text-left text-gray-600">Type</th>
                  <th className="px-3 py-2 text-left text-gray-600">Description</th>
                  <th className="px-3 py-2 text-right text-gray-600">Amount</th>
                  <th className="px-3 py-2 text-right text-gray-600">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {transactions.map((t, i) => (
                  <tr key={i} className={t.isDuplicate ? "opacity-40 bg-gray-50" : ""}>
                    <td className="px-3 py-1.5 whitespace-nowrap text-gray-600">{t.dtposted}</td>
                    <td className="px-3 py-1.5 text-gray-400">{t.trntype}</td>
                    <td className="px-3 py-1.5 text-gray-700 max-w-xs truncate">
                      {[t.name, t.memo].filter(Boolean).join(" — ") || "—"}
                    </td>
                    <td className={`px-3 py-1.5 text-right font-mono ${t.trnamt < 0 ? "text-red-600" : "text-green-700"}`}>
                      {fmt(t.trnamt)}
                    </td>
                    <td className="px-3 py-1.5 text-right">
                      {t.isDuplicate
                        ? <span className="text-amber-500">duplicate</span>
                        : <span className="text-green-600">new</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="flex gap-3">
            <button onClick={() => void handleImport()} disabled={importing || newTxns.length === 0}
              className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50">
              {importing ? "Importing…" : `Import ${newTxns.length} Transaction${newTxns.length !== 1 ? "s" : ""}`}
            </button>
            <button onClick={reset} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Back</button>
          </div>
        </div>
      )}

      {/* Step 3: Done */}
      {step === "done" && (
        <div className="text-center py-6 space-y-4">
          <div className="text-5xl">✓</div>
          <p className="text-lg font-semibold text-green-700">
            {importedCount} transaction{importedCount !== 1 ? "s" : ""} imported
          </p>
          {skippedCount > 0 && (
            <p className="text-sm text-gray-400">{skippedCount} skipped (duplicates)</p>
          )}
          <p className="text-sm text-gray-500">Go to Bank → Pending to classify them.</p>
          <div className="flex justify-center gap-3">
            <button onClick={reset} className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
              Import Another File
            </button>
            {lastBatchId && importedCount > 0 && (
              <button onClick={() => void handleUndoLast()}
                className="px-4 py-2 border border-red-300 text-red-600 text-sm rounded hover:bg-red-50">
                Undo This Import
              </button>
            )}
          </div>
        </div>
      )}
    </div>
    </PageLayout>
  );
}
