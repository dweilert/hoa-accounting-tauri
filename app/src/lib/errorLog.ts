import { invoke } from "@tauri-apps/api/core";

export async function writeErrorLog(entry: string): Promise<void> {
  const timestamp = new Date().toISOString();
  const line = `[${timestamp}] ${entry}`;
  try {
    await invoke("write_error_log", { entry: line });
  } catch {
    // Fallback: log to console if Tauri invoke unavailable (browser preview)
    console.error("errorLog:", line);
  }
}

export async function logCrash(screen: string, error: Error): Promise<void> {
  const entry = `CRASH screen=${screen}\n  message: ${error.message}\n  stack: ${(error.stack ?? "").split("\n").slice(0, 6).join(" | ")}`;
  await writeErrorLog(entry);
}

export async function logNote(note: string): Promise<void> {
  await writeErrorLog(`NOTE ${note}`);
}
