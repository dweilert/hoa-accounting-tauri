import { useEffect, useState, useCallback } from "react";
import { Modal } from "../components/Modal";
import {
  getAssumptions, saveAssumptions,
  listAssets, insertAsset, updateAsset, deleteAsset,
  listScenarios, insertScenario, updateScenario, deleteScenario,
  type Assumptions, type AssumptionsFormValues,
  type ReserveAsset, type AssetFormValues,
  type Scenario, type ScenarioFormValues,
} from "../repositories/reserveStudyRepo";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 }).format(n);
}

function r2(n: number) {
  return Math.round(n * 100) / 100;
}

const CURRENT_YEAR = new Date().getFullYear();

const CONDITIONS = ["Excellent", "Good", "Moderate", "Poor", "Critical"] as const;
type Condition = typeof CONDITIONS[number];

const CONDITION_STYLE: Record<Condition, string> = {
  Excellent: "bg-green-100 text-green-700",
  Good:      "bg-teal-100 text-teal-700",
  Moderate:  "bg-yellow-100 text-yellow-700",
  Poor:      "bg-orange-100 text-orange-700",
  Critical:  "bg-red-100 text-red-700",
};

// ── Funding plan computation ──────────────────────────────────────────────────

type FundingYear = {
  year: number;
  beginningBalance: number;
  contribution: number;
  investmentIncome: number;
  expenditures: { label: string; cost: number }[];
  totalSpent: number;
  endingBalance: number;
  deficit: boolean;
};

function computeFundingPlan(
  assumptions: Assumptions,
  assets: ReserveAsset[],
  openingBalance: number,
): FundingYear[] {
  const { study_year, projection_years, annual_contribution, contribution_growth_rate, investment_return_rate } = assumptions;

  const expenditureMap = new Map<number, { label: string; cost: number }[]>();
  for (const asset of assets) {
    if (asset.replacement_cost <= 0) continue;
    const replaceYear = asset.install_year + asset.useful_life_years;
    const yearsOut = Math.max(0, replaceYear - study_year);
    const inflated = r2(asset.replacement_cost * Math.pow(1 + asset.annual_inflation, yearsOut));
    const label = `${asset.asset_group} — ${asset.component}`;
    const bucket = expenditureMap.get(replaceYear) ?? [];
    bucket.push({ label, cost: inflated });
    expenditureMap.set(replaceYear, bucket);
  }

  const rows: FundingYear[] = [];
  let balance = openingBalance;
  let contribution = annual_contribution;

  for (let offset = 0; offset < projection_years; offset++) {
    const year = study_year + offset;
    const investmentIncome = balance > 0 && investment_return_rate > 0 ? r2(balance * investment_return_rate) : 0;
    const yearExp = expenditureMap.get(year) ?? [];
    const totalSpent = r2(yearExp.reduce((s, e) => s + e.cost, 0));
    const endingBalance = r2(balance + r2(contribution) + investmentIncome - totalSpent);

    rows.push({
      year,
      beginningBalance: balance,
      contribution: r2(contribution),
      investmentIncome,
      expenditures: yearExp,
      totalSpent,
      endingBalance,
      deficit: endingBalance < 0,
    });

    balance = endingBalance;
    contribution = r2(contribution * (1 + contribution_growth_rate));
  }

  return rows;
}

// ── Assumptions form ──────────────────────────────────────────────────────────

const DEFAULT_ASSUMPTIONS: AssumptionsFormValues = {
  study_year: CURRENT_YEAR,
  reserve_balance_override: null,
  annual_contribution: 0,
  contribution_growth_rate: 0.03,
  investment_return_rate: 0.01,
  num_lots: 1,
  projection_years: 30,
  notes: null,
};

function AssumptionsPanel({
  assumptions,
  onSaved,
}: {
  assumptions: Assumptions | null;
  onSaved: (a: Assumptions) => void;
}) {
  const [values, setValues] = useState<AssumptionsFormValues>(
    assumptions ?? DEFAULT_ASSUMPTIONS
  );
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);

  const set = <K extends keyof AssumptionsFormValues>(k: K, v: AssumptionsFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSave(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try {
      await saveAssumptions(values);
      const updated = await getAssumptions();
      if (updated) onSaved(updated);
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } finally {
      setSaving(false);
    }
  }

  const num = (label: string, field: keyof AssumptionsFormValues, step = "1") => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        type="number"
        step={step}
        value={values[field] === null ? "" : String(values[field])}
        onChange={(e) => set(field, e.target.value === "" ? null : Number(e.target.value) as AssumptionsFormValues[typeof field])}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );

  return (
    <form onSubmit={handleSave} className="space-y-5">
      <div className="bg-white border rounded-lg p-5">
        <h2 className="font-semibold text-gray-800 text-sm mb-4">Study Parameters</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {num("Study Start Year", "study_year")}
          {num("Projection Years", "projection_years")}
          {num("Number of Lots", "num_lots")}
        </div>
      </div>

      <div className="bg-white border rounded-lg p-5">
        <h2 className="font-semibold text-gray-800 text-sm mb-4">Funding Assumptions</h2>
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-3">
          {num("Opening Reserve Balance ($)", "reserve_balance_override", "0.01")}
          {num("Annual Contribution ($)", "annual_contribution", "0.01")}
          {num("Contribution Growth Rate", "contribution_growth_rate", "0.001")}
          {num("Investment Return Rate", "investment_return_rate", "0.001")}
        </div>
        <p className="mt-2 text-xs text-gray-400">
          Growth and return rates as decimals (e.g. 0.03 = 3%).
        </p>
      </div>

      <div className="flex items-center gap-4">
        <button
          type="submit"
          disabled={saving}
          className="px-5 py-2 bg-blue-600 text-white text-sm rounded-lg hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : "Save Assumptions"}
        </button>
        {saved && <span className="text-sm text-green-600">✓ Saved</span>}
      </div>
    </form>
  );
}

// ── Asset form ────────────────────────────────────────────────────────────────

const DEFAULT_ASSET: AssetFormValues = {
  asset_group: "",
  component: "",
  install_year: CURRENT_YEAR,
  useful_life_years: 20,
  condition: "Good",
  replacement_cost: 0,
  annual_inflation: 0.04,
  notes: null,
};

function AssetForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: ReserveAsset;
  onSave: (v: AssetFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<AssetFormValues>(
    initial
      ? { asset_group: initial.asset_group, component: initial.component, install_year: initial.install_year, useful_life_years: initial.useful_life_years, condition: initial.condition, replacement_cost: initial.replacement_cost, annual_inflation: initial.annual_inflation, notes: initial.notes }
      : DEFAULT_ASSET
  );
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof AssetFormValues>(k: K, v: AssetFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try { await onSave(values); } finally { setSaving(false); }
  }

  const inp = (label: string, field: keyof AssetFormValues, type = "text") => (
    <div>
      <label className="block text-xs font-medium text-gray-700 mb-1">{label}</label>
      <input
        type={type}
        step={type === "number" ? "any" : undefined}
        value={values[field] === null ? "" : String(values[field])}
        onChange={(e) => set(field, (type === "number" ? Number(e.target.value) : e.target.value) as AssetFormValues[typeof field])}
        className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
      />
    </div>
  );

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div className="grid grid-cols-2 gap-3">
        {inp("Asset Group *", "asset_group")}
        {inp("Component *", "component")}
        {inp("Install Year", "install_year", "number")}
        {inp("Useful Life (years)", "useful_life_years", "number")}
        {inp("Replacement Cost ($)", "replacement_cost", "number")}
        {inp("Annual Inflation Rate", "annual_inflation", "number")}
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Condition</label>
        <select
          value={values.condition}
          onChange={(e) => set("condition", e.target.value as Condition)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        >
          {CONDITIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
      </div>
      {inp("Notes", "notes")}
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button
          type="submit"
          disabled={saving || !values.asset_group || !values.component}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : initial ? "Save Changes" : "Add Asset"}
        </button>
      </div>
    </form>
  );
}

// ── Assets panel ──────────────────────────────────────────────────────────────

type AssetModal = { mode: "add" } | { mode: "edit"; asset: ReserveAsset } | null;

function AssetsPanel({ studyYear }: { studyYear: number }) {
  const [assets, setAssets] = useState<ReserveAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<AssetModal>(null);

  const load = useCallback(async () => {
    setAssets(await listAssets());
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: AssetFormValues) {
    if (modal?.mode === "edit") await updateAsset(modal.asset.id, values);
    else await insertAsset(values);
    setModal(null);
    await load();
  }

  async function handleDelete(asset: ReserveAsset) {
    if (!confirm(`Remove "${asset.asset_group} — ${asset.component}"?`)) return;
    await deleteAsset(asset.id);
    await load();
  }

  const replaceYear = (a: ReserveAsset) => a.install_year + a.useful_life_years;
  const yearsLeft = (a: ReserveAsset) => replaceYear(a) - studyYear;

  const yearColor = (yrs: number) =>
    yrs < 0 ? "text-red-600 font-semibold" :
    yrs < 3 ? "text-orange-600 font-semibold" :
    yrs < 6 ? "text-yellow-600" : "text-gray-500";

  const totalCost = assets.reduce((s, a) => s + a.replacement_cost, 0);

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <div className="space-y-3">
      <div className="flex justify-between items-center">
        <p className="text-xs text-gray-500">
          {assets.length} component{assets.length !== 1 ? "s" : ""} · Total replacement cost: {fmt(totalCost)}
        </p>
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
        >
          + Add Component
        </button>
      </div>

      <div className="border rounded-lg overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Group</th>
              <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Component</th>
              <th className="px-4 py-2 text-center text-xs font-medium text-gray-600">Condition</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Installed</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Replace Year</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Yrs Left</th>
              <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Replacement Cost</th>
              <th className="px-4 py-2" />
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {assets.length === 0 && (
              <tr><td colSpan={8} className="px-4 py-6 text-center text-gray-400 text-sm">No components yet. Click "+ Add Component" to start.</td></tr>
            )}
            {assets.map((a) => (
              <tr key={a.id}>
                <td className="px-4 py-2 text-gray-700 text-xs">{a.asset_group}</td>
                <td className="px-4 py-2 font-medium text-gray-800 text-xs">{a.component}</td>
                <td className="px-4 py-2 text-center">
                  <span className={`px-2 py-0.5 rounded text-xs font-medium ${CONDITION_STYLE[a.condition]}`}>
                    {a.condition}
                  </span>
                </td>
                <td className="px-4 py-2 text-right text-gray-500 text-xs">{a.install_year}</td>
                <td className="px-4 py-2 text-right text-gray-700 text-xs">{replaceYear(a)}</td>
                <td className={`px-4 py-2 text-right text-xs ${yearColor(yearsLeft(a))}`}>
                  {yearsLeft(a) < 0 ? `${Math.abs(yearsLeft(a))}yr overdue` : `${yearsLeft(a)} yr`}
                </td>
                <td className="px-4 py-2 text-right font-mono text-xs text-gray-800">{fmt(a.replacement_cost)}</td>
                <td className="px-4 py-2 text-right space-x-2 whitespace-nowrap">
                  <button onClick={() => setModal({ mode: "edit", asset: a })} className="text-xs text-blue-600 hover:underline">Edit</button>
                  <button onClick={() => handleDelete(a)} className="text-xs text-red-500 hover:underline">Remove</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Component" : "Edit Component"}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <AssetForm initial={modal.asset} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <AssetForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
  );
}

// ── Funding plan panel ────────────────────────────────────────────────────────

function FundingPlanPanel({ assumptions }: { assumptions: Assumptions | null }) {
  const [assets, setAssets] = useState<ReserveAsset[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    listAssets().then(setAssets).finally(() => setLoading(false));
  }, []);

  if (!assumptions) {
    return <p className="text-sm text-gray-400">Set assumptions first to generate a funding plan.</p>;
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  const openingBalance = assumptions.reserve_balance_override ?? 0;
  const rows = computeFundingPlan(assumptions, assets, openingBalance);
  const deficitYears = rows.filter((r) => r.deficit).length;

  return (
    <div className="space-y-3">
      <div className="flex gap-4 text-xs text-gray-500 bg-gray-50 rounded-lg p-3">
        <span>Opening balance: <strong className="text-gray-800">{fmt(openingBalance)}</strong></span>
        <span>·</span>
        <span>Annual contribution: <strong className="text-gray-800">{fmt(assumptions.annual_contribution)}</strong></span>
        <span>·</span>
        <span>Projection: <strong className="text-gray-800">{assumptions.projection_years} years</strong></span>
        {deficitYears > 0 && (
          <>
            <span>·</span>
            <span className="text-red-600 font-semibold">{deficitYears} deficit year{deficitYears !== 1 ? "s" : ""}</span>
          </>
        )}
      </div>

      <div className="border rounded-lg overflow-hidden overflow-x-auto">
        <table className="w-full text-xs whitespace-nowrap">
          <thead className="bg-gray-50 border-b">
            <tr>
              <th className="px-3 py-2 text-left font-medium text-gray-600">Year</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Beg. Balance</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Contribution</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Investment</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">Expenditures</th>
              <th className="px-3 py-2 text-right font-medium text-gray-600">End Balance</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 bg-white">
            {rows.map((r) => (
              <tr key={r.year} className={r.deficit ? "bg-red-50" : r.year === CURRENT_YEAR ? "bg-blue-50" : ""}>
                <td className="px-3 py-1.5 font-medium text-gray-800">
                  {r.year}
                  {r.expenditures.length > 0 && (
                    <span className="ml-1 text-orange-500" title={r.expenditures.map((e) => e.label).join(", ")}>●</span>
                  )}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-gray-700">{fmt(r.beginningBalance)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-green-700">{fmt(r.contribution)}</td>
                <td className="px-3 py-1.5 text-right font-mono text-green-600">{r.investmentIncome > 0 ? fmt(r.investmentIncome) : "—"}</td>
                <td className="px-3 py-1.5 text-right font-mono text-red-600">
                  {r.totalSpent > 0 ? (
                    <span title={r.expenditures.map((e) => `${e.label}: ${fmt(e.cost)}`).join("\n")}>
                      {fmt(r.totalSpent)}
                    </span>
                  ) : "—"}
                </td>
                <td className={`px-3 py-1.5 text-right font-mono font-semibold ${r.deficit ? "text-red-700" : "text-gray-900"}`}>
                  {fmt(r.endingBalance)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="text-xs text-gray-400">Orange dot (●) indicates a replacement expenditure year. Hover the expenditure amount to see components.</p>
    </div>
  );
}

// ── Scenario form ─────────────────────────────────────────────────────────────

function ScenarioForm({
  initial,
  onSave,
  onCancel,
}: {
  initial?: Scenario;
  onSave: (v: ScenarioFormValues) => Promise<void>;
  onCancel: () => void;
}) {
  const [values, setValues] = useState<ScenarioFormValues>(
    initial
      ? { scenario_name: initial.scenario_name, description: initial.description, emergency_cost: initial.emergency_cost, expected_year: initial.expected_year, notes: initial.notes }
      : { scenario_name: "", description: null, emergency_cost: 0, expected_year: null, notes: null }
  );
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof ScenarioFormValues>(k: K, v: ScenarioFormValues[K]) =>
    setValues((p) => ({ ...p, [k]: v }));

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSaving(true);
    try { await onSave(values); } finally { setSaving(false); }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Scenario Name *</label>
        <input
          value={values.scenario_name}
          onChange={(e) => set("scenario_name", e.target.value)}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Emergency Cost ($)</label>
          <input
            type="number"
            step="any"
            value={values.emergency_cost}
            onChange={(e) => set("emergency_cost", Number(e.target.value))}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
        <div>
          <label className="block text-xs font-medium text-gray-700 mb-1">Expected Year</label>
          <input
            type="number"
            value={values.expected_year ?? ""}
            onChange={(e) => set("expected_year", e.target.value ? Number(e.target.value) : null)}
            className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
          />
        </div>
      </div>
      <div>
        <label className="block text-xs font-medium text-gray-700 mb-1">Description</label>
        <textarea
          value={values.description ?? ""}
          onChange={(e) => set("description", e.target.value || null)}
          rows={2}
          className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>
      <div className="flex justify-end gap-3 pt-2 border-t">
        <button type="button" onClick={onCancel} className="px-4 py-2 text-sm text-gray-600 hover:text-gray-900">Cancel</button>
        <button
          type="submit"
          disabled={saving || !values.scenario_name}
          className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
        >
          {saving ? "Saving…" : initial ? "Save Changes" : "Add Scenario"}
        </button>
      </div>
    </form>
  );
}

// ── Scenarios panel ───────────────────────────────────────────────────────────

type ScenarioModal = { mode: "add" } | { mode: "edit"; scenario: Scenario } | null;

function ScenariosPanel({ assumptions }: { assumptions: Assumptions | null }) {
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [assets, setAssets] = useState<ReserveAsset[]>([]);
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState<ScenarioModal>(null);

  const load = useCallback(async () => {
    const [s, a] = await Promise.all([listScenarios(), listAssets()]);
    setScenarios(s);
    setAssets(a);
    setLoading(false);
  }, []);

  useEffect(() => { void load(); }, [load]);

  async function handleSave(values: ScenarioFormValues) {
    if (modal?.mode === "edit") await updateScenario(modal.scenario.id, values);
    else await insertScenario(values);
    setModal(null);
    await load();
  }

  async function handleDelete(s: Scenario) {
    if (!confirm(`Remove scenario "${s.scenario_name}"?`)) return;
    await deleteScenario(s.id);
    await load();
  }

  const planRows = assumptions
    ? computeFundingPlan(assumptions, assets, assumptions.reserve_balance_override ?? 0)
    : [];

  const numLots = assumptions?.num_lots ?? 1;
  const studyYear = assumptions?.study_year ?? CURRENT_YEAR;

  function analyzeScenario(s: Scenario) {
    const cost = s.emergency_cost;
    let balanceAtYear = 0;
    if (s.expected_year && planRows.length) {
      const row = planRows.find((r) => r.year === s.expected_year);
      balanceAtYear = row?.beginningBalance ?? 0;
    }
    const shortfall = Math.max(0, cost - balanceAtYear);
    const perLot = numLots > 0 ? r2(shortfall / numLots) : 0;
    const yearsToSave = s.expected_year ? Math.max(1, s.expected_year - studyYear) : 1;
    return { cost, balanceAtYear, shortfall, perLot, yearsToSave };
  }

  if (loading) return <p className="text-sm text-gray-400">Loading…</p>;

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          onClick={() => setModal({ mode: "add" })}
          className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700"
        >
          + Add Scenario
        </button>
      </div>

      {scenarios.length === 0 && (
        <p className="text-sm text-gray-400 italic">No scenarios yet. Add one to model emergency or unplanned expenditures.</p>
      )}

      {scenarios.map((s) => {
        const { cost, balanceAtYear, shortfall, yearsToSave } = analyzeScenario(s);
        const funded = shortfall === 0;
        return (
          <div key={s.id} className="border rounded-lg p-4 space-y-3 bg-white">
            <div className="flex items-start justify-between">
              <div>
                <p className="font-semibold text-gray-800 text-sm">{s.scenario_name}</p>
                {s.description && <p className="text-xs text-gray-500 mt-0.5">{s.description}</p>}
              </div>
              <div className="flex gap-2">
                <button onClick={() => setModal({ mode: "edit", scenario: s })} className="text-xs text-blue-600 hover:underline">Edit</button>
                <button onClick={() => handleDelete(s)} className="text-xs text-red-500 hover:underline">Remove</button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
              <div className="bg-gray-50 rounded p-2">
                <p className="text-gray-500">Emergency Cost</p>
                <p className="font-semibold text-gray-800 text-sm">{fmt(cost)}</p>
              </div>
              <div className="bg-gray-50 rounded p-2">
                <p className="text-gray-500">Expected Year</p>
                <p className="font-semibold text-gray-800 text-sm">{s.expected_year ?? "—"}</p>
              </div>
              <div className="bg-gray-50 rounded p-2">
                <p className="text-gray-500">Proj. Balance at Year</p>
                <p className="font-semibold text-gray-800 text-sm">{assumptions ? fmt(balanceAtYear) : "—"}</p>
              </div>
              <div className={`rounded p-2 ${funded ? "bg-green-50" : "bg-red-50"}`}>
                <p className={funded ? "text-green-600" : "text-red-600"}>Shortfall</p>
                <p className={`font-semibold text-sm ${funded ? "text-green-700" : "text-red-700"}`}>
                  {funded ? "Fully funded" : fmt(shortfall)}
                </p>
              </div>
            </div>

            {!funded && numLots > 0 && (
              <div className="text-xs text-gray-600 bg-amber-50 border border-amber-200 rounded p-3">
                <p className="font-medium text-amber-800 mb-1">Per-lot assessment options to cover the shortfall:</p>
                <div className="flex gap-6">
                  {[3, 5, 10].map((yrs) => {
                    const spread = Math.min(yrs, yearsToSave);
                    const annual = spread > 0 ? r2(shortfall / numLots / spread) : 0;
                    return (
                      <div key={yrs}>
                        <span className="text-amber-700">Over {yrs} yr: </span>
                        <span className="font-semibold text-amber-900">{fmt(annual)}/yr</span>
                        <span className="text-amber-600"> ({fmt(r2(annual / 12))}/mo)</span>
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>
        );
      })}

      {modal && (
        <Modal
          title={modal.mode === "add" ? "Add Scenario" : "Edit Scenario"}
          onClose={() => setModal(null)}
        >
          {modal.mode === "edit" ? (
            <ScenarioForm initial={modal.scenario} onSave={handleSave} onCancel={() => setModal(null)} />
          ) : (
            <ScenarioForm onSave={handleSave} onCancel={() => setModal(null)} />
          )}
        </Modal>
      )}
    </div>
  );
}

// ── Main screen ───────────────────────────────────────────────────────────────

type Tab = "assumptions" | "assets" | "funding-plan" | "scenarios";

const TABS: { key: Tab; label: string }[] = [
  { key: "assumptions", label: "Assumptions" },
  { key: "assets",      label: "Asset Inventory" },
  { key: "funding-plan", label: "Funding Plan" },
  { key: "scenarios",   label: "Scenarios" },
];

export function ReserveStudyScreen() {
  const [tab, setTab] = useState<Tab>("assumptions");
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getAssumptions()
      .then(setAssumptions)
      .catch((e) => setError(String(e)))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;

  return (
    <div className="p-8 max-w-6xl print:p-2">
      <div className="mb-6 flex items-center justify-between print:block">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Reserve Study</h1>
          <p className="text-sm text-gray-500 mt-0.5">Long-term capital reserve planning and funding projections.</p>
        </div>
        <div className="flex gap-2 print:hidden">
          <button
            onClick={() => window.print()}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 text-gray-700"
          >
            Print / PDF
          </button>
          <button
            onClick={async () => {
              const { listAssets: la } = await import("../repositories/reserveStudyRepo");
              const assets = await la();
              const rows = [
                ["Component", "Group", "Useful Life (yrs)", "Install Year", "Replacement Cost", "Condition"],
                ...assets.map((a) => [a.component, a.asset_group, a.useful_life_years, a.install_year, a.replacement_cost, a.condition]),
              ];
              const csv = rows.map((r) => r.map((v) => `"${String(v).replace(/"/g, '""')}"`).join(",")).join("\n");
              const blob = new Blob([csv], { type: "text/csv" });
              const url = URL.createObjectURL(blob);
              const a = document.createElement("a");
              a.href = url; a.download = "reserve_study_assets.csv"; a.click();
              URL.revokeObjectURL(url);
            }}
            className="px-3 py-1.5 text-sm border border-gray-300 rounded hover:bg-gray-50 text-gray-700"
          >
            Export CSV
          </button>
        </div>
      </div>

      {error && <p className="mb-4 text-sm text-red-600">{error}</p>}

      {/* Tabs */}
      <div className="flex gap-1 mb-6 border-b">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors ${
              tab === t.key
                ? "border-blue-600 text-blue-600"
                : "border-transparent text-gray-500 hover:text-gray-700"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "assumptions" && (
        <AssumptionsPanel
          assumptions={assumptions}
          onSaved={setAssumptions}
        />
      )}
      {tab === "assets" && (
        <AssetsPanel studyYear={assumptions?.study_year ?? CURRENT_YEAR} />
      )}
      {tab === "funding-plan" && (
        <FundingPlanPanel assumptions={assumptions} />
      )}
      {tab === "scenarios" && (
        <ScenariosPanel assumptions={assumptions} />
      )}
    </div>
  );
}
