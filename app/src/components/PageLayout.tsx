import { useState, useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { HELP, type HelpContent } from "../lib/helpContent";

// ── Help Drawer ───────────────────────────────────────────────────────────────

function HelpDrawer({ content, onClose }: { content: HelpContent; onClose: () => void }) {
  const drawerRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    function onKey(e: KeyboardEvent) { if (e.key === "Escape") onClose(); }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  // Close on click outside
  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (drawerRef.current && !drawerRef.current.contains(e.target as Node)) onClose();
    }
    // Slight delay so the button click that opened the drawer doesn't immediately close it
    const t = setTimeout(() => window.addEventListener("mousedown", onClick), 100);
    return () => { clearTimeout(t); window.removeEventListener("mousedown", onClick); };
  }, [onClose]);

  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20 z-30" />
      {/* Drawer */}
      <div
        ref={drawerRef}
        className="fixed top-0 right-0 h-full w-80 bg-white shadow-xl z-40 flex flex-col
                   animate-in slide-in-from-right duration-200"
        style={{ animation: "slideInRight 0.2s ease-out" }}
      >
        <div className="flex items-center justify-between px-5 py-4 border-b border-gray-200 bg-gray-50">
          <div className="flex items-center gap-2">
            <span className="w-6 h-6 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center">?</span>
            <h2 className="font-semibold text-gray-900 text-sm">{content.heading}</h2>
          </div>
          <button
            onClick={onClose}
            className="text-gray-400 hover:text-gray-700 text-lg leading-none w-7 h-7 flex items-center justify-center rounded hover:bg-gray-200"
          >
            ×
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-4">
          <p className="text-sm text-gray-700 leading-relaxed">{content.description}</p>
          <div>
            <p className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">Key Points</p>
            <ul className="space-y-2">
              {content.tips.map((tip, i) => (
                <li key={i} className="flex gap-2 text-sm text-gray-700">
                  <span className="text-blue-500 mt-0.5 shrink-0">•</span>
                  <span className="leading-snug">{tip}</span>
                </li>
              ))}
            </ul>
          </div>
          {content.warning && (
            <div className="bg-amber-50 border border-amber-200 rounded p-3">
              <p className="text-xs font-semibold text-amber-700 mb-1">Note</p>
              <p className="text-sm text-amber-800">{content.warning}</p>
            </div>
          )}
        </div>
      </div>
      <style>{`
        @keyframes slideInRight {
          from { transform: translateX(100%); opacity: 0; }
          to   { transform: translateX(0);    opacity: 1; }
        }
      `}</style>
    </>
  );
}

// ── PageLayout ────────────────────────────────────────────────────────────────

type PageLayoutProps = {
  title: string;
  subtitle?: string;
  /** Internal route to navigate back to */
  backTo?: string;
  /** Label for the back link (default: "Back") */
  backLabel?: string;
  /** Extra buttons/controls rendered in the header right side */
  actions?: React.ReactNode;
  /** Key into HELP registry — enables the "?" button */
  helpId?: string;
  /** Direct help content (alternative to helpId) */
  help?: HelpContent;
  children: React.ReactNode;
};

export function PageLayout({
  title,
  subtitle,
  backTo,
  backLabel = "Back",
  actions,
  helpId,
  help,
  children,
}: PageLayoutProps) {
  const [helpOpen, setHelpOpen] = useState(false);
  const helpContent = help ?? (helpId ? HELP[helpId] : undefined);
  const location = useLocation();
  const navigate = useNavigate();

  // Location state set by screens that link to this one (takes priority over hardcoded backTo)
  const stateFrom = (location.state as { from?: string; fromLabel?: string } | null)?.from;
  const stateLabel = (location.state as { from?: string; fromLabel?: string } | null)?.fromLabel;

  // Resolved back link: state wins over prop
  const resolvedBackTo = stateFrom ?? backTo;
  const resolvedBackLabel = stateLabel ?? backLabel;

  return (
    <>
      {/* Sticky header */}
      <div className="sticky top-0 z-20 bg-white border-b border-gray-200 print:hidden">
        <div className="px-6 py-3">
          {resolvedBackTo && (
            <button
              onClick={() => navigate(resolvedBackTo)}
              className="inline-flex items-center gap-1 text-xs text-blue-600 hover:text-blue-800 mb-1"
            >
              <span>←</span>
              <span>{resolvedBackLabel}</span>
            </button>
          )}
          <div className="flex items-center justify-between">
            <div className="min-w-0">
              <h1 className="text-xl font-bold text-gray-900 leading-tight truncate">{title}</h1>
              {subtitle && (
                <p className="text-sm text-gray-500 mt-0.5 leading-snug">{subtitle}</p>
              )}
            </div>
            <div className="flex items-center gap-2 ml-4 shrink-0">
              {actions}
              {helpContent && (
                <button
                  onClick={() => setHelpOpen(true)}
                  title="Help"
                  className="w-7 h-7 rounded-full border border-gray-300 text-gray-500 hover:bg-blue-50 hover:border-blue-400 hover:text-blue-700 text-sm font-bold flex items-center justify-center transition-colors"
                >
                  ?
                </button>
              )}
            </div>
          </div>
        </div>
      </div>

      {/* Content — no padding on print so report starts at the top edge */}
      <div className="p-6 print:p-0">
        {children}
      </div>

      {/* Help drawer */}
      {helpOpen && helpContent && (
        <HelpDrawer content={helpContent} onClose={() => setHelpOpen(false)} />
      )}
    </>
  );
}
