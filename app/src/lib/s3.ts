// S3 operations — delegates to Python scripts via Tauri shell plugin.
// Python path and scripts directory come from ~/hoa-system/tauri/config.json.
// boto3 must be available in the configured Python environment.

import { readConfig } from "./config";

export type S3Result = { ok: boolean; message: string };
export type UploadStatementsResult = S3Result & { uploaded: number };

export type StatementFile = {
  local_path: string;
  lot_number: string;
  owner_name: string;
  year: number;
};

async function runPython(scriptName: string, args: string[] = []): Promise<string> {
  const cfg = await readConfig();
  if (!cfg) throw new Error("App config not found — cannot run Python scripts.");

  const python = cfg.python_path ?? "python3";
  const scriptsDir = cfg.scripts_dir ?? "hoa-system/tauri/scripts";
  const { Command } = await import("@tauri-apps/plugin-shell");
  const result = await Command.create("run-python", [
    python,
    `${scriptsDir}/${scriptName}`,
    ...args,
  ]).execute();

  if (result.code !== 0 && !result.stdout.trim()) {
    throw new Error(result.stderr.trim() || `Script exited with code ${result.code}`);
  }
  return result.stdout.trim();
}

export async function pushDbBackup(): Promise<S3Result> {
  try {
    const out = await runPython("db_backup.py");
    return JSON.parse(out) as S3Result;
  } catch (e) {
    return { ok: false, message: String(e) };
  }
}

export async function uploadOwnerStatements(
  files: StatementFile[]
): Promise<UploadStatementsResult> {
  if (files.length === 0) {
    return { ok: true, message: "No files to upload.", uploaded: 0 };
  }
  try {
    // Write payload to a temp file so the script can read it without stdin tricks
    const { writeTextFile } = await import("@tauri-apps/plugin-fs");
    // Use /tmp directly — no tempDir() API in tauri-plugin-fs v2
    const tmp = `/tmp/hoa_statements_payload_${String(Math.trunc(performance.now()))}.json`;
    await writeTextFile(tmp, JSON.stringify({ files }));

    const out = await runPython("upload_statements.py", [tmp]);

    // Clean up temp file (best-effort)
    const { remove } = await import("@tauri-apps/plugin-fs");
    await remove(tmp).catch(() => undefined);

    return JSON.parse(out) as UploadStatementsResult;
  } catch (e) {
    return { ok: false, message: String(e), uploaded: 0 };
  }
}
