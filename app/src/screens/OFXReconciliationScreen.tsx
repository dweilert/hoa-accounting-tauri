import { useEffect, useLayoutEffect, useState, useCallback, useRef } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";
import { listBankAccounts } from "../repositories/bankAccountRepo";
import { appAlert, appConfirm } from "../components/AppDialogs";
import type { BankAccount } from "../types/bankAccount";

// ── Types ─────────────────────────────────────────────────────────────────────

type OFXRow = {
  id: number;
  transaction_date: string;
  amount: number;
  description: string;
  validation_status: "UNVALIDATED" | "VALIDATED" | "IGNORED";
  linked_source_type: string | null;
  linked_deposit_batch_id: number | null;
};

type AppRow = {
  source_type: "INCOME_BATCH" | "DEPOSIT_BATCH" | "BILL_PAYMENT" | "RESERVE_TRANSFER";
  source_id: number;
  date: string;
  amount: number;
  description: string;
  detail: string;
  display_type: string;
  linked_ofx_id: number | null;
};

type Pair = {
  ofx: OFXRow;
  app: AppRow;
  linkType: "bank_transaction_links" | "deposit_batch";
  amountMatch: boolean;
  groupTotal: number;
  partial: boolean;
  dateMatchDays: number;
};

type ViewMode = "pairs" | "sidebyside" | "timeline";
type SortField = "date" | "amount";
type SortDir = "asc" | "desc";
type LineData = { x1: number; y1: number; x2: number; y2: number; key: string; status: "ok" | "warn" | "error"; pair: Pair; faded: boolean };
type ClipBox = { top: number; bottom: number; width: number };
type SvgDot  = { rowKey: string; x: number; y: number; isLinked: boolean; matched: boolean; inView: boolean };
type DotDrag = { fromKind: "ofx" | "app"; fromKey: string; fromX: number; fromY: number; mouseX: number; mouseY: number };

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

function daysDiff(a: string, b: string): number {
  return Math.abs((new Date(a).getTime() - new Date(b).getTime()) / 86400000);
}

function displayType(sourceType: string, amount: number, categoryType: string | null): string {
  if (sourceType === "BILL_PAYMENT") return "Expense";
  if (sourceType === "RESERVE_TRANSFER") return "Transfer";
  if (sourceType === "DEPOSIT_BATCH") return "Deposit";
  return categoryType === "EXPENSE" || amount < 0 ? "Expense" : "Income";
}

function pairStatus(p: Pair): "ok" | "warn" | "error" {
  if (p.partial) return "warn";
  if (!p.amountMatch) return "error";
  if (p.dateMatchDays > 5) return "warn";
  return "ok";
}

function sortOFX(rows: OFXRow[], field: SortField, dir: SortDir): OFXRow[] {
  return [...rows].sort((a, b) => {
    const av = field === "date" ? a.transaction_date : a.amount;
    const bv = field === "date" ? b.transaction_date : b.amount;
    const c = av < bv ? -1 : av > bv ? 1 : 0;
    return dir === "asc" ? c : -c;
  });
}

function sortApp(rows: AppRow[], field: SortField, dir: SortDir): AppRow[] {
  return [...rows].sort((a, b) => {
    const av = field === "date" ? a.date : a.amount;
    const bv = field === "date" ? b.date : b.amount;
    const c = av < bv ? -1 : av > bv ? 1 : 0;
    return dir === "asc" ? c : -c;
  });
}

function todayStr(): string { return new Date().toISOString().slice(0, 10); }

function firstOfMonth(offset = 0): string {
  const d = new Date();
  d.setDate(1);
  d.setMonth(d.getMonth() + offset);
  return d.toISOString().slice(0, 10);
}

function applyPreset(preset: string): { from: string; to: string } {
  const now = new Date();
  const yr = now.getFullYear();
  if (preset === "thisMonth") {
    const first = new Date(now.getFullYear(), now.getMonth(), 1);
    return { from: first.toISOString().slice(0, 10), to: todayStr() };
  }
  if (preset === "lastMonth") {
    const first = new Date(now.getFullYear(), now.getMonth() - 1, 1);
    const last  = new Date(now.getFullYear(), now.getMonth(), 0);
    return { from: first.toISOString().slice(0, 10), to: last.toISOString().slice(0, 10) };
  }
  if (preset === "last3") {
    return { from: firstOfMonth(-2), to: todayStr() };
  }
  if (preset === "thisYear") {
    return { from: `${yr}-01-01`, to: todayStr() };
  }
  if (preset === "lastYear") {
    return { from: `${yr - 1}-01-01`, to: `${yr - 1}-12-31` };
  }
  return { from: firstOfMonth(0), to: todayStr() };
}

// ── Data loading ──────────────────────────────────────────────────────────────

type ScreenData = {
  pairs: Pair[];
  unmatchedOFX: OFXRow[];
  unmatchedApp: AppRow[];
  allOFX: OFXRow[];
  allApp: AppRow[];
};

async function loadData(bankAccountId: number, dateFrom: string, dateTo: string): Promise<ScreenData> {
  const db = await getDb();

  const allOFX = await db.select<OFXRow[]>(`
    SELECT bt.id, bt.transaction_date, bt.amount,
           COALESCE(bt.description,'') AS description,
           bt.validation_status,
           (SELECT btl.source_type FROM bank_transaction_links btl
             WHERE btl.bank_transaction_id = bt.id ORDER BY btl.id LIMIT 1) AS linked_source_type,
           (SELECT db2.id FROM deposit_batches db2
             WHERE db2.bank_transaction_id = bt.id ORDER BY db2.id LIMIT 1) AS linked_deposit_batch_id
    FROM bank_transactions bt
    WHERE bt.bank_account_id = ? AND bt.transaction_date >= ? AND bt.transaction_date <= ?
    ORDER BY bt.transaction_date, bt.id
  `, [bankAccountId, dateFrom, dateTo]);

  type LinkRow = {
    bank_transaction_id: number; source_type: string; source_id: number;
    app_date: string; app_amount: number; app_desc: string; app_detail: string; app_cat_type: string | null;
  };
  const linked = await db.select<LinkRow[]>(`
    SELECT btl.bank_transaction_id, btl.source_type, btl.source_id,
      CASE btl.source_type
        WHEN 'INCOME_BATCH'     THEN ib.income_date
        WHEN 'BILL_PAYMENT'     THEN bp.payment_date
        WHEN 'RESERVE_TRANSFER' THEN rt.transfer_date
        ELSE '' END AS app_date,
      CASE btl.source_type
        WHEN 'INCOME_BATCH'     THEN ib.amount
        WHEN 'BILL_PAYMENT'     THEN -bp.amount
        WHEN 'RESERVE_TRANSFER' THEN CASE WHEN rt.from_bank_account_id = bt.bank_account_id THEN -rt.amount ELSE rt.amount END
        ELSE 0 END AS app_amount,
      CASE btl.source_type
        WHEN 'INCOME_BATCH'     THEN COALESCE(ib.description,'')
        WHEN 'BILL_PAYMENT'     THEN COALESCE(NULLIF(b.description,''), 'Invoice ' || b.invoice_number)
        WHEN 'RESERVE_TRANSFER' THEN COALESCE(rt.description,'Reserve Transfer')
        ELSE '' END AS app_desc,
      CASE btl.source_type
        WHEN 'INCOME_BATCH'     THEN COALESCE(c.name,'')
        WHEN 'BILL_PAYMENT'     THEN COALESCE(v.vendor_name,'')
        WHEN 'RESERVE_TRANSFER' THEN COALESCE(rta.account_name,'') || ' → ' || COALESCE(rtb.account_name,'')
        ELSE '' END AS app_detail,
      c.category_type AS app_cat_type
    FROM bank_transaction_links btl
    JOIN bank_transactions bt ON bt.id = btl.bank_transaction_id
    LEFT JOIN income_batches ib    ON btl.source_type='INCOME_BATCH'     AND ib.id = btl.source_id
    LEFT JOIN categories c         ON btl.source_type='INCOME_BATCH'     AND c.id  = ib.category_id
    LEFT JOIN bill_payments bp     ON btl.source_type='BILL_PAYMENT'     AND bp.id = btl.source_id
    LEFT JOIN vendor_bills b       ON b.id = bp.vendor_bill_id
    LEFT JOIN vendors v            ON v.id = b.vendor_id
    LEFT JOIN reserve_transfers rt ON btl.source_type='RESERVE_TRANSFER' AND rt.id = btl.source_id
    LEFT JOIN bank_accounts rta    ON btl.source_type='RESERVE_TRANSFER' AND rta.id = rt.from_bank_account_id
    LEFT JOIN bank_accounts rtb    ON btl.source_type='RESERVE_TRANSFER' AND rtb.id = rt.to_bank_account_id
    WHERE bt.bank_account_id = ? AND bt.transaction_date >= ? AND bt.transaction_date <= ?
  `, [bankAccountId, dateFrom, dateTo]);

  type DepLinkRow = {
    bank_transaction_id: number; deposit_batch_id: number;
    deposit_date: string; total_amount: number; check_count: number; notes: string | null;
  };
  const depositLinks = await db.select<DepLinkRow[]>(`
    SELECT bt.id AS bank_transaction_id, db.id AS deposit_batch_id,
           db.deposit_date, db.total_amount, db.check_count, db.notes
    FROM deposit_batches db
    JOIN bank_transactions bt ON bt.id = db.bank_transaction_id
    WHERE bt.bank_account_id = ? AND bt.transaction_date >= ? AND bt.transaction_date <= ?
  `, [bankAccountId, dateFrom, dateTo]);

  const matchedOFXIds = new Set<number>();
  const pairs: Pair[] = [];

  for (const l of linked) {
    const ofx = allOFX.find((r) => r.id === l.bank_transaction_id);
    if (!ofx) continue;
    matchedOFXIds.add(ofx.id);
    const app: AppRow = {
      source_type: l.source_type as AppRow["source_type"],
      source_id: l.source_id,
      date: l.app_date,
      amount: l.app_amount,
      description: l.app_desc,
      detail: l.app_detail,
      display_type: displayType(l.source_type, l.app_amount, l.app_cat_type),
      linked_ofx_id: ofx.id,
    };
    pairs.push({
      ofx, app, linkType: "bank_transaction_links",
      amountMatch: Math.abs(ofx.amount - app.amount) < 0.01,
      groupTotal: app.amount,
      partial: false,
      dateMatchDays: daysDiff(ofx.transaction_date, app.date),
    });
  }

  for (const d of depositLinks) {
    const ofx = allOFX.find((r) => r.id === d.bank_transaction_id);
    if (!ofx) continue;
    matchedOFXIds.add(ofx.id);
    const app: AppRow = {
      source_type: "DEPOSIT_BATCH",
      source_id: d.deposit_batch_id,
      date: d.deposit_date,
      amount: d.total_amount,
      description: `Deposit Batch #${d.deposit_batch_id}`,
      detail: `${d.check_count} check${d.check_count !== 1 ? "s" : ""}${d.notes ? ` — ${d.notes}` : ""}`,
      display_type: "Deposit",
      linked_ofx_id: ofx.id,
    };
    pairs.push({
      ofx, app, linkType: "deposit_batch",
      amountMatch: Math.abs(ofx.amount - app.amount) < 0.01,
      groupTotal: app.amount,
      partial: false,
      dateMatchDays: daysDiff(ofx.transaction_date, app.date),
    });
  }

  pairs.sort((a, b) => a.ofx.transaction_date.localeCompare(b.ofx.transaction_date));

  const totals = new Map<number, number>();
  for (const p of pairs) totals.set(p.ofx.id, (totals.get(p.ofx.id) ?? 0) + p.app.amount);
  for (const p of pairs) {
    const tot = totals.get(p.ofx.id) ?? p.app.amount;
    p.groupTotal = tot;
    p.amountMatch = Math.abs(p.ofx.amount - tot) < 0.01;
    p.partial = p.linkType === "bank_transaction_links" && p.app.source_type !== "DEPOSIT_BATCH"
      && !p.amountMatch && p.ofx.amount * tot > 0 && Math.abs(tot) < Math.abs(p.ofx.amount);
  }
  const partialIds = new Set(pairs.filter((p) => p.partial).map((p) => p.ofx.id));
  const unmatchedOFX = allOFX.filter((r) => !matchedOFXIds.has(r.id) || partialIds.has(r.id));

  type RawIB = { id: number; income_date: string; amount: number; description: string | null; category_name: string | null; cat_type: string | null; ofx_id: number | null };
  const rawIB = await db.select<RawIB[]>(`
    SELECT ib.id, ib.income_date, ib.amount,
           COALESCE(ib.description,'') AS description, c.name AS category_name, c.category_type AS cat_type,
           btl.bank_transaction_id AS ofx_id
    FROM income_batches ib
    LEFT JOIN categories c ON c.id = ib.category_id
    LEFT JOIN bank_transaction_links btl ON btl.source_type='INCOME_BATCH' AND btl.source_id = ib.id
    WHERE ib.bank_account_id = ? AND ib.income_date >= ? AND ib.income_date <= ?
    ORDER BY ib.income_date
  `, [bankAccountId, dateFrom, dateTo]);

  type RawDB = { id: number; deposit_date: string; total_amount: number; check_count: number; notes: string | null; bank_transaction_id: number | null };
  const rawDB = await db.select<RawDB[]>(`
    SELECT id, deposit_date, total_amount, check_count, notes, bank_transaction_id
    FROM deposit_batches
    WHERE bank_account_id = ? AND deposit_date >= ? AND deposit_date <= ? AND status = 'POSTED'
    ORDER BY deposit_date
  `, [bankAccountId, dateFrom, dateTo]);

  type RawBP = { id: number; payment_date: string; amount: number; description: string; vendor_name: string | null; ofx_id: number | null };
  const rawBP = await db.select<RawBP[]>(`
    SELECT bp.id, bp.payment_date, bp.amount,
           COALESCE(NULLIF(b.description,''), 'Invoice ' || b.invoice_number) AS description,
           v.vendor_name, btl.bank_transaction_id AS ofx_id
    FROM bill_payments bp
    JOIN vendor_bills b ON b.id = bp.vendor_bill_id
    JOIN vendors v ON v.id = b.vendor_id
    LEFT JOIN bank_transaction_links btl ON btl.source_type='BILL_PAYMENT' AND btl.source_id = bp.id
    WHERE bp.bank_account_id = ? AND bp.payment_date >= ? AND bp.payment_date <= ?
    ORDER BY bp.payment_date
  `, [bankAccountId, dateFrom, dateTo]);

  type RawRT = { id: number; transfer_date: string; amount: number; description: string | null; from_id: number; from_name: string | null; to_name: string | null; ofx_id: number | null };
  const rawRT = await db.select<RawRT[]>(`
    SELECT rt.id, rt.transfer_date, rt.amount, rt.description, rt.from_bank_account_id AS from_id,
           fa.account_name AS from_name, ta.account_name AS to_name,
           (SELECT btl.bank_transaction_id FROM bank_transaction_links btl
              JOIN bank_transactions bt2 ON bt2.id = btl.bank_transaction_id
             WHERE btl.source_type='RESERVE_TRANSFER' AND btl.source_id = rt.id AND bt2.bank_account_id = ?) AS ofx_id
    FROM reserve_transfers rt
    LEFT JOIN bank_accounts fa ON fa.id = rt.from_bank_account_id
    LEFT JOIN bank_accounts ta ON ta.id = rt.to_bank_account_id
    WHERE (rt.from_bank_account_id = ? OR rt.to_bank_account_id = ?)
      AND rt.transfer_date >= ? AND rt.transfer_date <= ?
    ORDER BY rt.transfer_date
  `, [bankAccountId, bankAccountId, bankAccountId, dateFrom, dateTo]);

  const allApp: AppRow[] = [
    ...rawBP.map((r) => ({
      source_type: "BILL_PAYMENT" as const,
      source_id: r.id,
      date: r.payment_date,
      amount: -r.amount,
      description: r.description,
      detail: r.vendor_name ?? "",
      display_type: "Expense",
      linked_ofx_id: r.ofx_id,
    })),
    ...rawRT.map((r) => ({
      source_type: "RESERVE_TRANSFER" as const,
      source_id: r.id,
      date: r.transfer_date,
      amount: r.from_id === bankAccountId ? -r.amount : r.amount,
      description: r.description ?? "Reserve Transfer",
      detail: `${r.from_name ?? ""} → ${r.to_name ?? ""}`,
      display_type: "Transfer",
      linked_ofx_id: r.ofx_id,
    })),
    ...rawIB.map((r) => ({
      source_type: "INCOME_BATCH" as const,
      source_id: r.id,
      date: r.income_date,
      amount: r.amount,
      description: r.description ?? "",
      detail: r.category_name ?? "",
      display_type: displayType("INCOME_BATCH", r.amount, r.cat_type),
      linked_ofx_id: r.ofx_id,
    })),
    ...rawDB.map((r) => ({
      source_type: "DEPOSIT_BATCH" as const,
      source_id: r.id,
      date: r.deposit_date,
      amount: r.total_amount,
      description: `Deposit Batch #${r.id}`,
      detail: `${r.check_count} check${r.check_count !== 1 ? "s" : ""}${r.notes ? ` — ${r.notes}` : ""}`,
      display_type: "Deposit",
      linked_ofx_id: r.bank_transaction_id,
    })),
  ].sort((a, b) => a.date.localeCompare(b.date));

  const unmatchedApp = allApp.filter((a) => a.linked_ofx_id === null);

  return { pairs, unmatchedOFX, unmatchedApp, allOFX, allApp };
}

// ── Link / unlink ─────────────────────────────────────────────────────────────

async function unlinkPair(pair: Pair): Promise<void> {
  const db = await getDb();
  if (pair.linkType === "bank_transaction_links") {
    await db.execute(
      "DELETE FROM bank_transaction_links WHERE bank_transaction_id=? AND source_type=? AND source_id=?",
      [pair.ofx.id, pair.app.source_type, pair.app.source_id]
    );
  } else {
    await db.execute("UPDATE deposit_batches SET bank_transaction_id=NULL WHERE id=?", [pair.app.source_id]);
  }
  await db.execute("UPDATE bank_transactions SET validation_status='UNVALIDATED' WHERE id=?", [pair.ofx.id]);
}

async function linkOFXToApp(ofxId: number, ofxAmount: number, app: AppRow, alreadyLinked = 0): Promise<void> {
  if (app.linked_ofx_id !== null) {
    throw new Error("That app transaction is already linked to an OFX transaction. Unlink it first.");
  }
  if (ofxAmount * app.amount <= 0) {
    throw new Error(`Direction differs — OFX is ${fmt(ofxAmount)} but the app transaction is ${fmt(app.amount)}.`);
  }
  const newTotal = alreadyLinked + app.amount;
  if (Math.abs(newTotal) > Math.abs(ofxAmount) + 0.01) {
    throw new Error(
      `Amounts do not match — the linked total would be ${fmt(newTotal)} but the OFX transaction is ${fmt(ofxAmount)}.`
    );
  }
  const exact = Math.abs(newTotal - ofxAmount) < 0.01;
  if (app.source_type === "DEPOSIT_BATCH" && (alreadyLinked !== 0 || !exact)) {
    throw new Error(
      `Amounts do not match — OFX is ${fmt(ofxAmount)} but the deposit batch is ${fmt(app.amount)}. Deposit batches must match exactly.`
    );
  }
  const db = await getDb();
  if (app.source_type === "DEPOSIT_BATCH") {
    await db.execute("UPDATE deposit_batches SET bank_transaction_id=? WHERE id=?", [ofxId, app.source_id]);
  } else {
    await db.execute(
      "INSERT OR IGNORE INTO bank_transaction_links (bank_transaction_id, source_type, source_id) VALUES (?,?,?)",
      [ofxId, app.source_type, app.source_id]
    );
  }
  if (exact) {
    await db.execute("UPDATE bank_transactions SET validation_status='VALIDATED' WHERE id=?", [ofxId]);
  }
}

// ── Card components ───────────────────────────────────────────────────────────

type DragHandlers = {
  draggable?: boolean;
  onDragStart?: (e: React.DragEvent) => void;
  onDragEnd?: () => void;
  onDragOver?: (e: React.DragEvent) => void;
  onDragLeave?: () => void;
  onDrop?: (e: React.DragEvent) => void;
};

function OFXCard({ row, isDragSource, isDropTarget, ...drag }: { row: OFXRow; isDragSource?: boolean; isDropTarget?: boolean } & DragHandlers) {
  return (
    <div
      {...(drag.draggable ? { draggable: true } : {})}
      onDragStart={drag.onDragStart}
      onDragEnd={drag.onDragEnd}
      onDragOver={drag.onDragOver}
      onDragLeave={drag.onDragLeave}
      onDrop={drag.onDrop}
      className={`px-3 py-2.5 border-b border-gray-100 transition-colors select-none
        ${drag.draggable ? "cursor-grab active:cursor-grabbing" : ""}
        ${isDragSource ? "opacity-30" : ""}
        ${isDropTarget ? "bg-amber-100 ring-2 ring-inset ring-amber-400" : "hover:bg-gray-50"}
      `}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-gray-400">{row.transaction_date}</div>
          <div className="text-sm font-medium text-gray-800 truncate" title={row.description}>
            {row.description || "(no description)"}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className={`text-sm font-mono font-semibold ${row.amount < 0 ? "text-red-600" : "text-green-700"}`}>
            {fmt(row.amount)}
          </div>
        </div>
      </div>
    </div>
  );
}

function AppCard({ row, isDragSource, isDropTarget, ...drag }: { row: AppRow; isDragSource?: boolean; isDropTarget?: boolean } & DragHandlers) {
  return (
    <div
      {...(drag.draggable ? { draggable: true } : {})}
      onDragStart={drag.onDragStart}
      onDragEnd={drag.onDragEnd}
      onDragOver={drag.onDragOver}
      onDragLeave={drag.onDragLeave}
      onDrop={drag.onDrop}
      className={`px-3 py-2.5 border-b border-gray-100 transition-colors select-none
        ${drag.draggable ? "cursor-grab active:cursor-grabbing" : ""}
        ${isDragSource ? "opacity-30" : ""}
        ${isDropTarget ? "bg-amber-100 ring-2 ring-inset ring-amber-400" : "hover:bg-gray-50"}
      `}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 flex-1">
          <div className="text-xs text-gray-400">
            {row.date} · <span className="font-medium">{row.display_type}</span>
          </div>
          <div className="text-sm font-medium text-gray-800 truncate" title={row.description}>{row.description}</div>
          {row.detail && <div className="text-xs text-gray-400 truncate">{row.detail}</div>}
        </div>
        <div className="text-right shrink-0">
          <div className={`text-sm font-mono font-semibold ${row.amount < 0 ? "text-red-600" : "text-green-700"}`}>
            {fmt(row.amount)}
          </div>
        </div>
      </div>
    </div>
  );
}

// ── Sort header ───────────────────────────────────────────────────────────────

function SortBtn({ label, field, active, dir, onClick }: {
  label: string; field: SortField; active: SortField; dir: SortDir; onClick: (f: SortField) => void;
}) {
  return (
    <button onClick={() => onClick(field)}
      className="flex items-center gap-1 text-xs font-semibold uppercase tracking-wider text-gray-600 hover:text-gray-900">
      {label}{active === field ? (dir === "asc" ? " ▲" : " ▼") : " ⇅"}
    </button>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

export function OFXReconciliationScreen() {
  const [accounts, setAccounts] = useState<BankAccount[]>([]);
  const [accountId, setAccountId] = useState<number | null>(null);
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date(); d.setDate(1);
    return d.toISOString().slice(0, 10);
  });
  const [dateTo, setDateTo] = useState(todayStr());
  const [viewMode, setViewMode] = useState<ViewMode>("sidebyside");
  const [sortField, setSortField] = useState<SortField>("date");
  const [sortDir, setSortDir] = useState<SortDir>("asc");
  const [hideLinked, setHideLinked] = useState(false);
  const [data, setData] = useState<ScreenData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Connection-line measurement + dot-drag
  const sideBySideContainerRef = useRef<HTMLDivElement>(null);
  const ofxRowRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const appRowRefs = useRef<Map<string, HTMLDivElement>>(new Map());
  const ofxScrollRef = useRef<HTMLDivElement>(null);
  const appScrollRef = useRef<HTMLDivElement>(null);
  const measureRef = useRef<() => void>(() => {});
  const [clip, setClip] = useState<ClipBox>({ top: 0, bottom: 0, width: 0 });
  const [svgLines, setSvgLines] = useState<LineData[]>([]);
  const [ofxDots, setOfxDots] = useState<Map<string, SvgDot>>(new Map());
  const [appDots, setAppDots] = useState<Map<string, SvgDot>>(new Map());
  const [dotDrag, setDotDrag] = useState<DotDrag | null>(null);
  const [dotHover, setDotHover] = useState<string | null>(null);

  // Drag state
  const dragOFX = useRef<OFXRow | null>(null);
  const dragApp = useRef<AppRow | null>(null);
  const [dropTargetOFXId, setDropTargetOFXId] = useState<number | null>(null);
  const [dropTargetAppKey, setDropTargetAppKey] = useState<string | null>(null);
  const [dragSourceOFXId, setDragSourceOFXId] = useState<number | null>(null);
  const [dragSourceAppKey, setDragSourceAppKey] = useState<string | null>(null);

  const load = useCallback(async (keepView = false) => {
    if (!accountId || !dateFrom || !dateTo) return;
    if (!keepView) setLoading(true);
    setError(null);
    try { setData(await loadData(accountId, dateFrom, dateTo)); }
    catch (e) { setError(String(e)); }
    finally { setLoading(false); }
  }, [accountId, dateFrom, dateTo]);

  useEffect(() => {
    listBankAccounts(true).then((accts) => {
      setAccounts(accts);
      if (accts.length > 0) setAccountId(accts[0]!.id);
    }).catch((e) => setError(String(e)));
  }, []);

  useEffect(() => { if (accountId) void load(); }, [accountId, dateFrom, dateTo, load]);

  function toggleSort(field: SortField) {
    if (sortField === field) setSortDir((d) => d === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortDir("asc"); }
  }

  // Measure row positions → dots for every row + lines for matched pairs.
  // Re-run on scroll of either column, container resize and window resize.
  function measure() {
    const container = sideBySideContainerRef.current;
    const ofxArea = ofxScrollRef.current;
    const appArea = appScrollRef.current;
    if (viewMode !== "sidebyside" || !container || !ofxArea || !appArea || !data) {
      setSvgLines([]); setOfxDots(new Map()); setAppDots(new Map());
      return;
    }
    const cRect = container.getBoundingClientRect();
    const oA = ofxArea.getBoundingClientRect();
    const aA = appArea.getBoundingClientRect();
    const clipTop = Math.max(oA.top, aA.top) - cRect.top;
    const clipBottom = Math.min(oA.bottom, aA.bottom) - cRect.top;

    const fullOFX = new Set(data.pairs.filter((p) => p.amountMatch).map((p) => p.ofx.id));
    const newOfxDots = new Map<string, SvgDot>();
    for (const row of sortedOFX) {
      const el = ofxRowRefs.current.get(row.id);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      const mid = r.top + r.height / 2;
      newOfxDots.set(String(row.id), {
        rowKey: String(row.id),
        x: r.right - cRect.left,
        y: mid - cRect.top,
        isLinked: !!(row.linked_source_type || row.linked_deposit_batch_id),
        matched: fullOFX.has(row.id),
        inView: mid >= oA.top && mid <= oA.bottom,
      });
    }

    const newAppDots = new Map<string, SvgDot>();
    for (const row of sortedApp) {
      const key = `${row.source_type}-${row.source_id}`;
      const el = appRowRefs.current.get(key);
      if (!el) continue;
      const r = el.getBoundingClientRect();
      if (r.width === 0) continue;
      const mid = r.top + r.height / 2;
      newAppDots.set(key, {
        rowKey: key,
        x: r.left - cRect.left,
        y: mid - cRect.top,
        isLinked: row.linked_ofx_id !== null,
        matched: row.linked_ofx_id !== null && fullOFX.has(row.linked_ofx_id),
        inView: mid >= aA.top && mid <= aA.bottom,
      });
    }

    const clampY = (y: number) => Math.min(Math.max(y, clipTop), clipBottom);
    const lines: LineData[] = [];
    for (const pair of data.pairs) {
      const od = newOfxDots.get(String(pair.ofx.id));
      const ad = newAppDots.get(`${pair.app.source_type}-${pair.app.source_id}`);
      if (!od || !ad) continue;
      if ((od.y < clipTop && ad.y < clipTop) || (od.y > clipBottom && ad.y > clipBottom)) continue;
      lines.push({
        x1: od.x, y1: clampY(od.y), x2: ad.x, y2: clampY(ad.y),
        key: `${pair.ofx.id}-${pair.app.source_type}-${pair.app.source_id}`,
        status: pairStatus(pair),
        pair,
        faded: !od.inView || !ad.inView,
      });
    }

    setClip({ top: clipTop, bottom: clipBottom, width: cRect.width });
    setOfxDots(newOfxDots);
    setAppDots(newAppDots);
    setSvgLines(lines);
  }
  measureRef.current = measure;

  useLayoutEffect(() => {
    measureRef.current();
  }, [viewMode, data, sortField, sortDir, hideLinked, loading]);

  useEffect(() => {
    if (viewMode !== "sidebyside" || loading) return;
    let raf = 0;
    const schedule = () => {
      cancelAnimationFrame(raf);
      raf = requestAnimationFrame(() => measureRef.current());
    };
    const ofxArea = ofxScrollRef.current;
    const appArea = appScrollRef.current;
    const container = sideBySideContainerRef.current;
    ofxArea?.addEventListener("scroll", schedule, { passive: true });
    appArea?.addEventListener("scroll", schedule, { passive: true });
    window.addEventListener("resize", schedule);
    const ro = new ResizeObserver(schedule);
    if (container) ro.observe(container);
    return () => {
      cancelAnimationFrame(raf);
      ofxArea?.removeEventListener("scroll", schedule);
      appArea?.removeEventListener("scroll", schedule);
      window.removeEventListener("resize", schedule);
      ro.disconnect();
    };
  }, [viewMode, loading, data]);

  // Drag — OFX source
  function ofxDragStart(e: React.DragEvent, row: OFXRow) {
    dragOFX.current = row; dragApp.current = null;
    setDragSourceOFXId(row.id);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "ofx");
  }
  function ofxDragEnd() { setDragSourceOFXId(null); setDropTargetAppKey(null); dragOFX.current = null; }

  // Drag — App source
  function appDragStart(e: React.DragEvent, row: AppRow) {
    dragApp.current = row; dragOFX.current = null;
    setDragSourceAppKey(`${row.source_type}-${row.source_id}`);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", "app");
  }
  function appDragEnd() { setDragSourceAppKey(null); setDropTargetOFXId(null); dragApp.current = null; }

  async function dropOnApp(e: React.DragEvent, target: AppRow) {
    e.preventDefault();
    setDropTargetAppKey(null);
    const src = dragOFX.current;
    if (!src) return;
    dragOFX.current = null; setDragSourceOFXId(null);
    try { await linkOFXToApp(src.id, src.amount, target, linkedTotalFor(src.id)); await load(true); }
    catch (err) { await appAlert(err instanceof Error ? err.message : String(err)); }
  }

  async function dropOnOFX(e: React.DragEvent, target: OFXRow) {
    e.preventDefault();
    setDropTargetOFXId(null);
    const src = dragApp.current;
    if (!src) return;
    dragApp.current = null; setDragSourceAppKey(null);
    try { await linkOFXToApp(target.id, target.amount, src, linkedTotalFor(target.id)); await load(true); }
    catch (err) { await appAlert(err instanceof Error ? err.message : String(err)); }
  }

  async function handleUnlink(pair: Pair) {
    if (!await appConfirm(`Unlink?\n${pair.ofx.description} / ${fmt(pair.ofx.amount)}\n↔ ${pair.app.description}\n\nOFX reverts to UNVALIDATED.`)) return;
    try { await unlinkPair(pair); await load(true); }
    catch (e) { await appAlert(String(e)); }
  }

  // Dot-drag handlers
  function handleDotMouseDown(e: React.MouseEvent, kind: "ofx" | "app", key: string, x: number, y: number) {
    e.preventDefault();
    e.stopPropagation();
    setDotDrag({ fromKind: kind, fromKey: key, fromX: x, fromY: y, mouseX: x, mouseY: y });
  }

  function handleDotMouseUp(e: React.MouseEvent, kind: "ofx" | "app", key: string) {
    if (!dotDrag) return;
    e.stopPropagation();
    if (dotDrag.fromKind === kind) { setDotDrag(null); setDotHover(null); return; }
    let ofxRow: OFXRow | undefined;
    let appRow: AppRow | undefined;
    if (dotDrag.fromKind === "ofx") {
      ofxRow = sortedOFX.find((r) => String(r.id) === dotDrag.fromKey);
      appRow = sortedApp.find((r) => `${r.source_type}-${r.source_id}` === key);
    } else {
      appRow = sortedApp.find((r) => `${r.source_type}-${r.source_id}` === dotDrag.fromKey);
      ofxRow = sortedOFX.find((r) => String(r.id) === key);
    }
    setDotDrag(null); setDotHover(null);
    if (ofxRow && appRow) {
      void linkOFXToApp(ofxRow.id, ofxRow.amount, appRow, linkedTotalFor(ofxRow.id))
        .then(() => load(true))
        .catch((err) => void appAlert(err instanceof Error ? err.message : String(err)));
    }
  }

  async function handleLineClick(pair: Pair) {
    if (!await appConfirm(`Unlink ${fmt(pair.ofx.amount)} (${pair.ofx.transaction_date}) from ${pair.app.description}?`)) return;
    try { await unlinkPair(pair); await load(true); }
    catch (e) { await appAlert(String(e)); }
  }

  function linkedTotalFor(ofxId: number): number {
    return (data?.pairs ?? []).filter((p) => p.ofx.id === ofxId).reduce((sum, p) => sum + p.app.amount, 0);
  }

  async function handleAutoMatch() {
    if (!data) return;
    const ofxPool = data.unmatchedOFX.filter((r) => r.validation_status !== "IGNORED");
    const appPool = data.unmatchedApp;
    const remainingOf = (o: OFXRow) => o.amount - linkedTotalFor(o.id);
    type Pick = { o: OFXRow; apps: AppRow[] };
    const picks: Pick[] = [];
    const usedO = new Set<number>();
    const usedA = new Set<string>();

    const cands: { o: OFXRow; a: AppRow; days: number }[] = [];
    for (const o of ofxPool) {
      for (const a of appPool) {
        if (Math.abs(remainingOf(o) - a.amount) >= 0.01) continue;
        const days = daysDiff(o.transaction_date, a.date);
        if (days <= 5) cands.push({ o, a, days });
      }
    }
    cands.sort((x, y) => x.days - y.days);
    for (const c of cands) {
      const ak = appKey(c.a);
      if (usedO.has(c.o.id) || usedA.has(ak)) continue;
      usedO.add(c.o.id); usedA.add(ak); picks.push({ o: c.o, apps: [c.a] });
    }
    const exactCount = picks.length;

    for (const o of ofxPool) {
      if (usedO.has(o.id)) continue;
      const target = remainingOf(o);
      const near = appPool
        .filter((a) => !usedA.has(appKey(a)) && a.amount * target > 0 && Math.abs(a.amount) < Math.abs(target) - 0.005
          && daysDiff(o.transaction_date, a.date) <= 5)
        .sort((x, y) => daysDiff(o.transaction_date, x.date) - daysDiff(o.transaction_date, y.date))
        .slice(0, 40);
      let found: AppRow[] | null = null;
      for (let i = 0; i < near.length && !found; i++) {
        for (let j = i + 1; j < near.length && !found; j++) {
          const ai = near[i]!; const aj = near[j]!;
          if (Math.abs(ai.amount + aj.amount - target) < 0.01) { found = [ai, aj]; break; }
          for (let k = j + 1; k < near.length; k++) {
            const ak2 = near[k]!;
            if (Math.abs(ai.amount + aj.amount + ak2.amount - target) < 0.01) { found = [ai, aj, ak2]; break; }
          }
        }
      }
      if (found) {
        usedO.add(o.id);
        for (const a of found) usedA.add(appKey(a));
        picks.push({ o, apps: found });
      }
    }
    const splitCount = picks.length - exactCount;

    if (picks.length === 0) { await appAlert("No matches found: exact amount within 5 days, or 2-3 app transactions that add up to one OFX amount."); return; }
    if (!await appConfirm(`Link ${exactCount} exact match${exactCount !== 1 ? "es" : ""} and ${splitCount} split match${splitCount !== 1 ? "es" : ""} (several app transactions adding up to one OFX amount), all within 5 days?`)) return;
    let failed = 0;
    for (const pick of picks) {
      let running = linkedTotalFor(pick.o.id);
      try {
        for (const a of pick.apps) {
          await linkOFXToApp(pick.o.id, pick.o.amount, a, running);
          running += a.amount;
        }
      } catch { failed++; }
    }
    await load(true);
    await appAlert(`Linked ${picks.length - failed} of ${picks.length}.`);
  }

  // Derived display data
  const filteredPairs  = data ? (hideLinked ? [] : data.pairs) : [];
  const sortedPairs = [...filteredPairs].sort((a, b) => {
    const av = sortField === "date" ? a.ofx.transaction_date : a.ofx.amount;
    const bv = sortField === "date" ? b.ofx.transaction_date : b.ofx.amount;
    const c = av < bv ? -1 : av > bv ? 1 : 0;
    return sortDir === "asc" ? c : -c;
  });

  const fullyMatchedOFX = new Set((data?.pairs ?? []).filter((p) => p.amountMatch).map((p) => p.ofx.id));
  const baseOFX = hideLinked
    ? (data?.allOFX ?? []).filter((r) => !fullyMatchedOFX.has(r.id))
    : (data?.allOFX ?? []);
  const baseApp = hideLinked
    ? (data?.allApp ?? []).filter((r) => r.linked_ofx_id === null)
    : (data?.allApp ?? []);

  const sortedOFX = sortOFX(baseOFX, sortField, sortDir);
  const sortedApp = sortApp(baseApp, sortField, sortDir);

  type TRow = { kind: "ofx"; row: OFXRow; key: string; sortVal: string }
            | { kind: "app"; row: AppRow; key: string; sortVal: string };
  const timelineRows: TRow[] = data ? [
    ...baseOFX.map((r) => ({ kind: "ofx" as const, row: r, key: `ofx-${r.id}`, sortVal: sortField === "date" ? r.transaction_date : String(r.amount) })),
    ...baseApp.map((r) => ({ kind: "app" as const, row: r, key: `app-${r.source_type}-${r.source_id}`, sortVal: sortField === "date" ? r.date : String(r.amount) })),
  ].sort((a, b) => {
    const c = a.sortVal.localeCompare(b.sortVal);
    return sortDir === "asc" ? c : -c;
  }) : [];

  const totalOFX   = data?.allOFX.length ?? 0;
  const matchedCnt = fullyMatchedOFX.size;
  const appKey     = (r: AppRow) => `${r.source_type}-${r.source_id}`;

  return (
    <PageLayout title="OFX Reconciliation" subtitle="Match OFX bank transactions to app transactions." helpId="ofxReconciliation">
      <div className="space-y-3">

        {/* ── Controls row 1: account + dates + presets ── */}
        <div className="flex flex-wrap items-end gap-3">
          <div>
            <div className="text-xs text-gray-500 mb-1">Account</div>
            <select value={accountId ?? ""}
              onChange={(e) => setAccountId(Number(e.target.value))}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500">
              {accounts.map((a) => <option key={a.id} value={a.id}>{a.account_name}</option>)}
            </select>
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">From</div>
            <input type="date" value={dateFrom} onChange={(e) => setDateFrom(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div>
            <div className="text-xs text-gray-500 mb-1">To</div>
            <input type="date" value={dateTo} onChange={(e) => setDateTo(e.target.value)}
              className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>
          <div className="flex gap-1.5 flex-wrap self-end pb-0.5">
            {([
              ["thisMonth", "This month"],
              ["lastMonth", "Last month"],
              ["last3", "Last 3 mo"],
              ["thisYear", "This year"],
              ["lastYear", "Last year"],
            ] as [string, string][]).map(([k, label]) => (
              <button key={k}
                onClick={() => { const p = applyPreset(k); setDateFrom(p.from); setDateTo(p.to); }}
                className="px-2.5 py-1 text-xs rounded border border-gray-300 text-gray-600 hover:bg-gray-100">
                {label}
              </button>
            ))}
          </div>
        </div>

        {/* ── Controls row 2: view mode + sort + hide-linked ── */}
        <div className="flex flex-wrap items-center gap-3">
          {/* View mode */}
          <div className="flex gap-1.5">
            {(["pairs", "sidebyside", "timeline"] as ViewMode[]).map((m) => (
              <button key={m} onClick={() => setViewMode(m)}
                className={`px-3 py-1 text-xs rounded font-medium ${viewMode === m ? "text-white" : "border border-gray-300 text-gray-600 hover:bg-gray-50"}`}
                style={viewMode === m ? { backgroundColor: "#2f6046" } : {}}>
                {m === "pairs" ? "Pairs" : m === "sidebyside" ? "Side by Side" : "Timeline"}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-gray-300" />

          {/* Sort */}
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-500 font-medium">Sort:</span>
            <SortBtn label="Date" field="date" active={sortField} dir={sortDir} onClick={toggleSort} />
            <SortBtn label="Amount" field="amount" active={sortField} dir={sortDir} onClick={toggleSort} />
          </div>

          <div className="w-px h-5 bg-gray-300" />

          <button onClick={() => void handleAutoMatch()} disabled={!data}
            className="px-3 py-1 text-xs rounded font-medium text-white disabled:opacity-50"
            style={{ backgroundColor: "#7c3aed" }}>
            Auto-Match
          </button>

          <div className="w-px h-5 bg-gray-300" />

          {/* Hide linked */}
          <label className="flex items-center gap-2 text-xs text-gray-600 cursor-pointer select-none">
            <input type="checkbox" checked={hideLinked} onChange={(e) => setHideLinked(e.target.checked)}
              className="w-3.5 h-3.5 rounded" />
            Hide linked
          </label>
        </div>

        {/* Summary */}
        {data && (
          <div className="text-xs text-gray-500 flex gap-4">
            <span>{matchedCnt}/{totalOFX} OFX matched</span>
            <span className={data.unmatchedOFX.length > 0 ? "text-red-600 font-medium" : "text-green-600"}>
              {data.unmatchedOFX.length} unmatched OFX
            </span>
            <span className={data.unmatchedApp.length > 0 ? "text-red-600 font-medium" : "text-green-600"}>
              {data.unmatchedApp.length} unmatched app
            </span>
          </div>
        )}

        {error && <div className="p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}
        {loading && <p className="text-sm text-gray-400">Loading…</p>}

        {/* ══ PAIRS view ══ */}
        {viewMode === "pairs" && data && !loading && (
          <div className="space-y-5">
            {sortedPairs.length > 0 && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-gray-500 mb-2">Matched ({sortedPairs.length})</h2>
                <div className="border border-gray-200 rounded-lg overflow-hidden">
                  <table className="w-full text-sm">
                    <thead className="bg-gray-50 border-b">
                      <tr>
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-[42%]">OFX Transaction</th>
                        <th className="px-2 py-2 w-[6%]" />
                        <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-[42%]">App Transaction</th>
                        <th className="px-2 py-2 w-[10%]" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-gray-100">
                      {sortedPairs.map((p, i) => {
                        const st = pairStatus(p);
                        const cc = st === "ok" ? "#16a34a" : st === "warn" ? "#d97706" : "#dc2626";
                        return (
                          <tr key={i} className={st === "warn" ? "bg-amber-50" : st === "error" ? "bg-red-50" : ""}>
                            <td className="px-4 py-3">
                              <div className="text-xs text-gray-400">{p.ofx.transaction_date}</div>
                              <div className="text-sm font-medium text-gray-800 truncate" title={p.ofx.description}>{p.ofx.description}</div>
                              <div className={`text-sm font-mono font-semibold ${p.ofx.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(p.ofx.amount)}</div>
                            </td>
                            <td className="px-2 py-3 text-center">
                              <div className="flex flex-col items-center gap-0.5">
                                <div className="w-6 border-t-2" style={{ borderColor: cc }} />
                                <span className="text-xs font-bold" style={{ color: cc }}>{st === "ok" ? "✓" : st === "warn" ? "!" : "✗"}</span>
                                <div className="w-6 border-t-2" style={{ borderColor: cc }} />
                              </div>
                            </td>
                            <td className="px-4 py-3">
                              <div className="text-xs text-gray-400">{p.app.date}</div>
                              <div className="text-sm font-medium text-gray-800 truncate" title={p.app.description}>{p.app.description}</div>
                              {p.app.detail && <div className="text-xs text-gray-400">{p.app.detail}</div>}
                              <div className={`text-sm font-mono font-semibold ${p.app.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(p.app.amount)}</div>
                            </td>
                            <td className="px-2 py-3 text-right">
                              <button onClick={() => void handleUnlink(p)} className="text-xs text-gray-400 hover:text-red-600">Unlink</button>
                              {st !== "ok" && (
                                <div className="text-xs text-amber-600 mt-0.5">
                                  {!p.amountMatch ? (p.partial ? `partial ${fmt(p.groupTotal)} of ${fmt(p.ofx.amount)}` : `Δ${fmt(Math.abs(p.ofx.amount - p.groupTotal))}`) : `${Math.round(p.dateMatchDays)}d gap`}
                                </div>
                              )}
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              </section>
            )}

            {(data.unmatchedOFX.length > 0 || data.unmatchedApp.length > 0) && (
              <section>
                <h2 className="text-xs font-semibold uppercase tracking-wider text-red-500 mb-2">
                  Unmatched — drag OFX row onto App row (or reverse) to link · amounts must match exactly
                </h2>
                <div className="flex gap-4">
                  <div className="flex-1 border border-red-200 rounded-lg overflow-hidden">
                    <div className="bg-red-50 border-b border-red-200 px-3 py-2 text-xs font-semibold text-red-700">OFX ({data.unmatchedOFX.length})</div>
                    {data.unmatchedOFX.length === 0
                      ? <div className="px-4 py-6 text-center text-xs text-gray-400">All OFX matched ✓</div>
                      : sortOFX(data.unmatchedOFX, sortField, sortDir).map((row) => (
                        <OFXCard key={row.id} row={row} draggable
                          isDragSource={dragSourceOFXId === row.id}
                          isDropTarget={dropTargetOFXId === row.id}
                          onDragStart={(e) => ofxDragStart(e, row)}
                          onDragEnd={ofxDragEnd}
                          onDragOver={(e) => { if (dragApp.current) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTargetOFXId(row.id); } }}
                          onDragLeave={() => setDropTargetOFXId(null)}
                          onDrop={(e) => void dropOnOFX(e, row)}
                        />
                      ))
                    }
                  </div>
                  <div className="flex-1 border border-red-200 rounded-lg overflow-hidden">
                    <div className="bg-red-50 border-b border-red-200 px-3 py-2 text-xs font-semibold text-red-700">App ({data.unmatchedApp.length})</div>
                    {data.unmatchedApp.length === 0
                      ? <div className="px-4 py-6 text-center text-xs text-gray-400">All app matched ✓</div>
                      : sortApp(data.unmatchedApp, sortField, sortDir).map((row) => (
                        <AppCard key={appKey(row)} row={row} draggable
                          isDragSource={dragSourceAppKey === appKey(row)}
                          isDropTarget={dropTargetAppKey === appKey(row)}
                          onDragStart={(e) => appDragStart(e, row)}
                          onDragEnd={appDragEnd}
                          onDragOver={(e) => { if (dragOFX.current) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTargetAppKey(appKey(row)); } }}
                          onDragLeave={() => setDropTargetAppKey(null)}
                          onDrop={(e) => void dropOnApp(e, row)}
                        />
                      ))
                    }
                  </div>
                </div>
              </section>
            )}

            {matchedCnt > 0 && data.unmatchedOFX.length === 0 && data.unmatchedApp.length === 0 && (
              <div className="text-center py-4 text-sm text-green-700 font-medium">All {matchedCnt} transactions matched ✓</div>
            )}
          </div>
        )}

        {/* ══ SIDE-BY-SIDE view ══ */}
        {viewMode === "sidebyside" && data && !loading && (
          <div
            ref={sideBySideContainerRef}
            style={{ position: "relative", display: "flex", gap: 0 }}
            onMouseMove={(e) => {
              if (!dotDrag || !sideBySideContainerRef.current) return;
              const rect = sideBySideContainerRef.current.getBoundingClientRect();
              setDotDrag((d) => d ? { ...d, mouseX: e.clientX - rect.left, mouseY: e.clientY - rect.top } : null);
            }}
            onMouseUp={() => { setDotDrag(null); setDotHover(null); }}
            onMouseLeave={() => { setDotDrag(null); setDotHover(null); }}
          >
            {/* OFX column */}
            <div style={{ flex: 1, minWidth: 0 }} className="flex flex-col border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-50 border-b px-3 py-2 text-xs font-semibold text-gray-700">
                OFX ({sortedOFX.length})
              </div>
              <div ref={ofxScrollRef} className="overflow-y-auto" style={{ height: "calc(100vh - 380px)", minHeight: 320 }}>
              {sortedOFX.length === 0
                ? <div className="px-4 py-8 text-center text-xs text-gray-400">No OFX transactions</div>
                : sortedOFX.map((row) => (
                  <div key={row.id} ref={(el) => { if (el) ofxRowRefs.current.set(row.id, el); else ofxRowRefs.current.delete(row.id); }}>
                    <OFXCard row={row} draggable
                      isDragSource={dragSourceOFXId === row.id}
                      isDropTarget={dropTargetOFXId === row.id}
                      onDragStart={(e) => ofxDragStart(e, row)}
                      onDragEnd={ofxDragEnd}
                      onDragOver={(e) => { if (dragApp.current) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTargetOFXId(row.id); } }}
                      onDragLeave={() => setDropTargetOFXId(null)}
                      onDrop={(e) => void dropOnOFX(e, row)}
                    />
                  </div>
                ))
              }
              </div>
            </div>

            {/* Gutter spacer — 140px, SVG spans the full container */}
            <div style={{ width: "clamp(120px, 12vw, 260px)", flexShrink: 0 }} />

            {/* App column */}
            <div style={{ flex: 1, minWidth: 0 }} className="flex flex-col border border-gray-200 rounded-lg overflow-hidden">
              <div className="bg-gray-50 border-b px-3 py-2 text-xs font-semibold text-gray-700">
                App ({sortedApp.length})
              </div>
              <div ref={appScrollRef} className="overflow-y-auto" style={{ height: "calc(100vh - 380px)", minHeight: 320 }}>
              {sortedApp.length === 0
                ? <div className="px-4 py-8 text-center text-xs text-gray-400">No app transactions</div>
                : sortedApp.map((row) => (
                  <div key={appKey(row)} ref={(el) => { if (el) appRowRefs.current.set(appKey(row), el); else appRowRefs.current.delete(appKey(row)); }}>
                    <AppCard row={row} draggable
                      isDragSource={dragSourceAppKey === appKey(row)}
                      isDropTarget={dropTargetAppKey === appKey(row)}
                      onDragStart={(e) => appDragStart(e, row)}
                      onDragEnd={appDragEnd}
                      onDragOver={(e) => { if (dragOFX.current) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; setDropTargetAppKey(appKey(row)); } }}
                      onDragLeave={() => setDropTargetAppKey(null)}
                      onDrop={(e) => void dropOnApp(e, row)}
                    />
                  </div>
                ))
              }
              </div>
            </div>

            {/* ── SVG overlay: dots + lines + drag preview ── */}
            <svg
              pointerEvents="none"
              style={{ position: "absolute", top: 0, left: 0, width: "100%", height: "100%", overflow: "visible" }}
            >
              <defs>
                <clipPath id="recon-clip">
                  <rect x={-24} y={clip.top} width={clip.width + 48} height={Math.max(0, clip.bottom - clip.top)} />
                </clipPath>
              </defs>
              <g clipPath="url(#recon-clip)">
              {/* Lines connecting matched pairs — click to unlink */}
              {svgLines.map((l) => {
                const mx = 55;
                const d = `M ${l.x1} ${l.y1} C ${l.x1 + mx} ${l.y1}, ${l.x2 - mx} ${l.y2}, ${l.x2} ${l.y2}`;
                const color = l.status === "ok" ? "#4ade80" : l.status === "warn" ? "#fbbf24" : "#f87171";
                return (
                  <g key={l.key}>
                    {/* Wide invisible hit area so clicking is easy */}
                    {!l.faded && (
                      <path pointerEvents="all" d={d} fill="none" stroke="transparent" strokeWidth="14"
                        style={{ cursor: "pointer" }}
                        onClick={() => void handleLineClick(l.pair)}
                      />
                    )}
                    {/* Visible curve */}
                    <path pointerEvents="none" d={d} fill="none" stroke={color}
                      strokeWidth={l.faded ? 1.5 : 2.5} opacity={l.faded ? 0.18 : 0.9} />
                  </g>
                );
              })}

              {/* OFX dots — right edge of each OFX row */}
              {Array.from(ofxDots.values()).filter((d) => d.inView).map((dot) => {
                const isSource = dotDrag?.fromKind === "ofx" && dotDrag.fromKey === dot.rowKey;
                const isTarget = dotDrag?.fromKind === "app" && dotHover === dot.rowKey;
                return (
                  <circle key={`ofx-${dot.rowKey}`}
                    cx={dot.x} cy={dot.y}
                    r={isTarget ? 8 : isSource ? 7 : 5}
                    fill={isTarget ? "#3b82f6" : dot.matched ? "#16a34a" : dot.isLinked ? "#f59e0b" : "white"}
                    stroke={isTarget ? "#1d4ed8" : dot.matched ? "#15803d" : dot.isLinked ? "#b45309" : "#9ca3af"}
                    strokeWidth="2"
                    pointerEvents="all"
                    style={{ cursor: "crosshair" }}
                    onMouseDown={(e) => handleDotMouseDown(e, "ofx", dot.rowKey, dot.x, dot.y)}
                    onMouseUp={(e) => handleDotMouseUp(e, "ofx", dot.rowKey)}
                    onMouseEnter={() => { if (dotDrag?.fromKind === "app") setDotHover(dot.rowKey); }}
                    onMouseLeave={() => setDotHover(null)}
                  />
                );
              })}

              {/* App dots — left edge of each App row */}
              {Array.from(appDots.values()).filter((d) => d.inView).map((dot) => {
                const isSource = dotDrag?.fromKind === "app" && dotDrag.fromKey === dot.rowKey;
                const isTarget = dotDrag?.fromKind === "ofx" && dotHover === dot.rowKey;
                return (
                  <circle key={`app-${dot.rowKey}`}
                    cx={dot.x} cy={dot.y}
                    r={isTarget ? 8 : isSource ? 7 : 5}
                    fill={isTarget ? "#3b82f6" : dot.matched ? "#16a34a" : dot.isLinked ? "#f59e0b" : "white"}
                    stroke={isTarget ? "#1d4ed8" : dot.matched ? "#15803d" : dot.isLinked ? "#b45309" : "#9ca3af"}
                    strokeWidth="2"
                    pointerEvents="all"
                    style={{ cursor: "crosshair" }}
                    onMouseDown={(e) => handleDotMouseDown(e, "app", dot.rowKey, dot.x, dot.y)}
                    onMouseUp={(e) => handleDotMouseUp(e, "app", dot.rowKey)}
                    onMouseEnter={() => { if (dotDrag?.fromKind === "ofx") setDotHover(dot.rowKey); }}
                    onMouseLeave={() => setDotHover(null)}
                  />
                );
              })}
              </g>

              {/* Drag preview line */}
              {dotDrag && (
                <line
                  x1={dotDrag.fromX} y1={dotDrag.fromY}
                  x2={dotDrag.mouseX} y2={dotDrag.mouseY}
                  stroke="#3b82f6" strokeWidth="2" strokeDasharray="8 4" opacity="0.8"
                />
              )}
            </svg>
          </div>
        )}

        {/* ══ TIMELINE view ══ */}
        {viewMode === "timeline" && data && !loading && (
          <div className="border border-gray-200 rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-28">Date</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-20">Type</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600 w-28">Amount</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600 w-24">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {timelineRows.length === 0 && (
                  <tr><td colSpan={5} className="px-4 py-8 text-center text-gray-400">No transactions in range.</td></tr>
                )}
                {timelineRows.map((t) => {
                  if (t.kind === "ofx") {
                    const r = t.row;
                    const linked = r.linked_source_type || r.linked_deposit_batch_id;
                    return (
                      <tr key={t.key} className="hover:bg-blue-50">
                        <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{r.transaction_date}</td>
                        <td className="px-4 py-2"><span className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: "#dbeafe", color: "#1e40af" }}>OFX</span></td>
                        <td className="px-4 py-2 text-gray-800 truncate max-w-[260px]" title={r.description}>{r.description || "(no description)"}</td>
                        <td className={`px-4 py-2 text-right font-mono font-semibold ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
                        <td className="px-4 py-2">
                          {linked ? <span className="text-xs text-green-700">linked</span>
                                  : <span className="text-xs text-red-400">unmatched</span>}
                        </td>
                      </tr>
                    );
                  } else {
                    const r = t.row;
                    return (
                      <tr key={t.key} className="hover:bg-green-50">
                        <td className="px-4 py-2 text-xs text-gray-500 whitespace-nowrap">{r.date}</td>
                        <td className="px-4 py-2"><span className="text-xs px-1.5 py-0.5 rounded font-medium" style={{ backgroundColor: "#dcfce7", color: "#166534" }}>{r.display_type}</span></td>
                        <td className="px-4 py-2 text-gray-800 truncate max-w-[260px]" title={r.description}>
                          {r.description}{r.detail && <span className="text-gray-400"> — {r.detail}</span>}
                        </td>
                        <td className={`px-4 py-2 text-right font-mono font-semibold ${r.amount < 0 ? "text-red-600" : "text-green-700"}`}>{fmt(r.amount)}</td>
                        <td className="px-4 py-2">
                          {r.linked_ofx_id !== null ? <span className="text-xs text-green-700">linked</span>
                                                    : <span className="text-xs text-red-400">unmatched</span>}
                        </td>
                      </tr>
                    );
                  }
                })}
              </tbody>
            </table>
          </div>
        )}

        {!data && !loading && (
          <div className="text-center py-10 text-sm text-gray-400">Select an account and date range.</div>
        )}
      </div>
    </PageLayout>
  );
}
