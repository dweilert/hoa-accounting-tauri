import { useState, useEffect, useRef } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { HELP, type HelpContent } from "../lib/helpContent";
import { useNavHistory } from "../lib/navHistory";
import { canPopout, isPopoutWindow, openPopout, returnFromPopout } from "../lib/popout";

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
        className="fixed top-0 right-0 h-full w-1/2 min-w-80 bg-white shadow-xl z-40 flex flex-col
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
  const crumbs = useNavHistory();

  // All crumbs except the current page (last entry)
  const trail = crumbs.slice(0, -1);

  // Fallback: location state or backTo prop (for screens that hard-code a back dest)
  const stateFrom = (location.state as { from?: string; fromLabel?: string } | null)?.from;
  const stateLabel = (location.state as { from?: string; fromLabel?: string } | null)?.fromLabel;
  const resolvedBackTo = stateFrom ?? backTo;
  const resolvedBackLabel = stateLabel ?? backLabel;

  return (
    <>
      {/* Sticky page header — top-0 because the scroll container (main) already starts below the fixed top bar */}
      <div className="sticky top-0 z-20 border-b border-gray-200 print:hidden" style={{ backgroundColor: "#f2f5f1" }}>
        <div className="px-6 py-3">
          {/* Breadcrumb trail (auto-tracked history) */}
          {trail.length > 0 && (
            <nav className="flex items-center gap-1 text-xs text-gray-400 mb-1 flex-wrap">
              {trail.map((crumb, i) => (
                <span key={crumb.path} className="flex items-center gap-1">
                  {i > 0 && <span>/</span>}
                  <button
                    onClick={() => navigate(crumb.path)}
                    className="text-blue-600 hover:text-blue-800 hover:underline"
                  >
                    {crumb.label}
                  </button>
                </span>
              ))}
              <span>/</span>
              <span className="text-gray-500">{title}</span>
            </nav>
          )}
          {/* Fallback single back button (prop or location state) — shown only when no trail */}
          {trail.length === 0 && resolvedBackTo && (
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
              {canPopout() && (
                isPopoutWindow() ? (
                  <button
                    onClick={() => void returnFromPopout(location.pathname + location.search)}
                    title="Return to main window"
                    className="w-7 h-7 rounded border border-gray-300 text-gray-500 hover:bg-green-50 hover:border-green-500 hover:text-green-700 flex items-center justify-center transition-colors"
                  >
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M6 3H3v10h10v-3" />
                      <path d="M9 7l4-4M9 3h4v4" transform="rotate(180 11 5)" />
                    </svg>
                  </button>
                ) : (
                  <button
                    onClick={() => openPopout(location.pathname + location.search, title)}
                    title="Pop out into a separate window"
                    className="w-7 h-7 rounded border border-gray-300 text-gray-500 hover:bg-blue-50 hover:border-blue-400 hover:text-blue-700 flex items-center justify-center transition-colors"
                  >
                    <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round">
                      <path d="M7 3H3v10h10V9" />
                      <path d="M9 3h4v4M13 3L7.5 8.5" />
                    </svg>
                  </button>
                )
              )}
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
