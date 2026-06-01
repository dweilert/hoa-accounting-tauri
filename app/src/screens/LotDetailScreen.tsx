import { useEffect, useState, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { Modal } from "../components/Modal";
import { getLot, getOwnershipHistory, updateLot, type OwnershipRow } from "../repositories/lotRepo";
import { listAssessments, type AssessmentRow } from "../repositories/assessmentRepo";
import { listPaymentsForLot, type PaymentRow } from "../repositories/depositRepo";
import { LotForm } from "./LotsScreen";
import type { Lot, LotFormValues } from "../types/lot";
import { CHARGE_TYPE_LABELS, STATUS_COLORS } from "../types/assessment";

function fmt(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

function fmtDate(s: string) {
  return new Date(s + "T00:00:00").toLocaleDateString("en-US", { year: "numeric", month: "short", day: "numeric" });
}

// ── AR summary card ───────────────────────────────────────────────────────────

function ARSummary({ assessments }: { assessments: AssessmentRow[] }) {
  const open = assessments.filter((a) => a.status === "OPEN");
  const partial = assessments.filter((a) => a.status === "PARTIAL");
  const openTotal = open.reduce((s, a) => s + a.amount, 0);
  const partialTotal = partial.reduce((s, a) => s + a.amount, 0);
  const total = openTotal + partialTotal;

  if (total === 0) {
    return (
      <div className="bg-green-50 border border-green-200 rounded-lg px-4 py-3 text-sm text-green-700 font-medium">
        Account current — no outstanding balance.
      </div>
    );
  }

  return (
    <div className="bg-yellow-50 border border-yellow-200 rounded-lg px-4 py-3">
      <p className="text-sm font-semibold text-yellow-800">Outstanding Balance: {fmt(total)}</p>
      <p className="text-xs text-yellow-600 mt-0.5">
        {open.length > 0 && <span>{open.length} open charge{open.length !== 1 ? "s" : ""} ({fmt(openTotal)})</span>}
        {open.length > 0 && partial.length > 0 && <span className="mx-1">·</span>}
        {partial.length > 0 && <span>{partial.length} partial charge{partial.length !== 1 ? "s" : ""} ({fmt(partialTotal)})</span>}
      </p>
    </div>
  );
}

// ── Screen ────────────────────────────────────────────────────────────────────

export function LotDetailScreen() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const lotId = Number(id);

  const [lot, setLot] = useState<Lot | null>(null);
  const [ownership, setOwnership] = useState<OwnershipRow[]>([]);
  const [assessments, setAssessments] = useState<AssessmentRow[]>([]);
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [l, o, a, p] = await Promise.all([
        getLot(lotId),
        getOwnershipHistory(lotId),
        listAssessments({ lotId }),
        listPaymentsForLot(lotId),
      ]);
      if (!l) { setError("Lot not found."); return; }
      setLot(l);
      setOwnership(o);
      setAssessments(a);
      setPayments(p);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, [lotId]);

  useEffect(() => { void load(); }, [load]);

  async function handleEditSave(values: LotFormValues) {
    await updateLot(lotId, values);
    setEditOpen(false);
    await load();
  }

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;
  if (error || !lot) return <div className="p-8"><p className="text-sm text-red-600">{error ?? "Not found."}</p></div>;

  const address = [lot.street_address_1, lot.street_address_2].filter(Boolean).join(", ");
  const cityLine = [lot.city, lot.state, lot.postal_code].filter(Boolean).join(", ");
  const currentOwners = ownership.filter((o) => !o.end_date);

  return (
    <div className="p-8 max-w-4xl space-y-6">

      {/* Header */}
      <div>
        <button
          onClick={() => navigate("/lots")}
          className="text-xs text-blue-600 hover:underline mb-3 inline-block"
        >
          ← Back to Lots
        </button>
        <div className="flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-bold text-gray-900">Lot {lot.lot_number}</h1>
            {address && <p className="text-sm text-gray-500 mt-0.5">{address}{cityLine ? `, ${cityLine}` : ""}</p>}
            {lot.legal_description && (
              <p className="text-xs text-gray-400 mt-0.5">{lot.legal_description}</p>
            )}
          </div>
          <div className="flex items-center gap-3">
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${lot.active_flag ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"}`}>
              {lot.active_flag ? "Active" : "Inactive"}
            </span>
            <button
              onClick={() => setEditOpen(true)}
              className="px-3 py-1.5 text-xs border border-gray-300 text-gray-600 rounded hover:bg-gray-50"
            >
              Edit Lot
            </button>
          </div>
        </div>
      </div>

      {/* AR summary */}
      <ARSummary assessments={assessments} />

      {/* Current owners */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Current Owner{currentOwners.length !== 1 ? "s" : ""}</h2>
        {currentOwners.length === 0 ? (
          <p className="text-sm text-gray-400 italic">No current owner on record.</p>
        ) : (
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Since</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Ownership %</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {currentOwners.map((o) => (
                  <tr key={o.id}>
                    <td className="px-4 py-2 font-medium text-gray-800">{o.display_name}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{fmtDate(o.start_date)}</td>
                    <td className="px-4 py-2 text-right text-gray-500 text-xs">{o.ownership_percent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Assessments */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Assessments ({assessments.length})</h2>
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {assessments.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">No assessments.</td></tr>
              )}
              {assessments.map((a) => (
                <tr key={a.id}>
                  <td className="px-4 py-2 text-gray-500 text-xs whitespace-nowrap">{fmtDate(a.assessment_date)}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{CHARGE_TYPE_LABELS[a.charge_type]}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{a.description ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-800">{fmt(a.amount)}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[a.status]}`}>
                      {a.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {/* Payments */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Payment History ({payments.length})</h2>
        <div className="border rounded-lg overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Method</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Check #</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Memo</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {payments.length === 0 && (
                <tr><td colSpan={5} className="px-4 py-6 text-center text-gray-400 text-sm">No payments on record.</td></tr>
              )}
              {payments.map((p) => (
                <tr key={p.id}>
                  <td className="px-4 py-2 text-gray-500 text-xs whitespace-nowrap">{fmtDate(p.payment_date)}</td>
                  <td className="px-4 py-2 text-gray-600 text-xs">{p.payment_method}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{p.check_number ?? "—"}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{p.memo ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-700">{fmt(p.amount)}</td>
                </tr>
              ))}
              {payments.length > 0 && (
                <tr className="bg-gray-50 font-semibold">
                  <td colSpan={4} className="px-4 py-2 text-xs text-gray-600">Total received</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-green-800">
                    {fmt(payments.reduce((s, p) => s + p.amount, 0))}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </section>

      {/* Ownership history */}
      {ownership.some((o) => o.end_date) && (
        <section>
          <h2 className="text-sm font-semibold text-gray-800 mb-2">Prior Owners</h2>
          <div className="border rounded-lg overflow-hidden">
            <table className="w-full text-sm">
              <thead className="bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">From</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">To</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">%</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 bg-white">
                {ownership.filter((o) => o.end_date).map((o) => (
                  <tr key={o.id} className="opacity-60">
                    <td className="px-4 py-2 text-gray-700">{o.display_name}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{fmtDate(o.start_date)}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{o.end_date ? fmtDate(o.end_date) : "—"}</td>
                    <td className="px-4 py-2 text-right text-gray-500 text-xs">{o.ownership_percent}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {editOpen && lot && (
        <Modal title={`Edit Lot ${lot.lot_number}`} onClose={() => setEditOpen(false)}>
          <LotForm
            initial={{ ...lot, owner_names: null }}
            onSave={handleEditSave}
            onCancel={() => setEditOpen(false)}
          />
        </Modal>
      )}
    </div>
  );
}
