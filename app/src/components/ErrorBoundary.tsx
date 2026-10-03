import { Component, type ErrorInfo, type ReactNode } from "react";
import { logCrash } from "../lib/errorLog";

type Props = { children: ReactNode };
type State = { error: Error | null; logged: boolean };

export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null, logged: false };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  override componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("ErrorBoundary caught:", error, info.componentStack);
    const screen = window.location.pathname;
    logCrash(screen, error).then(() => this.setState({ logged: true })).catch(() => {});
  }

  override render() {
    const { error, logged } = this.state;
    if (error) {
      return (
        <div className="p-6 max-w-2xl">
          <div className="rounded-lg border border-red-300 p-4" style={{ backgroundColor: "#fef2f2" }}>
            <p className="font-semibold text-red-800 text-sm mb-1">Screen crashed</p>
            <p className="text-red-700 text-sm font-mono break-all">{error.message}</p>
            {logged && (
              <p className="text-xs text-red-500 mt-1">
                Logged to ~/hoa-system/tauri/errors.log
              </p>
            )}
            <details className="mt-3">
              <summary className="text-xs text-red-600 cursor-pointer select-none">Stack trace</summary>
              <pre className="text-xs text-red-600 mt-2 whitespace-pre-wrap break-all overflow-auto max-h-48">
                {error.stack}
              </pre>
            </details>
            <button
              onClick={() => this.setState({ error: null, logged: false })}
              className="mt-3 text-xs px-3 py-1 rounded border"
              style={{ backgroundColor: "#fee2e2", borderColor: "#fca5a5", color: "#991b1b" }}
            >
              Try again
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
