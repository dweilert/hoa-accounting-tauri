import { useState } from "react";
import { PageLayout } from "../components/PageLayout";
import { getDb } from "../lib/db";
import { useTableSort } from "../lib/useTableSort";
import { SortableTh } from "../components/SortableTh";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

type CheckStatus = "PASS" | "WARN" | "FAIL";

type BillingMonth = {
  month: string;
  lots_billed: number;
  expected_lots: number;
  min_amount: number;
  max_amount: number;
  amount_ok: boolean;
};

type UtilityMonth = {
  month: string;
  has_vendor_bill: boolean;
  has_direct_entry: boolean;
  total: number;
};

type InterestMonth = {
  month: string;
  category: string;
  total: number;
};

type SanityResult = {
  billing: BillingMonth[];
  utility: UtilityMonth[];
  interest: InterestMonth[];
  allMonths: string[];
};

async function runSanityCheck(): Promise<SanityResult> {
  const db = await getDb();

  // All months that have at least one assessment (defines the expected billing universe)
  const monthRows = await db.select<{ month: string }[]>(`
    SELECT DISTINCT strftime('%Y-%m', assessment_date) AS month
    FROM assessments WHERE charge_type = 'DUES'
    ORDER BY month
  `);
  const allMonths = monthRows.map((r) => r.month);

  // Total active lots (= max lots_billed in any month — we use the highest observed count)
  const lotCountRow = await db.select<{ n: number }[]>(`
    SELECT COUNT(DISTINCT lot_id) AS n FROM assessments WHERE charge_type = 'DUES'
  `);
  const expectedLots = lotCountRow[0]?.n ?? 0;

  // Billing consistency: per month lot count + amount range
  const billingRows = await db.select<{
    month: string; lots_billed: number; min_amount: number; max_amount: number;
  }[]>(`
    SELECT strftime('%Y-%m', assessment_date) AS month,
           COUNT(DISTINCT lot_id)             AS lots_billed,
           MIN(amount)                        AS min_amount,
           MAX(amount)                        AS max_amount
    FROM assessments WHERE charge_type = 'DUES'
    GROUP BY month ORDER BY month
  `);

  const billing: BillingMonth[] = billingRows.map((r) => ({
    ...r,
    expected_lots: expectedLots,
    amount_ok: Math.abs(r.max_amount - r.min_amount) < 0.01,
  }));

  // Utility: vendor bills
  const utilVendor = await db.select<{ month: string; total: number }[]>(`
    SELECT strftime('%Y-%m', vb.invoice_date) AS month, SUM(vb.amount) AS total
    FROM vendor_bills vb
    JOIN categories c ON c.id = vb.category_id
    WHERE c.name = 'Utilities'
    GROUP BY month
  `);
  const utilVendorMap = new Map(utilVendor.map((r) => [r.month, r.total]));

  // Utility: direct income_batch entries (negative = outflow)
  const utilDirect = await db.select<{ month: string; total: number }[]>(`
    SELECT strftime('%Y-%m', ib.income_date) AS month, SUM(-ib.amount) AS total
    FROM income_batches ib
    JOIN categories c ON c.id = ib.category_id
    WHERE c.name = 'Utilities'
    GROUP BY month
  `);
  const utilDirectMap = new Map(utilDirect.map((r) => [r.month, r.total]));

  const utility: UtilityMonth[] = allMonths.map((month) => ({
    month,
    has_vendor_bill: utilVendorMap.has(month),
    has_direct_entry: utilDirectMap.has(month),
    total: (utilVendorMap.get(month) ?? 0) + (utilDirectMap.get(month) ?? 0),
  }));

  // Interest income: any INCOME category with "interest" in name
  const interestRows = await db.select<{ month: string; category: string; total: number }[]>(`
    SELECT strftime('%Y-%m', ib.income_date) AS month,
           c.name AS category,
           SUM(ib.amount) AS total
    FROM income_batches ib
    JOIN categories c ON c.id = ib.category_id
    WHERE c.category_type = 'INCOME'
      AND (LOWER(c.name) LIKE '%interest%' OR LOWER(c.name) LIKE '%bank%')
    GROUP BY month, c.name
    ORDER BY month, c.name
  `);
  const interest: InterestMonth[] = interestRows;

  return { billing, utility, interest, allMonths };
}

function StatusBadge({ status }: { status: CheckStatus }) {
  const cls =
    status === "PASS" ? "bg-green-100 text-green-700" :
    status === "WARN" ? "bg-yellow-100 text-yellow-700" :
    "bg-red-100 text-red-700";
  return <span className={`px-2 py-0.5 rounded text-xs font-semibold ${cls}`}>{status}</span>;
}

function SectionHeader({ title, status }: { title: string; status: CheckStatus }) {
  return (
    <div className="flex items-center gap-3 mb-3">
      <h3 className="font-semibold text-gray-900 text-sm">{title}</h3>
      <StatusBadge status={status} />
    </div>
  );
}

export function SanityCheckScreen() {
  const [result, setResult] = useState<SanityResult | null>(null);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setError(null);
    try {
      setResult(await runSanityCheck());
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }

  // Derive overall statuses
  const billingStatus: CheckStatus = !result ? "PASS" :
    result.billing.some((r) => r.lots_billed !== r.expected_lots) ? "FAIL" :
    result.billing.some((r) => !r.amount_ok) ? "WARN" : "PASS";

  const interestSet = new Set(result?.interest.map((r) => r.month) ?? []);
  const utilityMissing = result?.utility.filter((u) => !u.has_vendor_bill && !u.has_direct_entry) ?? [];
  const interestMissing = result?.allMonths.filter((m) => !interestSet.has(m)) ?? [];

  const utilityStatus: CheckStatus = !result ? "PASS" : utilityMissing.length > 0 ? "WARN" : "PASS";
  const interestStatus: CheckStatus = !result ? "PASS" : interestMissing.length > 0 ? "WARN" : "PASS";

  const billingSort = useTableSort(result?.billing ?? [], {
    month: (r) => r.month,
    lotsBilled: (r) => r.lots_billed,
    expected: (r) => r.expected_lots,
    min: (r) => r.min_amount,
    max: (r) => r.max_amount,
    status: (r) => (r.lots_billed !== r.expected_lots ? "FAIL" : !r.amount_ok ? "WARN" : "PASS"),
  });
  const utilitySort = useTableSort(result?.utility ?? [], {
    month: (u) => u.month,
    vendorBill: (u) => (u.has_vendor_bill ? 1 : 0),
    directEntry: (u) => (u.has_direct_entry ? 1 : 0),
    total: (u) => u.total,
    status: (u) => (u.has_vendor_bill || u.has_direct_entry ? "PASS" : "WARN"),
  });
  const interestSort = useTableSort(result?.interest ?? [], {
    month: (r) => r.month,
    category: (r) => r.category,
    total: (r) => r.total,
  });

  return (
    <PageLayout
      title="Sanity Check"
      subtitle="Verify billing completeness, expenses, and income against expected monthly patterns."
      helpId="sanity-check"
      actions={
        <button
          onClick={() => void run()}
          disabled={running}
          className="px-4 py-2 text-sm text-white rounded-lg disabled:opacity-50"
          style={{ backgroundColor: "#2f6046" }}
        >
          {running ? "Running…" : "Run Checks"}
        </button>
      }
    >
      <div className="space-y-6 max-w-3xl">
        {error && <p className="text-sm text-red-600">{error}</p>}

        {!result && !running && (
          <p className="text-sm text-gray-500">Click "Run Checks" to validate the data.</p>
        )}

        {result && (
          <>
            {/* ── A: Billing Consistency ── */}
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <SectionHeader
                title="(A) Dues Billing Consistency — same lots billed, same amount each month"
                status={billingStatus}
              />
              <table className="w-full text-xs">
                <thead className="bg-gray-50 border-b sticky top-0 z-10">
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <SortableTh label="Month" col="month" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} />
                    <SortableTh label="Lots Billed" col="lotsBilled" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} className="text-center" />
                    <SortableTh label="Expected" col="expected" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} className="text-center" />
                    <SortableTh label="Min Amount" col="min" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} right />
                    <SortableTh label="Max Amount" col="max" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} right />
                    <SortableTh label="Status" col="status" sortKey={billingSort.sortKey} sortDir={billingSort.sortDir} onSort={billingSort.toggleSort} className="text-center" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {billingSort.sorted.map((r) => {
                    const lotsOk = r.lots_billed === r.expected_lots;
                    const s: CheckStatus = !lotsOk ? "FAIL" : !r.amount_ok ? "WARN" : "PASS";
                    return (
                      <tr key={r.month} className={s !== "PASS" ? "bg-red-50" : ""}>
                        <td className="px-3 py-1.5 font-mono text-gray-700">{r.month}</td>
                        <td className={`px-3 py-1.5 text-center font-semibold ${lotsOk ? "text-gray-700" : "text-red-600"}`}>
                          {r.lots_billed}
                        </td>
                        <td className="px-3 py-1.5 text-center text-gray-500">{r.expected_lots}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-gray-700">{fmt(r.min_amount)}</td>
                        <td className={`px-3 py-1.5 text-right font-mono ${r.amount_ok ? "text-gray-700" : "text-orange-600 font-semibold"}`}>
                          {fmt(r.max_amount)}
                        </td>
                        <td className="px-3 py-1.5 text-center"><StatusBadge status={s} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>

            {/* ── B: Utility Expense Coverage ── */}
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <SectionHeader
                title="(B) Utility Expense — bill recorded each month"
                status={utilityStatus}
              />
              <table className="w-full text-xs">
                <thead className="bg-gray-50 border-b sticky top-0 z-10">
                  <tr className="bg-gray-50 border-b border-gray-200">
                    <SortableTh label="Month" col="month" sortKey={utilitySort.sortKey} sortDir={utilitySort.sortDir} onSort={utilitySort.toggleSort} />
                    <SortableTh label="Vendor Bill" col="vendorBill" sortKey={utilitySort.sortKey} sortDir={utilitySort.sortDir} onSort={utilitySort.toggleSort} className="text-center" />
                    <SortableTh label="Direct Entry" col="directEntry" sortKey={utilitySort.sortKey} sortDir={utilitySort.sortDir} onSort={utilitySort.toggleSort} className="text-center" />
                    <SortableTh label="Total" col="total" sortKey={utilitySort.sortKey} sortDir={utilitySort.sortDir} onSort={utilitySort.toggleSort} right />
                    <SortableTh label="Status" col="status" sortKey={utilitySort.sortKey} sortDir={utilitySort.sortDir} onSort={utilitySort.toggleSort} className="text-center" />
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {utilitySort.sorted.map((u) => {
                    const found = u.has_vendor_bill || u.has_direct_entry;
                    const s: CheckStatus = found ? "PASS" : "WARN";
                    return (
                      <tr key={u.month} className={!found ? "bg-yellow-50" : ""}>
                        <td className="px-3 py-1.5 font-mono text-gray-700">{u.month}</td>
                        <td className="px-3 py-1.5 text-center">{u.has_vendor_bill ? "✓" : "—"}</td>
                        <td className="px-3 py-1.5 text-center">{u.has_direct_entry ? "✓" : "—"}</td>
                        <td className={`px-3 py-1.5 text-right font-mono ${found ? "text-gray-700" : "text-gray-400"}`}>
                          {found ? fmt(u.total) : "—"}
                        </td>
                        <td className="px-3 py-1.5 text-center"><StatusBadge status={s} /></td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              {utilityMissing.length > 0 && (
                <p className="mt-2 text-xs text-yellow-700">
                  Missing: {utilityMissing.map((u) => u.month).join(", ")}
                </p>
              )}
            </div>

            {/* ── C: Interest Income Coverage ── */}
            <div className="bg-white border border-gray-200 rounded-xl p-4">
              <SectionHeader
                title="(C) Interest Income — recorded each month"
                status={interestStatus}
              />
              {result.interest.length === 0 ? (
                <p className="text-xs text-gray-500">No interest income records found.</p>
              ) : (
                <table className="w-full text-xs">
                  <thead className="bg-gray-50 border-b sticky top-0 z-10">
                    <tr className="bg-gray-50 border-b border-gray-200">
                      <SortableTh label="Month" col="month" sortKey={interestSort.sortKey} sortDir={interestSort.sortDir} onSort={interestSort.toggleSort} />
                      <SortableTh label="Category" col="category" sortKey={interestSort.sortKey} sortDir={interestSort.sortDir} onSort={interestSort.toggleSort} />
                      <SortableTh label="Amount" col="total" sortKey={interestSort.sortKey} sortDir={interestSort.sortDir} onSort={interestSort.toggleSort} right />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-gray-100">
                    {interestSort.sorted.map((r, i) => (
                      <tr key={i}>
                        <td className="px-3 py-1.5 font-mono text-gray-700">{r.month}</td>
                        <td className="px-3 py-1.5 text-gray-600">{r.category}</td>
                        <td className="px-3 py-1.5 text-right font-mono text-green-700">{fmt(r.total)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
              {interestMissing.length > 0 && (
                <p className="mt-2 text-xs text-yellow-700">
                  Months with no interest recorded: {interestMissing.join(", ")}
                </p>
              )}
              {interestMissing.length === 0 && result.interest.length > 0 && (
                <p className="mt-2 text-xs text-green-700">All billed months have interest income recorded.</p>
              )}
            </div>
          </>
        )}
      </div>
    </PageLayout>
  );
}
