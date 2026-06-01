import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { getDb } from "../lib/db";

// ── Types ─────────────────────────────────────────────────────────────────────

type WorkflowTab = {
  id: number;
  tab_key: string;
  icon: string;
  label: string;
  description: string;
  sort_order: number;
};

type WorkflowSection = {
  id: number;
  tab_id: number;
  label: string;
  tip_text: string;
  sort_order: number;
};

type WorkflowCard = {
  id: number;
  section_id: number;
  num_label: string;
  icon: string;
  title: string;
  description: string;
  href: string;
  link_label: string;
  color: string;
  sort_order: number;
};

// ── Color map ─────────────────────────────────────────────────────────────────

const COLOR_CLASSES: Record<string, { badge: string; border: string; btn: string }> = {
  blue:  { badge: "bg-blue-600 text-white",   border: "border-blue-300",  btn: "bg-blue-600 hover:bg-blue-700 text-white" },
  green: { badge: "bg-green-600 text-white",  border: "border-green-300", btn: "bg-green-600 hover:bg-green-700 text-white" },
  rose:  { badge: "bg-rose-600 text-white",   border: "border-rose-300",  btn: "bg-rose-600 hover:bg-rose-700 text-white" },
  teal:  { badge: "bg-teal-600 text-white",   border: "border-teal-300",  btn: "bg-teal-600 hover:bg-teal-700 text-white" },
  amber: { badge: "bg-amber-500 text-white",  border: "border-amber-300", btn: "bg-amber-500 hover:bg-amber-600 text-white" },
  slate: { badge: "bg-slate-600 text-white",  border: "border-slate-300", btn: "bg-slate-600 hover:bg-slate-700 text-white" },
};

function colorFor(c: string) {
  return COLOR_CLASSES[c] ?? COLOR_CLASSES["slate"]!;
}

// ── Card component ─────────────────────────────────────────────────────────────

function WorkflowCard({ card }: { card: WorkflowCard }) {
  const navigate = useNavigate();
  const col = colorFor(card.color);
  const isInternal = card.href.startsWith("/") && card.href !== "#";
  const isAnchor = card.href === "#";

  function handleGo() {
    if (isInternal) navigate(card.href);
  }

  return (
    <div className={`bg-white rounded-lg border-2 ${col.border} p-4 flex flex-col gap-2 shadow-sm`}>
      <div className="flex items-start gap-3">
        {card.num_label && (
          <span className={`shrink-0 w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${col.badge}`}>
            {card.num_label}
          </span>
        )}
        <div className="flex-1 min-w-0">
          <div className="font-semibold text-gray-900 text-sm leading-snug">
            {card.icon && <span className="mr-1">{card.icon}</span>}
            {card.title}
          </div>
          {card.description && (
            <p className="mt-1 text-xs text-gray-600 leading-relaxed">{card.description}</p>
          )}
        </div>
      </div>
      {card.link_label && !isAnchor && (
        <button
          onClick={handleGo}
          disabled={!isInternal}
          className={`mt-auto self-start px-3 py-1 rounded text-xs font-medium transition-colors ${
            isInternal ? col.btn : "bg-gray-200 text-gray-500 cursor-not-allowed"
          }`}
        >
          {card.link_label} →
        </button>
      )}
      {card.link_label && isAnchor && (
        <span className="mt-auto self-start px-3 py-1 rounded text-xs font-medium bg-gray-100 text-gray-500 italic">
          {card.link_label}
        </span>
      )}
    </div>
  );
}

// ── Section component ─────────────────────────────────────────────────────────

function WorkflowSection({ section, cards }: { section: WorkflowSection; cards: WorkflowCard[] }) {
  const [showTip, setShowTip] = useState(false);

  return (
    <div className="mb-8">
      <div className="flex items-center gap-2 mb-3">
        <h3 className="text-base font-semibold text-gray-800">{section.label}</h3>
        {section.tip_text && (
          <div className="relative">
            <button
              onClick={() => setShowTip((v) => !v)}
              className="w-5 h-5 rounded-full bg-gray-200 hover:bg-gray-300 text-gray-600 text-xs flex items-center justify-center font-bold transition-colors"
              title="Accounting note"
            >
              ?
            </button>
            {showTip && (
              <div
                className="absolute z-10 left-0 top-7 w-80 bg-amber-50 border border-amber-300 rounded-lg p-3 shadow-lg text-xs text-gray-700 leading-relaxed"
                onClick={() => setShowTip(false)}
              >
                <p className="font-semibold text-amber-800 mb-1">Accounting Note</p>
                {section.tip_text}
              </div>
            )}
          </div>
        )}
      </div>
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 gap-3">
        {cards.map((c) => (
          <WorkflowCard key={c.id} card={c} />
        ))}
      </div>
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function WorkflowGuideScreen() {
  const [tabs, setTabs] = useState<WorkflowTab[]>([]);
  const [activeTabId, setActiveTabId] = useState<number | null>(null);
  const [sections, setSections] = useState<WorkflowSection[]>([]);
  const [cards, setCards] = useState<WorkflowCard[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load tabs once
  useEffect(() => {
    getDb()
      .then((db) =>
        db.select<WorkflowTab[]>(
          "SELECT id, tab_key, icon, label, description, sort_order FROM workflow_tabs WHERE is_active=1 ORDER BY sort_order"
        )
      )
      .then((rows) => {
        setTabs(rows);
        if (rows.length > 0 && rows[0]) setActiveTabId(rows[0].id);
      })
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  // Load sections + cards when active tab changes
  useEffect(() => {
    if (activeTabId === null) return;
    getDb()
      .then((db) =>
        Promise.all([
          db.select<WorkflowSection[]>(
            "SELECT id, tab_id, label, tip_text, sort_order FROM workflow_sections WHERE tab_id=? AND is_active=1 ORDER BY sort_order",
            [activeTabId]
          ),
          db.select<WorkflowCard[]>(
            `SELECT wc.id, wc.section_id, wc.num_label, wc.icon, wc.title, wc.description,
                    wc.href, wc.link_label, wc.color, wc.sort_order
             FROM workflow_cards wc
             JOIN workflow_sections ws ON wc.section_id = ws.id
             WHERE ws.tab_id = ? AND wc.is_active = 1
             ORDER BY ws.sort_order, wc.sort_order`,
            [activeTabId]
          ),
        ])
      )
      .then(([secs, cds]) => {
        setSections(secs);
        setCards(cds);
      })
      .catch((e) => setError(String(e)));
  }, [activeTabId]);

  const activeTab = tabs.find((t) => t.id === activeTabId);

  if (loading) {
    return (
      <div className="p-8 text-gray-500 text-sm">Loading workflow guide…</div>
    );
  }

  if (error) {
    return (
      <div className="p-8 text-red-600 text-sm">Error: {error}</div>
    );
  }

  return (
    <div className="p-6 print:p-0">
      <div className="mb-6 flex items-center justify-between print:hidden">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Workflow Guide</h1>
          <p className="text-sm text-gray-500 mt-1">Step-by-step checklists for routine HOA accounting tasks</p>
        </div>
        <button
          onClick={() => window.print()}
          className="px-4 py-2 text-sm border border-gray-300 rounded hover:bg-gray-50 text-gray-700"
        >
          Print Cheatsheet
        </button>
      </div>
      {/* Print-only header */}
      <div className="hidden print:block mb-6">
        <h1 className="text-xl font-bold text-gray-900">HOA Accounting — Workflow Cheatsheet</h1>
        {activeTab && <p className="text-sm text-gray-600 mt-1">{activeTab.label}: {activeTab.description}</p>}
      </div>

      {/* Tab bar — hidden on print */}
      <div className="flex gap-1 border-b border-gray-200 mb-6 overflow-x-auto print:hidden">
        {tabs.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTabId(tab.id)}
            className={[
              "px-5 py-2.5 text-sm font-medium whitespace-nowrap border-b-2 transition-colors -mb-px",
              tab.id === activeTabId
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-800 hover:border-gray-300",
            ].join(" ")}
          >
            {tab.icon && <span className="mr-1.5">{tab.icon}</span>}
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab description */}
      {activeTab?.description && (
        <div className="mb-6 bg-blue-50 border border-blue-200 rounded-lg px-4 py-3 text-sm text-blue-800 leading-relaxed">
          {activeTab.description}
        </div>
      )}

      {/* Sections + cards */}
      {sections.length === 0 ? (
        <p className="text-gray-400 text-sm">No workflow steps defined for this tab.</p>
      ) : (
        sections.map((sec) => (
          <WorkflowSection
            key={sec.id}
            section={sec}
            cards={cards.filter((c) => c.section_id === sec.id)}
          />
        ))
      )}
    </div>
  );
}
