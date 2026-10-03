import { useState, useEffect, useCallback } from "react";
import { PageLayout } from "../components/PageLayout";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import {
  insertBankTransaction,
  getExistingDedupKeys,
  createImportBatch,
  finalizeImportBatch,
  storeOfxBalance,
} from "../repositories/reconciliationRepo";
import type { BankAccount } from "../types/bankAccount";

// ── Constants ─────────────────────────────────────────────────────────────────

const INBOX_REL = "hoa-system/ofx-inbox";
const FETCHER_PYTHON = `${String(import.meta.env.HOME ?? "~")}/hoa_downloader/.venv/bin/python`;
const FETCHER_SCRIPT = `${String(import.meta.env.HOME ?? "~")}/hoa_downloader/run.py`;
const HEARTBEAT_STALE_SECS = 180;

// ── OFX Parser (shared logic) ─────────────────────────────────────────────────

type OFXTransaction = {
  trntype: string;
  dtposted: string;
  trnamt: number;
  fitid: string;
  name: string;
  memo: string;
};

function parseOFXDate(raw: string): string {
  const d = raw.slice(0, 8);
  return d.length === 8
    ? `${d.slice(0, 4)}-${d.slice(4, 6)}-${d.slice(6, 8)}`
    : raw;
}

function extractTag(block: string, tag: string): string {
  const closeRe = new RegExp(`<${tag}>([^<]+)</${tag}>`, "i");
  const openRe = new RegExp(`<${tag}>([^<\r\n]+)`, "i");
  return (closeRe.exec(block)?.[1] ?? openRe.exec(block)?.[1] ?? "").trim();
}

function parseOFX(text: string): OFXTransaction[] {
  const transactions: OFXTransaction[] = [];
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
    let amount = rawAmt;
    if (trntype.toUpperCase() === "DEBIT" && amount > 0) amount = -amount;
    if (trntype.toUpperCase() === "CHECK" && amount > 0) amount = -amount;
    transactions.push({ trntype, dtposted: parseOFXDate(dtraw), trnamt: amount, fitid, name, memo });
  }
  return transactions;
}

function buildDedupKey(fitid: string, date: string, amount: number): string {
  return fitid ? `ofx-${fitid}` : `ofx-${date}-${amount}`;
}

function parseOFXBalance(text: string): { balanceDate: string; balanceAmount: number } | null {
  const block = /<LEDGERBAL>([\s\S]*?)(<\/LEDGERBAL>|<AVAILBAL>|<\/STMTRS>)/i.exec(text)?.[1];
  if (!block) return null;
  const amtStr = extractTag(block, "BALAMT");
  const dtRaw = extractTag(block, "DTASOF");
  if (!amtStr || !dtRaw) return null;
  const balanceAmount = parseFloat(amtStr);
  if (isNaN(balanceAmount)) return null;
  return { balanceDate: parseOFXDate(dtRaw), balanceAmount };
}

// ── Inbox file reader (Tauri only) ────────────────────────────────────────────

type InboxFile = { name: string; size: number; mtime: string };

async function listInboxFiles(): Promise<InboxFile[]> {
  const { readDir, stat, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  const entries = await readDir(INBOX_REL, { baseDir: BaseDirectory.Home });
  const files: InboxFile[] = [];
  for (const entry of entries) {
    if (!entry.name?.toLowerCase().endsWith(".ofx")) continue;
    // Only pending files — skip archive/ subdirectory
    if (!entry.name) continue;
    try {
      const info = await stat(`${INBOX_REL}/${entry.name}`, { baseDir: BaseDirectory.Home });
      files.push({
        name: entry.name,
        size: info.size ?? 0,
        mtime: info.mtime ? new Date(info.mtime).toLocaleString() : "—",
      });
    } catch {
      files.push({ name: entry.name, size: 0, mtime: "—" });
    }
  }
  return files.sort((a, b) => a.name.localeCompare(b.name));
}

async function readStatusFile(filename: string): Promise<Record<string, string> | null> {
  const { readTextFile, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  try {
    const text = await readTextFile(`${INBOX_REL}/${filename}`, { baseDir: BaseDirectory.Home });
    const out: Record<string, string> = {};
    for (const line of text.split("\n")) {
      if (!line.includes(":")) continue;
      const idx = line.indexOf(":");
      out[line.slice(0, idx).trim().toLowerCase()] = line.slice(idx + 1).trim();
    }
    return Object.keys(out).length ? out : null;
  } catch {
    return null;
  }
}

async function readOFXText(filename: string): Promise<string> {
  const { readTextFile, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  return readTextFile(`${INBOX_REL}/${filename}`, { baseDir: BaseDirectory.Home });
}

async function deleteInboxFile(filename: string): Promise<void> {
  const { remove, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  await remove(`${INBOX_REL}/${filename}`, { baseDir: BaseDirectory.Home });
}

async function archiveFile(filename: string): Promise<void> {
  // Move to ofx-inbox/archive/YYYY/MM/filename via rename
  const { rename, mkdir, exists, BaseDirectory } = await import("@tauri-apps/plugin-fs");
  const now = new Date();
  const yyyy = now.getFullYear();
  const mm = String(now.getMonth() + 1).padStart(2, "0");
  const archiveDir = `${INBOX_REL}/archive/${yyyy}/${mm}`;
  await mkdir(archiveDir, { baseDir: BaseDirectory.Home, recursive: true });

  let dest = `${archiveDir}/${filename}`;
  let n = 1;
  const stem = filename.replace(/\.ofx$/i, "");
  const ext = ".ofx";
  while (await exists(dest, { baseDir: BaseDirectory.Home }).catch(() => false)) {
    dest = `${archiveDir}/${stem}_${n}${ext}`;
    n++;
  }
  await rename(`${INBOX_REL}/${filename}`, dest, { oldPathBaseDir: BaseDirectory.Home, newPathBaseDir: BaseDirectory.Home });
}

// ── Banner ────────────────────────────────────────────────────────────────────

type BannerLevel = "ok" | "warning" | "danger" | "neutral";
type Banner = { level: BannerLevel; title: string; detail: string };

function buildBanner(
  heartbeat: Record<string, string> | null,
  success: Record<string, string> | null,
  failure: Record<string, string> | null,
): Banner {
  const now = Date.now();

  if (heartbeat) {
    const ts = heartbeat["timestamp"] ? new Date(heartbeat["timestamp"]).getTime() : NaN;
    if (!isNaN(ts) && (now - ts) / 1000 > HEARTBEAT_STALE_SECS) {
      const mins = Math.floor((now - ts) / 60000);
      return { level: "danger", title: "OFX fetcher is down", detail: `No heartbeat for ${mins} minute(s). Check the fetcher daemon.` };
    }
  } else if (!success && !failure) {
    return { level: "neutral", title: "Fetcher not yet run", detail: "Press Run Fetcher to pull bank data for the first time." };
  }

  const failTs = failure?.["timestamp"] ? new Date(failure["timestamp"]).getTime() : NaN;
  const succTs = success?.["timestamp"] ? new Date(success["timestamp"]).getTime() : NaN;

  if (!isNaN(failTs) && (isNaN(succTs) || failTs > succTs)) {
    return {
      level: "warning",
      title: `OFX pull failed: ${failure?.["error"] ?? "unknown error"}`,
      detail: failure?.["message"] ?? "",
    };
  }

  if (!isNaN(succTs)) {
    const when = new Date(succTs).toLocaleString();
    const listed = (success?.["files"] ?? "").split(",").map((s) => s.trim()).filter(Boolean);
    return {
      level: "ok",
      title: `Last pull: ${when}`,
      detail: listed.length ? `${listed.length} file(s) fetched` : "Fetch completed",
    };
  }

  return { level: "neutral", title: "No fetch activity yet", detail: "" };
}

const bannerColors: Record<BannerLevel, string> = {
  ok: "bg-green-50 border-green-200 text-green-800",
  warning: "bg-amber-50 border-amber-200 text-amber-800",
  danger: "bg-red-50 border-red-200 text-red-800",
  neutral: "bg-gray-50 border-gray-200 text-gray-700",
};

// ── Import one file ───────────────────────────────────────────────────────────

async function importFile(
  filename: string,
  accounts: BankAccount[],
): Promise<{ imported: number; skipped: number; error?: string }> {
  try {
    const text = await readOFXText(filename);
    const transactions = parseOFX(text);
    if (transactions.length === 0) return { imported: 0, skipped: 0, error: "No transactions found" };

    // Match ACCTID from OFX to bank account by last4
    const acctidMatch = /<ACCTID>([^<\r\n]+)/i.exec(text);
    const acctid = acctidMatch?.[1]?.trim() ?? "";
    const last4 = acctid.slice(-4);
    const account = accounts.find((a) => a.account_last4 === last4) ?? accounts[0];
    if (!account) return { imported: 0, skipped: 0, error: "No matching bank account found" };

    const existing = await getExistingDedupKeys(account.id).catch(() => new Set<string>());
    const batchId = await createImportBatch(account.id, filename);
    let imported = 0, skipped = 0;
    for (const t of transactions) {
      const key = buildDedupKey(t.fitid, t.dtposted, t.trnamt);
      if (existing.has(key)) { skipped++; continue; }
      const desc = [t.name, t.memo].filter(Boolean).join(" — ") || t.trntype;
      const id = await insertBankTransaction(account.id, t.dtposted, t.trnamt, desc, key, batchId);
      if (id > 0) imported++; else skipped++;
    }
    await finalizeImportBatch(batchId, imported, skipped);
    const bal = parseOFXBalance(text);
    if (bal) await storeOfxBalance(account.id, bal.balanceDate, bal.balanceAmount).catch(() => undefined);
    return { imported, skipped };
  } catch (e) {
    return { imported: 0, skipped: 0, error: String(e) };
  }
}

// ── Screen ────────────────────────────────────────────────────────────────────

function isTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function OFXInboxScreen() {
  const [files, setFiles] = useState<InboxFile[]>([]);
  const [banner, setBanner] = useState<Banner>({ level: "neutral", title: "Loading…", detail: "" });
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [loading, setLoading] = useState(true);
  const [fetcherRunning, setFetcherRunning] = useState(false);
  const [importingFile, setImportingFile] = useState<string | null>(null);
  const [importingAll, setImportingAll] = useState(false);
  const [lastResult, setLastResult] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    if (!isTauri()) return;
    setLoading(true);
    setError(null);
    try {
      const [pending, heartbeat, success, failure, accts] = await Promise.all([
        listInboxFiles(),
        readStatusFile("heartbeat.txt"),
        readStatusFile("last_success.txt"),
        readStatusFile("last_failure.txt"),
        listBankAccounts(true),
      ]);
      setFiles(pending);
      setBanner(buildBanner(heartbeat, success, failure));
      setAccounts(accts);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  async function handleImportOne(filename: string) {
    setImportingFile(filename);
    setLastResult(null);
    const result = await importFile(filename, accounts);
    if (result.error) {
      setLastResult(`${filename}: ${result.error}`);
    } else {
      await archiveFile(filename).catch(() => undefined);
      setLastResult(`${filename}: imported ${result.imported}, skipped ${result.skipped} duplicates`);
      await refresh();
    }
    setImportingFile(null);
  }

  async function handleImportAll() {
    if (files.length === 0) return;
    setImportingAll(true);
    setLastResult(null);
    let totalImported = 0, totalSkipped = 0;
    const errors: string[] = [];
    for (const f of files) {
      const result = await importFile(f.name, accounts);
      if (result.error) {
        errors.push(`${f.name}: ${result.error}`);
      } else {
        totalImported += result.imported;
        totalSkipped += result.skipped;
        await archiveFile(f.name).catch(() => undefined);
      }
    }
    const summary = `Imported ${totalImported} transactions (${totalSkipped} skipped).`;
    setLastResult(errors.length ? `${summary} Errors: ${errors.join("; ")}` : summary);
    await refresh();
    setImportingAll(false);
  }

  async function handleDelete(filename: string) {
    if (!confirm(`Delete ${filename} without importing?`)) return;
    try {
      await deleteInboxFile(filename);
      await refresh();
    } catch (e) {
      setError(`Delete failed: ${String(e)}`);
    }
  }

  async function handleRunFetcher() {
    if (!isTauri()) return;
    setFetcherRunning(true);
    setLastResult(null);
    try {
      const { Command } = await import("@tauri-apps/plugin-shell");
      const result = await Command.create("run-python", [
        FETCHER_PYTHON,
        FETCHER_SCRIPT,
        "--headless",
      ]).execute();
      if (result.code === 0) {
        setLastResult("Fetcher completed successfully.");
      } else {
        setLastResult(`Fetcher exited ${result.code ?? "?"}: ${(result.stderr ?? "").slice(0, 200)}`);
      }
      await refresh();
    } catch (e) {
      setLastResult(`Fetcher error: ${String(e)}`);
    } finally {
      setFetcherRunning(false);
    }
  }

  const fmt = (n: number) => `${(n / 1024).toFixed(1)} KB`;

  if (!isTauri()) {
    return (
      <PageLayout title="OFX Inbox" subtitle="Manage OFX files downloaded by the Frost fetcher daemon.">
        <div className="p-4 bg-amber-50 border border-amber-200 rounded text-amber-800 text-sm">
          OFX Inbox requires the desktop app — not available in browser preview.
        </div>
      </PageLayout>
    );
  }

  return (
    <PageLayout title="OFX Inbox" subtitle="Manage OFX files downloaded by the Frost fetcher daemon." helpId="ofxInbox">
      <div className="space-y-4">

        {/* Banner */}
        <div className={`p-3 border rounded text-sm ${bannerColors[banner.level]}`}>
          <span className="font-medium">{banner.title}</span>
          {banner.detail && <span className="ml-2 opacity-80">{banner.detail}</span>}
        </div>

        {/* Toolbar */}
        <div className="flex gap-3 items-center flex-wrap">
          <button
            onClick={() => void handleRunFetcher()}
            disabled={fetcherRunning || importingAll}
            className="px-4 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {fetcherRunning ? "Fetcher running…" : "Run Fetcher"}
          </button>
          <button
            onClick={() => void handleImportAll()}
            disabled={importingAll || fetcherRunning || files.length === 0}
            className="px-4 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
          >
            {importingAll ? "Importing…" : `Import All (${files.length})`}
          </button>
          <button
            onClick={() => void refresh()}
            disabled={loading}
            className="px-3 py-2 border border-gray-300 text-gray-600 text-sm rounded hover:bg-gray-50 disabled:opacity-50"
          >
            {loading ? "Refreshing…" : "Refresh"}
          </button>
        </div>

        {/* Result message */}
        {lastResult && (
          <div className="p-3 bg-blue-50 border border-blue-200 rounded text-blue-800 text-sm">
            {lastResult}
          </div>
        )}

        {error && (
          <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
        )}

        {/* File list */}
        {files.length === 0 ? (
          <div className="border rounded-lg p-8 text-center text-sm text-gray-400">
            {loading ? "Loading inbox…" : "No pending OFX files. Run the fetcher or check the inbox folder."}
          </div>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">File</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Size</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Modified</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {files.map((f) => (
                  <tr key={f.name} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-mono text-xs text-gray-700">{f.name}</td>
                    <td className="px-4 py-2 text-right text-xs text-gray-500">{fmt(f.size)}</td>
                    <td className="px-4 py-2 text-xs text-gray-500">{f.mtime}</td>
                    <td className="px-4 py-2 text-right">
                      <div className="flex gap-2 justify-end">
                        <button
                          onClick={() => void handleImportOne(f.name)}
                          disabled={importingFile === f.name || importingAll || fetcherRunning}
                          className="px-3 py-1 bg-green-600 text-white text-xs rounded hover:bg-green-700 disabled:opacity-50"
                        >
                          {importingFile === f.name ? "Importing…" : "Import"}
                        </button>
                        <button
                          onClick={() => void handleDelete(f.name)}
                          disabled={importingFile === f.name || importingAll}
                          className="px-3 py-1 border border-red-300 text-red-600 text-xs rounded hover:bg-red-50 disabled:opacity-50"
                        >
                          Delete
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <p className="text-xs text-gray-400">
          Inbox: ~/hoa-system/ofx-inbox/ · Imported files are moved to archive/YYYY/MM/
        </p>
      </div>
    </PageLayout>
  );
}
