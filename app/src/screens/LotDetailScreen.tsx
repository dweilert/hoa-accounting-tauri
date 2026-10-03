import { useEffect, useState, useCallback } from "react";
import { useParams } from "react-router-dom";
import { Modal } from "../components/Modal";
import { PageLayout } from "../components/PageLayout";
import { getLot, getOwnershipHistory, updateLot, updateOwnershipRow, type OwnershipRow } from "../repositories/lotRepo";
import { listAssessments, voidAssessment, writeOffAssessment, type AssessmentRow } from "../repositories/assessmentRepo";
import { listPaymentsForLot, type PaymentRow } from "../repositories/depositRepo";
import { LotForm } from "./LotsScreen";
import type { Lot, LotFormValues } from "../types/lot";
import { CHARGE_TYPE_LABELS, STATUS_COLORS } from "../types/assessment";
import { appConfirm } from "../components/AppDialogs";

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
  const lotId = Number(id);

  const [lot, setLot] = useState<Lot | null>(null);
  const [ownership, setOwnership] = useState<OwnershipRow[]>([]);
  const [assessments, setAssessments] = useState<AssessmentRow[]>([]);
  const [payments, setPayments] = useState<PaymentRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [editOpen, setEditOpen] = useState(false);
  const [editOwnership, setEditOwnership] = useState<OwnershipRow | null>(null);
  const [ownershipSaving, setOwnershipSaving] = useState(false);
  const [ownershipError, setOwnershipError] = useState<string | null>(null);

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

  async function handleVoidAssessment(a: AssessmentRow) {
    if (!await appConfirm(`Void ${CHARGE_TYPE_LABELS[a.charge_type]} of ${fmt(a.amount)} for Lot ${lot?.lot_number}?`)) return;
    await voidAssessment(a.id);
    await load();
  }

  async function handleWriteOffAssessment(a: AssessmentRow) {
    if (!await appConfirm(`Write off ${CHARGE_TYPE_LABELS[a.charge_type]} of ${fmt(a.amount)} for Lot ${lot?.lot_number}? This marks it uncollectible.`)) return;
    await writeOffAssessment(a.id);
    await load();
  }

  async function handleOwnershipSave(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!editOwnership) return;
    const fd = new FormData(e.currentTarget);
    const start_date = fd.get("start_date") as string;
    const end_date = (fd.get("end_date") as string) || null;
    const ownership_percent = Number(fd.get("ownership_percent"));
    if (!start_date) { setOwnershipError("Start date required."); return; }
    setOwnershipSaving(true);
    setOwnershipError(null);
    try {
      await updateOwnershipRow(editOwnership.id, start_date, end_date, ownership_percent);
      setEditOwnership(null);
      await load();
    } catch (err) {
      setOwnershipError(String(err));
    } finally {
      setOwnershipSaving(false);
    }
  }

  if (loading) return <div className="p-8"><p className="text-sm text-gray-400">Loading…</p></div>;
  if (error || !lot) return <div className="p-8"><p className="text-sm text-red-600">{error ?? "Not found."}</p></div>;

  const address = [lot.street_address_1, lot.street_address_2].filter(Boolean).join(", ");
  const cityLine = [lot.city, lot.state, lot.postal_code].filter(Boolean).join(", ");
  const currentOwners = ownership.filter((o) => !o.end_date);

  return (
    <PageLayout
      title={lot ? `Lot ${lot.lot_number}` : "Lot Detail"}
      {...(address ? { subtitle: `${address}${cityLine ? `, ${cityLine}` : ""}` } : {})}
      backTo="/lots"
      backLabel="Lots"
      helpId="lotDetail"
      actions={
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
      }
    >
    <div className="space-y-6">

      {/* AR summary */}
      <ARSummary assessments={assessments} />

      {/* Current owners */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Current Owner{currentOwners.length !== 1 ? "s" : ""}</h2>
        {currentOwners.length === 0 ? (
          <p className="text-sm text-gray-400 italic">No current owner on record.</p>
        ) : (
          <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Since</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Ownership %</th>
                  <th className="px-4 py-2 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {currentOwners.map((o) => (
                  <tr key={o.id} className="hover:bg-gray-50">
                    <td className="px-4 py-2 font-medium text-gray-800">{o.display_name}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{fmtDate(o.start_date)}</td>
                    <td className="px-4 py-2 text-right text-gray-500 text-xs">{o.ownership_percent}%</td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => { setOwnershipError(null); setEditOwnership(o); }}
                        className="text-xs text-blue-600 hover:underline"
                      >Edit</button>
                    </td>
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
        <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Type</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Description</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Status</th>
                <th className="px-4 py-2 w-24" />
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
              {assessments.length === 0 && (
                <tr><td colSpan={6} className="px-4 py-6 text-center text-gray-400 text-sm">No assessments.</td></tr>
              )}
              {assessments.map((a) => {
                const canAct = a.status === "OPEN" || a.status === "PARTIAL";
                return (
                <tr key={a.id} className={!canAct ? "opacity-50" : ""}>
                  <td className="px-4 py-2 text-gray-500 text-xs whitespace-nowrap">{fmtDate(a.assessment_date)}</td>
                  <td className="px-4 py-2 text-gray-700 text-xs">{CHARGE_TYPE_LABELS[a.charge_type]}</td>
                  <td className="px-4 py-2 text-gray-500 text-xs">{a.description ?? "—"}</td>
                  <td className="px-4 py-2 text-right font-mono text-xs text-gray-800">{fmt(a.amount)}</td>
                  <td className="px-4 py-2">
                    <span className={`px-2 py-0.5 rounded text-xs font-medium ${STATUS_COLORS[a.status]}`}>
                      {a.status}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-right whitespace-nowrap space-x-2">
                    {canAct && <button onClick={() => handleVoidAssessment(a)} className="text-xs text-gray-400 hover:text-red-600">Void</button>}
                    {canAct && <button onClick={() => handleWriteOffAssessment(a)} className="text-xs text-gray-400 hover:text-orange-600">Write Off</button>}
                  </td>
                </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      {/* Payments */}
      <section>
        <h2 className="text-sm font-semibold text-gray-800 mb-2">Payment History ({payments.length})</h2>
        <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
          <table className="w-full text-sm">
            <thead className="sticky top-0 z-10 bg-gray-50 border-b">
              <tr>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Date</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Method</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Check #</th>
                <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Memo</th>
                <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">Amount</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100">
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
          <div className="border rounded-lg overflow-auto max-h-[calc(100vh-200px)] ">
            <table className="w-full text-sm">
              <thead className="sticky top-0 z-10 bg-gray-50 border-b">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">Owner</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">From</th>
                  <th className="px-4 py-2 text-left text-xs font-medium text-gray-600">To</th>
                  <th className="px-4 py-2 text-right text-xs font-medium text-gray-600">%</th>
                  <th className="px-4 py-2 w-8" />
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {ownership.filter((o) => o.end_date).map((o) => (
                  <tr key={o.id} className="opacity-70 hover:opacity-100 hover:bg-gray-50">
                    <td className="px-4 py-2 text-gray-700">{o.display_name}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{fmtDate(o.start_date)}</td>
                    <td className="px-4 py-2 text-gray-500 text-xs">{o.end_date ? fmtDate(o.end_date) : "—"}</td>
                    <td className="px-4 py-2 text-right text-gray-500 text-xs">{o.ownership_percent}%</td>
                    <td className="px-4 py-2 text-right">
                      <button
                        onClick={() => { setOwnershipError(null); setEditOwnership(o); }}
                        className="text-xs text-blue-600 hover:underline"
                      >Edit</button>
                    </td>
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

      {editOwnership && (
        <Modal
          title={`Edit Ownership — ${editOwnership.display_name}`}
          onClose={() => setEditOwnership(null)}
        >
          <form onSubmit={handleOwnershipSave} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Start Date</label>
                <input
                  type="date"
                  name="start_date"
                  defaultValue={editOwnership.start_date}
                  required
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">End Date <span className="text-gray-400">(blank = current owner)</span></label>
                <input
                  type="date"
                  name="end_date"
                  defaultValue={editOwnership.end_date ?? ""}
                  className="w-full border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Ownership %</label>
              <input
                type="number"
                name="ownership_percent"
                defaultValue={editOwnership.ownership_percent}
                min={1}
                max={100}
                required
                className="w-32 border border-gray-300 rounded px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-400"
              />
            </div>
            {ownershipError && <p className="text-xs text-red-600">{ownershipError}</p>}
            <div className="flex justify-end gap-2 pt-2">
              <button
                type="button"
                onClick={() => setEditOwnership(null)}
                className="px-3 py-1.5 text-xs border border-gray-300 rounded text-gray-600 hover:bg-gray-50"
              >
                Cancel
              </button>
              <button
                type="submit"
                disabled={ownershipSaving}
                className="px-3 py-1.5 text-xs rounded text-white disabled:opacity-50"
                style={{ backgroundColor: "#2f6046" }}
              >
                {ownershipSaving ? "Saving…" : "Save"}
              </button>
            </div>
          </form>
        </Modal>
      )}
    </div>
    </PageLayout>
  );
}
