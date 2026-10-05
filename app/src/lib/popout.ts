import { emit } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow, WebviewWindow } from "@tauri-apps/api/webviewWindow";

export const POPOUT_PREFIX = "popout-";
export const POPOUT_RETURN_EVENT = "popout-return";
export const DB_CHANGED_EVENT = "db-changed";

function inTauri(): boolean {
  return typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
}

export function currentWindowLabel(): string {
  return inTauri() ? getCurrentWebviewWindow().label : "browser";
}

export function isPopoutWindow(): boolean {
  return currentWindowLabel().startsWith(POPOUT_PREFIX);
}

export function canPopout(): boolean {
  return inTauri();
}

export function openPopout(path: string, title: string): void {
  const win = new WebviewWindow(`${POPOUT_PREFIX}${Date.now()}`, {
    url: path,
    title: `${title} — HOA Accounting`,
    width: 1100,
    height: 750,
    minWidth: 600,
    minHeight: 400,
  });
  void win.once("tauri://error", (e) => console.error("popout failed", e));
}

export async function returnFromPopout(path: string): Promise<void> {
  await emit(POPOUT_RETURN_EVENT, { path });
  await getCurrentWebviewWindow().close();
}

let notifyTimer: ReturnType<typeof setTimeout> | null = null;

export function notifyDbChanged(): void {
  if (!inTauri()) return;
  if (notifyTimer) clearTimeout(notifyTimer);
  notifyTimer = setTimeout(() => {
    void emit(DB_CHANGED_EVENT, { from: currentWindowLabel() });
  }, 300);
}
