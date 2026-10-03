import { useState, useEffect } from "react";

// ── Singleton dialog manager ───────────────────────────────────────────────────
// Replaces native alert() / confirm() with styled React modals.
// Mount <AppDialogHost /> once in App.tsx, then call appAlert / appConfirm anywhere.

type Pending =
  | { type: "alert"; title: string; message: string; resolve: () => void }
  | { type: "confirm"; title: string; message: string; resolve: (v: boolean) => void };

let _enqueue: ((d: Pending) => void) | null = null;

export function appAlert(message: string, title = "Notice"): Promise<void> {
  return new Promise((resolve) => {
    if (_enqueue) {
      _enqueue({ type: "alert", title, message, resolve });
    } else {
      // Host not mounted yet — fallback to native (shouldn't happen in production)
      window.alert(message);
      resolve();
    }
  });
}

export function appConfirm(message: string, title = "Confirm"): Promise<boolean> {
  return new Promise((resolve) => {
    if (_enqueue) {
      _enqueue({ type: "confirm", title, message, resolve });
    } else {
      resolve(window.confirm(message));
    }
  });
}

// ── Host component — render once at app root ──────────────────────────────────

export function AppDialogHost() {
  const [queue, setQueue] = useState<Pending[]>([]);

  useEffect(() => {
    _enqueue = (d) => setQueue((q) => [...q, d]);
    return () => { _enqueue = null; };
  }, []);

  const current = queue[0];
  if (!current) return null;

  function dismiss() {
    setQueue((q) => q.slice(1));
  }

  if (current.type === "alert") {
    return (
      <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40">
        <div className="bg-white rounded-lg shadow-xl w-full max-w-sm mx-4">
          <div className="px-5 py-4 border-b">
            <h2 className="text-sm font-semibold text-gray-900">{current.title}</h2>
          </div>
          <div className="px-5 py-4">
            <p className="text-sm text-gray-700 whitespace-pre-wrap">{current.message}</p>
          </div>
          <div className="px-5 py-3 border-t flex justify-end">
            <button
              autoFocus
              onClick={() => { dismiss(); current.resolve(); }}
              className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
            >
              OK
            </button>
          </div>
        </div>
      </div>
    );
  }

  // confirm
  return (
    <div className="fixed inset-0 z-[200] flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-lg shadow-xl w-full max-w-sm mx-4">
        <div className="px-5 py-4 border-b">
          <h2 className="text-sm font-semibold text-gray-900">{current.title}</h2>
        </div>
        <div className="px-5 py-4">
          <p className="text-sm text-gray-700 whitespace-pre-wrap">{current.message}</p>
        </div>
        <div className="px-5 py-3 border-t flex justify-end gap-3">
          <button
            onClick={() => { dismiss(); current.resolve(false); }}
            className="px-4 py-1.5 border border-gray-300 text-gray-700 text-sm rounded hover:bg-gray-50"
          >
            Cancel
          </button>
          <button
            autoFocus
            onClick={() => { dismiss(); current.resolve(true); }}
            className="px-4 py-1.5 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
