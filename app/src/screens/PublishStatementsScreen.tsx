/**
 * Publish Statements to S3
 *
 * Generates one Owner Ledger PDF per active lot via @react-pdf/renderer,
 * writes each to a temp file, then calls the Rust upload_pdf_to_s3 command
 * which makes the S3 PutObject request directly (no Python, no CORS issues).
 *
 * Credentials are read from ~/hoa-system/tauri/s3_config.json.
 * S3 key: owner-reports/{lot_number}/{year}_{lot_number}_{owner_name}.pdf
 */
import { useEffect, useState, useRef } from "react";
import React from "react";
import { invoke } from "@tauri-apps/api/core";
import { readTextFile, writeFile } from "@tauri-apps/plugin-fs";
import { homeDir } from "@tauri-apps/api/path";
import { getDb } from "../lib/db";
import { loadOwnerLedger, loadOwnerDetails } from "../lib/ownerLedgerData";
import { PageLayout } from "../components/PageLayout";

const CURRENT_YEAR = new Date().getFullYear();

// ── Types ─────────────────────────────────────────────────────────────────────

type S3Config = {
  region: string;
  access_key_id: string;
  secret_access_key: string;
  owner_statements: { bucket: string; prefix: string };
};

type LotRow = {
  lot_id: number;
  lot_number: string;
  owner_id: number | null;
  owner_name: string | null;
};

type LotStatus =
  | { phase: "idle" }
  | { phase: "generating" }
  | { phase: "uploading" }
  | { phase: "done"; key: string }
  | { phase: "error"; message: string };

// ── Data loaders ──────────────────────────────────────────────────────────────

async function loadConfig(): Promise<S3Config> {
  const home = await homeDir();
  const text = await readTextFile(`${home}/hoa-system/tauri/s3_config.json`);
  return JSON.parse(text) as S3Config;
}

async function loadHoaName(): Promise<string> {
  const db = await getDb();
  const rows = await db.select<{ value: string }[]>(
    "SELECT value FROM app_settings WHERE key = 'hoa_name' LIMIT 1"
  );
  return rows[0]?.value ?? "HOA";
}

async function loadActiveLots(): Promise<LotRow[]> {
  const db = await getDb();
  // One row per lot — pick the primary (first alphabetically) owner
  return db.select<LotRow[]>(`
    SELECT l.id AS lot_id, l.lot_number,
           MIN(o.id)           AS owner_id,
           MIN(o.display_name) AS owner_name
    FROM lots l
    LEFT JOIN lot_ownership lo ON lo.lot_id = l.id AND lo.end_date IS NULL
    LEFT JOIN owners o ON o.id = lo.owner_id
    WHERE l.active_flag = 1
    GROUP BY l.id, l.lot_number
    ORDER BY l.lot_number
  `);
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function PublishStatementsScreen() {
  const [year, setYear]           = useState(CURRENT_YEAR);
  const [lots, setLots]           = useState<LotRow[]>([]);
  const [statuses, setStatuses]   = useState<Record<string, LotStatus>>({});
  const [config, setConfig]       = useState<S3Config | null>(null);
  const [configError, setConfigError] = useState<string | null>(null);
  const [hoaName, setHoaName]     = useState("HOA");
  const [running, setRunning]     = useState(false);
  const [loadingLots, setLoadingLots] = useState(true);
  const abortRef = useRef(false);

  // Load config, HOA name, and lots on mount
  useEffect(() => {
    loadConfig()
      .then(setConfig)
      .catch((e) => setConfigError(String(e)));
    loadHoaName().then(setHoaName).catch(() => {});
    loadActiveLots()
      .then((rows) => {
        setLots(rows);
        const init: Record<string, LotStatus> = {};
        rows.forEach((r) => { init[r.lot_number] = { phase: "idle" }; });
        setStatuses(init);
      })
      .finally(() => setLoadingLots(false));
  }, []);

  // Re-init statuses when year changes (reset to idle)
  useEffect(() => {
    if (lots.length === 0) return;
    const init: Record<string, LotStatus> = {};
    lots.forEach((r) => { init[r.lot_number] = { phase: "idle" }; });
    setStatuses(init);
  }, [year, lots]);

  function setStatus(lotNumber: string, s: LotStatus) {
    setStatuses((prev) => ({ ...prev, [lotNumber]: s }));
  }

  // ── Publish all lots ────────────────────────────────────────────────────────
  async function handlePublish() {
    if (!config || running) return;
    abortRef.current = false;
    setRunning(true);

    // Reset all to idle
    const init: Record<string, LotStatus> = {};
    lots.forEach((r) => { init[r.lot_number] = { phase: "idle" }; });
    setStatuses(init);

    const { pdf }            = await import("@react-pdf/renderer");
    const { OwnerLedgerPDF } = await import("../reports/OwnerLedgerPDF");

    const home    = await homeDir();
    const runDate = `Generated: ${new Date().toLocaleString("en-US", {
      year: "numeric", month: "long", day: "numeric",
      hour: "numeric", minute: "2-digit",
    })}`;

    for (const lot of lots) {
      if (abortRef.current) break;
      if (!lot.owner_id) {
        setStatus(lot.lot_number, { phase: "error", message: "No owner assigned" });
        continue;
      }

      try {
        // 1. Generate PDF
        setStatus(lot.lot_number, { phase: "generating" });
        const [result, ownerDetails] = await Promise.all([
          loadOwnerLedger(lot.owner_id, year),
          loadOwnerDetails(lot.owner_id, year),
        ]);

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const docEl = React.createElement(OwnerLedgerPDF as any, {
          result, ownerDetails, hoaName, runDate, year,
        });
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const blob   = await (pdf as any)(docEl).toBlob();
        const buffer = await blob.arrayBuffer();

        // 2. Write to temp file (within permitted fs scope)
        const tmpPath = `${home}/hoa-system/tauri/stmt_tmp_${lot.lot_number}.pdf`;
        await writeFile(tmpPath, new Uint8Array(buffer));

        // 3. Upload via Rust (no CORS — Rust makes the HTTPS request)
        setStatus(lot.lot_number, { phase: "uploading" });
        const safeOwner = (lot.owner_name ?? "unknown")
          .replace(/[^a-zA-Z0-9_-]/g, "_")
          .slice(0, 40);
        const key = `${config.owner_statements.prefix}${lot.lot_number}/${year}_${lot.lot_number}_${safeOwner}.pdf`;

        await invoke("upload_pdf_to_s3", {
          localPath: tmpPath,
          bucket: config.owner_statements.bucket,
          key,
          region: config.region,
          accessKey: config.access_key_id,
          secretKey: config.secret_access_key,
        });

        setStatus(lot.lot_number, { phase: "done", key });
      } catch (e) {
        setStatus(lot.lot_number, { phase: "error", message: String(e) });
      }
    }

    setRunning(false);
  }

  // ── Derived counts ──────────────────────────────────────────────────────────
  const total     = lots.length;
  const done      = Object.values(statuses).filter((s) => s.phase === "done").length;
  const errors    = Object.values(statuses).filter((s) => s.phase === "error").length;
  const inFlight  = Object.values(statuses).filter(
    (s) => s.phase === "generating" || s.phase === "uploading"
  ).length;
  const anyStarted = done + errors + inFlight > 0;

  // ── Render ──────────────────────────────────────────────────────────────────
  return (
    <PageLayout title="Publish Statements" subtitle="Generate Owner Ledger PDFs and push to S3 for homeowner access.">
      <div className="space-y-5">

        {/* Config card */}
        <div className="bg-white border rounded-lg p-4 space-y-4">
          <div className="grid grid-cols-2 gap-4">
            {/* Year */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Statement Year</label>
              <select
                value={year}
                onChange={(e) => setYear(Number(e.target.value))}
                disabled={running}
                className="w-full border border-gray-300 rounded px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white disabled:opacity-50"
              >
                {[CURRENT_YEAR, CURRENT_YEAR - 1, CURRENT_YEAR - 2].map((y) => (
                  <option key={y} value={y}>{y}</option>
                ))}
              </select>
            </div>

            {/* S3 destination */}
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">S3 Destination</label>
              {configError ? (
                <p className="text-xs text-red-600 mt-1">{configError}</p>
              ) : config ? (
                <p className="text-sm text-gray-600 mt-1 font-mono">
                  s3://{config.owner_statements.bucket}/{config.owner_statements.prefix}
                </p>
              ) : (
                <p className="text-xs text-gray-400 mt-1">Loading config…</p>
              )}
            </div>
          </div>

          {/* Action row */}
          <div className="flex items-center gap-4 pt-2 border-t border-gray-100">
            <button
              onClick={handlePublish}
              disabled={running || !config || !!configError || loadingLots || total === 0}
              className="px-5 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {running ? "Publishing…" : `Publish All ${total} Statements`}
            </button>

            {running && (
              <button
                onClick={() => { abortRef.current = true; }}
                className="px-4 py-2 text-sm border border-red-300 text-red-600 rounded-lg hover:bg-red-50"
              >
                Stop
              </button>
            )}

            {anyStarted && !running && (
              <span className="text-sm text-gray-500">
                {done} of {total} published
                {errors > 0 && <span className="text-red-600 ml-2">· {errors} error{errors > 1 ? "s" : ""}</span>}
              </span>
            )}
          </div>

          {/* Progress bar */}
          {anyStarted && (
            <div className="w-full bg-gray-100 rounded-full h-1.5">
              <div
                className="bg-blue-600 h-1.5 rounded-full transition-all duration-300"
                style={{ width: `${total > 0 ? ((done + errors) / total) * 100 : 0}%` }}
              />
            </div>
          )}
        </div>

        {/* Lots table */}
        <div className="bg-white border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
          <table className="w-full text-[11px]">
            <thead className="bg-gray-50 border-b sticky top-0 z-10">
              <tr className="bg-slate-800 text-white">
                <th className="px-3 py-2 text-left text-[10px] font-semibold">Lot</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold">Owner</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold w-32">Status</th>
                <th className="px-3 py-2 text-left text-[10px] font-semibold">S3 Key</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {loadingLots && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">Loading lots…</td></tr>
              )}
              {!loadingLots && total === 0 && (
                <tr><td colSpan={4} className="px-3 py-6 text-center text-gray-400">No active lots found.</td></tr>
              )}
              {lots.map((lot) => {
                const s = statuses[lot.lot_number] ?? { phase: "idle" };
                return (
                  <tr key={lot.lot_number}>
                    <td className="px-3 py-1.5 font-semibold text-gray-900">Lot {lot.lot_number}</td>
                    <td className="px-3 py-1.5 text-gray-600">
                      {lot.owner_name ?? <span className="italic text-gray-400">— No owner —</span>}
                    </td>
                    <td className="px-3 py-1.5">
                      <StatusBadge status={s} />
                    </td>
                    <td className="px-3 py-1.5 text-gray-400 font-mono text-[10px]">
                      {s.phase === "done" ? s.key : ""}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </div>
    </PageLayout>
  );
}

function StatusBadge({ status }: { status: LotStatus }) {
  switch (status.phase) {
    case "idle":
      return <span className="text-gray-300">—</span>;
    case "generating":
      return <span className="text-blue-600">⟳ Generating…</span>;
    case "uploading":
      return <span className="text-blue-600">⟳ Uploading…</span>;
    case "done":
      return <span className="text-green-600 font-medium">✓ Done</span>;
    case "error":
      return (
        <span className="text-red-600" title={status.message}>
          ✗ Error
        </span>
      );
  }
}
