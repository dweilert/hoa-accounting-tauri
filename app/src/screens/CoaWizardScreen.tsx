import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PageLayout } from "../components/PageLayout";
import { countCategories, bulkInsertCategories } from "../repositories/categoryRepo";
import type { CategoryFormValues, CategoryTypeValue, FundCodeValue } from "../types/category";

// ── Category template builder ─────────────────────────────────────────────────

type TemplateRow = CategoryFormValues & { key: string };

function buildTemplate(opts: {
  hasReserve: boolean;
  trackUtilities: boolean;
  hasAmenity: boolean;
}): TemplateRow[] {
  const rows: TemplateRow[] = [];
  let sort = 10;

  function add(
    key: string,
    code: string,
    name: string,
    type: CategoryTypeValue,
    fund: FundCodeValue,
    group?: string,
    desc?: string,
  ): void {
    rows.push({ key, code, name, category_type: type, fund_code: fund, sort_order: sort, group_name: group, description: desc, active_flag: 1 });
    sort += 10;
  }

  // ── Income ────────────────────────────────────────────────────────────────
  add("HOA_DUES", "HOA_DUES", "HOA Dues", "INCOME", "OPERATING", "Assessments");
  add("SPECIAL_ASSESS", "SPECIAL_ASSESS", "Special Assessments", "INCOME", "OPERATING", "Assessments");
  add("LATE_FEES", "LATE_FEES", "Late Fees", "INCOME", "OPERATING", "Assessments");
  add("INTEREST_INC", "INTEREST_INC", "Interest Income", "INCOME", "OPERATING", "Other Income");
  add("MISC_INC", "MISC_INC", "Miscellaneous Income", "INCOME", "OPERATING", "Other Income");

  if (opts.hasReserve) {
    add("RESERVE_CONTRIB", "RESERVE_CONTRIB", "Reserve Fund Contributions", "INCOME", "RESERVE", "Reserve");
    add("RESERVE_INTEREST", "RESERVE_INTEREST", "Reserve Fund Interest", "INCOME", "RESERVE", "Reserve");
  }
  if (opts.hasAmenity) {
    add("AMENITY_FEES", "AMENITY_FEES", "Amenity / Facility Fees", "INCOME", "OPERATING", "Other Income");
  }

  // ── Expense ───────────────────────────────────────────────────────────────
  add("MGMT_FEES", "MGMT_FEES", "Management Fees", "EXPENSE", "OPERATING", "Administration");
  add("ACCOUNTING", "ACCOUNTING", "Accounting & Audit", "EXPENSE", "OPERATING", "Administration");
  add("LEGAL", "LEGAL", "Legal Fees", "EXPENSE", "OPERATING", "Administration");
  add("INSURANCE", "INSURANCE", "Insurance", "EXPENSE", "OPERATING", "Administration");
  add("POSTAGE", "POSTAGE", "Postage & Printing", "EXPENSE", "OPERATING", "Administration");
  add("BANK_FEES", "BANK_FEES", "Bank Charges", "EXPENSE", "OPERATING", "Administration");

  add("LANDSCAPING", "LANDSCAPING", "Landscaping & Grounds", "EXPENSE", "OPERATING", "Maintenance");
  add("SNOW_REMOVAL", "SNOW_REMOVAL", "Snow Removal", "EXPENSE", "OPERATING", "Maintenance");
  add("REPAIRS_MAINT", "REPAIRS_MAINT", "Repairs & Maintenance", "EXPENSE", "OPERATING", "Maintenance");
  add("PAINTING", "PAINTING", "Painting & Exterior", "EXPENSE", "OPERATING", "Maintenance");
  add("PEST_CONTROL", "PEST_CONTROL", "Pest Control", "EXPENSE", "OPERATING", "Maintenance");

  if (opts.trackUtilities) {
    add("ELECTRIC", "ELECTRIC", "Electric", "EXPENSE", "OPERATING", "Utilities");
    add("GAS", "GAS", "Gas", "EXPENSE", "OPERATING", "Utilities");
    add("WATER_SEWER", "WATER_SEWER", "Water & Sewer", "EXPENSE", "OPERATING", "Utilities");
    add("TRASH", "TRASH", "Trash & Recycling", "EXPENSE", "OPERATING", "Utilities");
    add("INTERNET", "INTERNET", "Internet / Cable (common areas)", "EXPENSE", "OPERATING", "Utilities");
  }

  if (opts.hasAmenity) {
    add("POOL_MAINT", "POOL_MAINT", "Pool / Amenity Maintenance", "EXPENSE", "OPERATING", "Amenities");
    add("AMENITY_SUPPLIES", "AMENITY_SUPPLIES", "Amenity Supplies", "EXPENSE", "OPERATING", "Amenities");
  }

  if (opts.hasReserve) {
    add("RESERVE_CAPITAL", "RESERVE_CAPITAL", "Reserve Capital Projects", "EXPENSE", "RESERVE", "Reserve");
  }

  add("MISC_EXP", "MISC_EXP", "Miscellaneous Expense", "EXPENSE", "OPERATING", "Other");

  // ── Transfers ─────────────────────────────────────────────────────────────
  if (opts.hasReserve) {
    add("XFER_TO_RESERVE", "XFER_TO_RESERVE", "Transfer to Reserve Fund", "TRANSFER", "OPERATING", "Transfers");
    add("XFER_FROM_RESERVE", "XFER_FROM_RESERVE", "Transfer from Reserve Fund", "TRANSFER", "RESERVE", "Transfers");
  }

  return rows;
}

// ── Wizard steps ──────────────────────────────────────────────────────────────

type Step = "welcome" | "questions" | "preview" | "done";

export function CoaWizardScreen() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>("welcome");
  const [existingCount, setExistingCount] = useState(0);
  const [loading, setLoading] = useState(true);

  const [hasReserve, setHasReserve] = useState(true);
  const [trackUtilities, setTrackUtilities] = useState(true);
  const [hasAmenity, setHasAmenity] = useState(false);

  const [template, setTemplate] = useState<TemplateRow[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    countCategories().then((n) => { setExistingCount(n); setLoading(false); });
  }, []);

  function buildPreview() {
    const rows = buildTemplate({ hasReserve, trackUtilities, hasAmenity });
    setTemplate(rows);
    setSelected(new Set(rows.map((r) => r.key)));
    setStep("preview");
  }

  async function handleImport() {
    const toInsert = template.filter((r) => selected.has(r.key));
    setSaving(true);
    setError(null);
    try {
      await bulkInsertCategories(toInsert);
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  function toggleAll(checked: boolean) {
    setSelected(checked ? new Set(template.map((r) => r.key)) : new Set());
  }

  const TYPE_LABEL: Record<CategoryTypeValue, string> = { INCOME: "Income", EXPENSE: "Expense", TRANSFER: "Transfer" };
  const TYPE_COLOR: Record<CategoryTypeValue, string> = {
    INCOME: "text-green-700 bg-green-50",
    EXPENSE: "text-red-700 bg-red-50",
    TRANSFER: "text-blue-700 bg-blue-50",
  };

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;

  // ── Welcome ───────────────────────────────────────────────────────────────
  if (step === "welcome") {
    return (
      <PageLayout title="Chart of Accounts Wizard" subtitle="Answer questions to generate a starter chart of accounts." helpId="coaWizard" backTo="/categories" backLabel="Chart of Accounts">
      <div className="max-w-lg">
        <p className="text-sm text-gray-600 mb-4">
          This wizard generates a standard HOA chart of accounts based on a few questions. You can review and
          deselect any categories before they are added.
        </p>
        {existingCount > 0 && (
          <div className="mb-4 bg-amber-50 border border-amber-200 rounded-lg px-4 py-3 text-sm text-amber-800">
            You already have <strong>{existingCount}</strong> {existingCount === 1 ? "category" : "categories"}.
            The wizard will skip any codes that already exist — no duplicates will be created.
          </div>
        )}
        <div className="flex gap-3">
          <button
            onClick={() => setStep("questions")}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Get Started
          </button>
          <button
            onClick={() => navigate("/categories")}
            className="px-5 py-2 text-sm text-gray-600 hover:text-gray-900"
          >
            Cancel
          </button>
        </div>
      </div>
      </PageLayout>
    );
  }

  // ── Questions ─────────────────────────────────────────────────────────────
  if (step === "questions") {
    return (
      <PageLayout title="Chart of Accounts Wizard" subtitle="Answer questions to generate a starter chart of accounts." helpId="coaWizard" backTo="/categories" backLabel="Chart of Accounts">
      <div className="max-w-lg">
        <p className="text-sm font-semibold text-gray-700 mb-1">A few quick questions</p>
        <p className="text-sm text-gray-500 mb-6">Answer these to tailor the category list for your HOA.</p>

        <div className="space-y-5">
          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={hasReserve}
              onChange={(e) => setHasReserve(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
            />
            <div>
              <p className="text-sm font-medium text-gray-800">We maintain a Reserve Fund</p>
              <p className="text-xs text-gray-500">Adds reserve contribution/interest income, capital expense, and transfer categories.</p>
            </div>
          </label>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={trackUtilities}
              onChange={(e) => setTrackUtilities(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
            />
            <div>
              <p className="text-sm font-medium text-gray-800">We track utilities separately</p>
              <p className="text-xs text-gray-500">Adds individual categories for electric, gas, water/sewer, trash, and internet.</p>
            </div>
          </label>

          <label className="flex items-start gap-3 cursor-pointer">
            <input
              type="checkbox"
              checked={hasAmenity}
              onChange={(e) => setHasAmenity(e.target.checked)}
              className="mt-0.5 h-4 w-4 rounded border-gray-300 text-blue-600"
            />
            <div>
              <p className="text-sm font-medium text-gray-800">We have a pool or other shared amenity</p>
              <p className="text-xs text-gray-500">Adds amenity fee income and pool/amenity maintenance expense categories.</p>
            </div>
          </label>
        </div>

        <div className="flex gap-3 mt-8">
          <button
            onClick={buildPreview}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
          >
            Preview Categories →
          </button>
          <button onClick={() => setStep("welcome")} className="px-5 py-2 text-sm text-gray-600 hover:text-gray-900">
            Back
          </button>
        </div>
      </div>
      </PageLayout>
    );
  }

  // ── Preview ───────────────────────────────────────────────────────────────
  if (step === "preview") {
    const allChecked = selected.size === template.length;
    const byType = (["INCOME", "EXPENSE", "TRANSFER"] as CategoryTypeValue[]).map((t) => ({
      type: t,
      rows: template.filter((r) => r.category_type === t),
    })).filter((g) => g.rows.length > 0);

    return (
      <PageLayout title="Chart of Accounts Wizard" subtitle="Answer questions to generate a starter chart of accounts." helpId="coaWizard" backTo="/categories" backLabel="Chart of Accounts">
      <div className="max-w-2xl">
        <p className="text-sm font-semibold text-gray-700 mb-1">Review Categories</p>
        <p className="text-sm text-gray-500 mb-4">
          {selected.size} of {template.length} categories selected. Uncheck any you don't need.
        </p>

        {error && <p className="mb-3 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

        <div className="mb-3 flex items-center gap-2">
          <input
            type="checkbox"
            id="select-all"
            checked={allChecked}
            onChange={(e) => toggleAll(e.target.checked)}
            className="h-4 w-4 rounded border-gray-300 text-blue-600"
          />
          <label htmlFor="select-all" className="text-xs text-gray-500 cursor-pointer">
            {allChecked ? "Deselect all" : "Select all"}
          </label>
        </div>

        <div className="border rounded-lg overflow-hidden mb-6">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="w-8 px-3 py-2" />
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Code</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Name</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-3 py-2 text-left text-xs font-medium text-gray-600">Group</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {byType.map(({ type, rows }) => (
                <>
                  <tr key={`hdr-${type}`} className="bg-gray-50">
                    <td colSpan={5} className="px-3 py-1.5">
                      <span className={`text-xs font-semibold uppercase tracking-wide ${TYPE_COLOR[type].split(" ")[0]}`}>
                        {TYPE_LABEL[type]}
                      </span>
                    </td>
                  </tr>
                  {rows.map((r) => (
                    <tr key={r.key} className={!selected.has(r.key) ? "opacity-40" : ""}>
                      <td className="px-3 py-1.5 text-center">
                        <input
                          type="checkbox"
                          checked={selected.has(r.key)}
                          onChange={(e) => {
                            const next = new Set(selected);
                            if (e.target.checked) next.add(r.key); else next.delete(r.key);
                            setSelected(next);
                          }}
                          className="h-4 w-4 rounded border-gray-300 text-blue-600"
                        />
                      </td>
                      <td className="px-3 py-1.5 font-mono text-xs text-gray-700">{r.code}</td>
                      <td className="px-3 py-1.5 text-gray-800">{r.name}</td>
                      <td className="px-3 py-1.5">
                        <span className={`px-1.5 py-0.5 rounded text-xs font-medium ${TYPE_COLOR[r.category_type]}`}>
                          {TYPE_LABEL[r.category_type]}
                        </span>
                      </td>
                      <td className="px-3 py-1.5 text-xs text-gray-500">{r.group_name ?? ""}</td>
                    </tr>
                  ))}
                </>
              ))}
            </tbody>
          </table>
        </div>

        <div className="flex gap-3">
          <button
            onClick={() => void handleImport()}
            disabled={saving || selected.size === 0}
            className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {saving ? "Adding…" : `Add ${selected.size} Categories`}
          </button>
          <button onClick={() => setStep("questions")} className="px-5 py-2 text-sm text-gray-600 hover:text-gray-900">
            Back
          </button>
        </div>
      </div>
      </PageLayout>
    );
  }

  // ── Done ──────────────────────────────────────────────────────────────────
  return (
    <PageLayout title="Chart of Accounts Wizard" subtitle="Answer questions to generate a starter chart of accounts." helpId="coaWizard" backTo="/categories" backLabel="Chart of Accounts">
    <div className="max-w-lg">
      <p className="text-sm font-semibold text-gray-700 mb-2">Chart of Accounts Ready</p>
      <p className="text-sm text-gray-600 mb-6">
        Your categories have been added. You can edit, add, or remove them at any time from the Chart of Accounts screen.
      </p>
      <div className="flex gap-3">
        <button
          onClick={() => navigate("/categories")}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700"
        >
          View Chart of Accounts →
        </button>
        <button
          onClick={() => { setStep("welcome"); setExistingCount((n) => n + selected.size); }}
          className="px-5 py-2 text-sm text-gray-600 hover:text-gray-900"
        >
          Run Again
        </button>
      </div>
    </div>
    </PageLayout>
  );
}
