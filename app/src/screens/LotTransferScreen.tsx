import { useEffect, useState } from "react";
import { getDb } from "../lib/db";
import { PageLayout } from "../components/PageLayout";

// ── Types ─────────────────────────────────────────────────────────────────────

type Lot = {
  id: number;
  lot_number: string;
  street_address_1: string | null;
};

type CurrentOwner = {
  ownership_id: number;
  owner_id: number;
  display_name: string;
  email: string | null;
  start_date: string;
  ownership_percent: number;
};

type OpenAssessment = {
  id: number;
  assessment_date: string;
  due_date: string | null;
  amount: number;
  status: string;
  description: string | null;
};

type ExistingOwner = {
  id: number;
  display_name: string;
  email: string | null;
};

// ── Helpers ───────────────────────────────────────────────────────────────────

const fmt = (n: number) =>
  new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);

async function loadLots(): Promise<Lot[]> {
  const db = await getDb();
  return db.select<Lot[]>(
    "SELECT id, lot_number, street_address_1 FROM lots WHERE active_flag=1 ORDER BY lot_number"
  );
}

async function loadCurrentOwners(lotId: number): Promise<CurrentOwner[]> {
  const db = await getDb();
  return db.select<CurrentOwner[]>(
    `SELECT lo.id AS ownership_id, lo.owner_id, o.display_name, o.email,
            lo.start_date, lo.ownership_percent
     FROM lot_ownership lo
     JOIN owners o ON lo.owner_id = o.id
     WHERE lo.lot_id = ? AND lo.end_date IS NULL
     ORDER BY lo.is_primary_contact DESC, o.display_name`,
    [lotId]
  );
}

async function loadOpenAssessments(lotId: number): Promise<OpenAssessment[]> {
  const db = await getDb();
  return db.select<OpenAssessment[]>(
    `SELECT id, assessment_date, due_date, amount, status, description
     FROM assessments
     WHERE lot_id = ? AND status IN ('OPEN','PARTIAL')
     ORDER BY assessment_date DESC`,
    [lotId]
  );
}

async function loadAllOwners(): Promise<ExistingOwner[]> {
  const db = await getDb();
  return db.select<ExistingOwner[]>(
    "SELECT id, display_name, email FROM owners WHERE active_flag=1 ORDER BY display_name"
  );
}

async function executeTransfer(
  lotId: number,
  transferDate: string,
  currentOwnershipIds: number[],
  newOwnerIds: number[],   // must already exist in owners table
  notes: string
): Promise<void> {
  const db = await getDb();

  // Close all current ownership records
  for (const owId of currentOwnershipIds) {
    await db.execute(
      "UPDATE lot_ownership SET end_date = ? WHERE id = ?",
      [transferDate, owId]
    );
  }

  // Create new ownership records (split equally among new owners)
  const pct = newOwnerIds.length > 0 ? 100 / newOwnerIds.length : 100;
  for (let i = 0; i < newOwnerIds.length; i++) {
    await db.execute(
      `INSERT INTO lot_ownership (lot_id, owner_id, start_date, ownership_percent, is_primary_contact)
       VALUES (?, ?, ?, ?, ?)`,
      [lotId, newOwnerIds[i], transferDate, pct, i === 0 ? 1 : 0]
    );
  }

  // Audit note
  if (notes.trim()) {
    await db.execute(
      `INSERT INTO audit_log (entity_type, entity_id, action, after_json, changed_by)
       VALUES ('lot_ownership', ?, 'UPDATE', ?, 'lot-transfer-wizard')`,
      [lotId, JSON.stringify({ transfer_date: transferDate, note: notes })]
    );
  }
}

async function createNewOwner(
  ownerType: "PERSON" | "ENTITY" | "TRUST",
  displayName: string,
  firstName: string,
  lastName: string,
  email: string,
  phone: string,
  address: string,
  city: string,
  state: string,
  postalCode: string
): Promise<number> {
  const db = await getDb();
  const result = await db.execute(
    `INSERT INTO owners (owner_type, display_name, first_name, last_name, email, phone, mailing_address_1, city, state, postal_code)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
    [ownerType, displayName, firstName || null, lastName || null, email || null, phone || null,
     address || null, city || null, state || null, postalCode || null]
  );
  return result.lastInsertId as number;
}

// ── Step components ───────────────────────────────────────────────────────────

type Step = "select-lot" | "review" | "new-owner" | "confirm" | "done";

type WizardState = {
  lot: Lot | null;
  currentOwners: CurrentOwner[];
  openAssessments: OpenAssessment[];
  transferDate: string;
  newOwnerMode: "existing" | "create";
  selectedExistingOwnerIds: number[];
  newOwnerFirstName: string;
  newOwnerLastName: string;
  newOwnerEmail: string;
  newOwnerPhone: string;
  newOwnerAddress: string;
  newOwnerCity: string;
  newOwnerState: string;
  newOwnerPostal: string;
  notes: string;
};

const INIT: WizardState = {
  lot: null,
  currentOwners: [],
  openAssessments: [],
  transferDate: new Date().toISOString().slice(0, 10),
  newOwnerMode: "create",
  selectedExistingOwnerIds: [],
  newOwnerFirstName: "",
  newOwnerLastName: "",
  newOwnerEmail: "",
  newOwnerPhone: "",
  newOwnerAddress: "",
  newOwnerCity: "",
  newOwnerState: "TX",
  newOwnerPostal: "",
  notes: "",
};

// ── Main screen ───────────────────────────────────────────────────────────────

export function LotTransferScreen() {
  const [step, setStep] = useState<Step>("select-lot");
  const [wiz, setWiz] = useState<WizardState>(INIT);
  const [lots, setLots] = useState<Lot[]>([]);
  const [allOwners, setAllOwners] = useState<ExistingOwner[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([loadLots(), loadAllOwners()])
      .then(([l, o]) => { setLots(l); setAllOwners(o); })
      .catch((e) => setError(String(e)));
  }, []);

  const set = <K extends keyof WizardState>(k: K, v: WizardState[K]) =>
    setWiz((p) => ({ ...p, [k]: v }));

  async function selectLot(lot: Lot) {
    setBusy(true);
    try {
      const [owners, assessments] = await Promise.all([
        loadCurrentOwners(lot.id),
        loadOpenAssessments(lot.id),
      ]);
      setWiz((p) => ({ ...p, lot, currentOwners: owners, openAssessments: assessments }));
      setStep("review");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  async function handleTransfer() {
    if (!wiz.lot) return;
    setBusy(true);
    setError(null);
    try {
      let newOwnerIds: number[] = [];

      if (wiz.newOwnerMode === "existing") {
        newOwnerIds = wiz.selectedExistingOwnerIds;
      } else {
        const displayName = `${wiz.newOwnerFirstName} ${wiz.newOwnerLastName}`.trim() || "New Owner";
        const id = await createNewOwner(
          "PERSON", displayName,
          wiz.newOwnerFirstName, wiz.newOwnerLastName,
          wiz.newOwnerEmail, wiz.newOwnerPhone,
          wiz.newOwnerAddress, wiz.newOwnerCity, wiz.newOwnerState, wiz.newOwnerPostal
        );
        newOwnerIds = [id];
      }

      if (newOwnerIds.length === 0) { setError("Select or create at least one new owner."); setBusy(false); return; }

      await executeTransfer(
        wiz.lot.id,
        wiz.transferDate,
        wiz.currentOwners.map((o) => o.ownership_id),
        newOwnerIds,
        wiz.notes
      );
      setStep("done");
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }

  function reset() {
    setWiz(INIT);
    setStep("select-lot");
    setError(null);
  }

  const STEPS: Step[] = ["select-lot", "review", "new-owner", "confirm"];
  const stepIdx = STEPS.indexOf(step);

  return (
    <PageLayout
      title="Lot Transfer Wizard"
      subtitle="Transfer lot ownership when a property sells."
      helpId="lotTransfer"
    >
    <div className="max-w-2xl">
      {error && (
        <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>
      )}

      {step !== "done" && (
        <div className="flex gap-4 mb-6 text-xs">
          {(["Select Lot", "Review", "New Owner", "Confirm"] as const).map((label, i) => (
            <div key={label} className="flex items-center gap-1.5">
              <span className={`w-5 h-5 rounded-full flex items-center justify-center font-bold ${i <= stepIdx ? "bg-blue-600 text-white" : "bg-gray-200 text-gray-500"}`}>
                {i + 1}
              </span>
              <span className={i === stepIdx ? "text-blue-600 font-medium" : "text-gray-400"}>{label}</span>
            </div>
          ))}
        </div>
      )}

      {/* Step 1: Select Lot */}
      {step === "select-lot" && (
        <div className="space-y-3">
          <p className="text-sm text-gray-600">Select the lot being transferred.</p>
          {busy && <p className="text-sm text-gray-400">Loading…</p>}
          <div className="bg-white border rounded-lg divide-y max-h-96 overflow-y-auto">
            {lots.map((lot) => (
              <button
                key={lot.id}
                onClick={() => void selectLot(lot)}
                disabled={busy}
                className="w-full text-left px-4 py-3 hover:bg-blue-50 transition-colors disabled:opacity-50"
              >
                <span className="font-medium text-gray-900">Lot {lot.lot_number}</span>
                {lot.street_address_1 && (
                  <span className="ml-2 text-sm text-gray-500">{lot.street_address_1}</span>
                )}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Step 2: Review current situation */}
      {step === "review" && wiz.lot && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-4 space-y-3">
            <h3 className="font-semibold text-gray-800">
              Lot {wiz.lot.lot_number} — {wiz.lot.street_address_1}
            </h3>

            <div>
              <p className="text-xs font-medium text-gray-500 uppercase mb-1">Current Owners</p>
              {wiz.currentOwners.length === 0 ? (
                <p className="text-sm text-gray-400">No current owner on record.</p>
              ) : (
                <ul className="space-y-1">
                  {wiz.currentOwners.map((o) => (
                    <li key={o.ownership_id} className="text-sm text-gray-700">
                      {o.display_name}
                      {o.email && <span className="text-gray-400 ml-2 text-xs">{o.email}</span>}
                      <span className="text-gray-400 ml-2 text-xs">since {o.start_date}</span>
                    </li>
                  ))}
                </ul>
              )}
            </div>

            {wiz.openAssessments.length > 0 && (
              <div className="bg-amber-50 border border-amber-200 rounded p-3">
                <p className="text-xs font-semibold text-amber-800 mb-1">
                  Open Assessments ({wiz.openAssessments.length})
                </p>
                <p className="text-xs text-amber-700 mb-2">
                  These will remain on the lot after transfer. Contact the prior owners to collect
                  outstanding balances before or at closing.
                </p>
                <ul className="space-y-0.5">
                  {wiz.openAssessments.map((a) => (
                    <li key={a.id} className="text-xs text-amber-800">
                      {a.assessment_date} — {fmt(a.amount)} ({a.status})
                      {a.description && <span className="text-amber-600 ml-1">{a.description}</span>}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <label className="block text-xs font-medium text-gray-700 mb-1">Transfer / Closing Date</label>
              <input
                type="date"
                value={wiz.transferDate}
                onChange={(e) => set("transferDate", e.target.value)}
                className="border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setStep("new-owner")}
              className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
            >
              Continue →
            </button>
            <button onClick={reset} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800">
              Start Over
            </button>
          </div>
        </div>
      )}

      {/* Step 3: New owner info */}
      {step === "new-owner" && (
        <div className="space-y-4">
          <div className="flex gap-3 mb-2">
            <button
              onClick={() => set("newOwnerMode", "create")}
              className={`px-4 py-1.5 text-sm rounded border ${wiz.newOwnerMode === "create" ? "bg-blue-600 text-white border-blue-600" : "border-gray-300 text-gray-600 hover:bg-gray-50"}`}
            >
              Create New Owner
            </button>
            <button
              onClick={() => set("newOwnerMode", "existing")}
              className={`px-4 py-1.5 text-sm rounded border ${wiz.newOwnerMode === "existing" ? "bg-blue-600 text-white border-blue-600" : "border-gray-300 text-gray-600 hover:bg-gray-50"}`}
            >
              Select Existing Owner
            </button>
          </div>

          {wiz.newOwnerMode === "create" && (
            <div className="bg-white border rounded-lg p-4 space-y-3">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">First Name</label>
                  <input type="text" value={wiz.newOwnerFirstName} onChange={(e) => set("newOwnerFirstName", e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Last Name</label>
                  <input type="text" value={wiz.newOwnerLastName} onChange={(e) => set("newOwnerLastName", e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Email</label>
                  <input type="email" value={wiz.newOwnerEmail} onChange={(e) => set("newOwnerEmail", e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Phone</label>
                  <input type="text" value={wiz.newOwnerPhone} onChange={(e) => set("newOwnerPhone", e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div className="col-span-2">
                  <label className="block text-xs font-medium text-gray-700 mb-1">Mailing Address</label>
                  <input type="text" value={wiz.newOwnerAddress} onChange={(e) => set("newOwnerAddress", e.target.value)}
                    placeholder="Street address"
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">City</label>
                  <input type="text" value={wiz.newOwnerCity} onChange={(e) => set("newOwnerCity", e.target.value)}
                    className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">State</label>
                    <input type="text" value={wiz.newOwnerState} onChange={(e) => set("newOwnerState", e.target.value)}
                      maxLength={2}
                      className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </div>
                  <div>
                    <label className="block text-xs font-medium text-gray-700 mb-1">ZIP</label>
                    <input type="text" value={wiz.newOwnerPostal} onChange={(e) => set("newOwnerPostal", e.target.value)}
                      className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500" />
                  </div>
                </div>
              </div>
            </div>
          )}

          {wiz.newOwnerMode === "existing" && (
            <div className="bg-white border rounded-lg p-4">
              <p className="text-xs text-gray-500 mb-2">Select one or more existing owners (hold Ctrl/Cmd for multiple).</p>
              <select
                multiple
                size={8}
                value={wiz.selectedExistingOwnerIds.map(String)}
                onChange={(e) => {
                  const selected = Array.from(e.target.selectedOptions).map((o) => Number(o.value));
                  set("selectedExistingOwnerIds", selected);
                }}
                className="w-full border border-gray-300 rounded text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {allOwners.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.display_name}{o.email ? ` <${o.email}>` : ""}
                  </option>
                ))}
              </select>
            </div>
          )}

          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Notes (optional)</label>
            <input
              type="text"
              value={wiz.notes}
              onChange={(e) => set("notes", e.target.value)}
              placeholder="e.g. Sold via Redfin, closing 2026-06-15"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => setStep("confirm")}
              className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700"
            >
              Review & Confirm →
            </button>
            <button onClick={() => setStep("review")} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800">
              ← Back
            </button>
          </div>
        </div>
      )}

      {/* Step 4: Confirm */}
      {step === "confirm" && wiz.lot && (
        <div className="space-y-4">
          <div className="bg-white border rounded-lg p-5 space-y-3">
            <h3 className="font-semibold text-gray-800">Confirm Transfer</h3>

            <div className="grid grid-cols-2 gap-4 text-sm">
              <div>
                <p className="text-xs text-gray-500">Lot</p>
                <p className="font-medium">{wiz.lot.lot_number} — {wiz.lot.street_address_1}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Transfer Date</p>
                <p className="font-medium">{wiz.transferDate}</p>
              </div>
              <div>
                <p className="text-xs text-gray-500">Previous Owners</p>
                {wiz.currentOwners.map((o) => (
                  <p key={o.ownership_id} className="text-gray-700">{o.display_name}</p>
                ))}
              </div>
              <div>
                <p className="text-xs text-gray-500">New Owner</p>
                {wiz.newOwnerMode === "create" ? (
                  <p className="text-gray-700">
                    {`${wiz.newOwnerFirstName} ${wiz.newOwnerLastName}`.trim() || "New Owner"}
                    {wiz.newOwnerEmail && <span className="text-gray-400 ml-1 text-xs">&lt;{wiz.newOwnerEmail}&gt;</span>}
                  </p>
                ) : (
                  wiz.selectedExistingOwnerIds.map((id) => {
                    const o = allOwners.find((x) => x.id === id);
                    return <p key={id} className="text-gray-700">{o?.display_name ?? id}</p>;
                  })
                )}
              </div>
            </div>

            {wiz.notes && (
              <div>
                <p className="text-xs text-gray-500">Notes</p>
                <p className="text-sm text-gray-700">{wiz.notes}</p>
              </div>
            )}
          </div>

          <div className="bg-amber-50 border border-amber-200 rounded p-3 text-xs text-amber-800">
            This will close all current ownership records as of {wiz.transferDate} and create a new ownership record.
            Any open assessments remain on the lot — collect outstanding balances from the prior owners separately.
          </div>

          <div className="flex gap-3">
            <button
              onClick={() => void handleTransfer()}
              disabled={busy}
              className="px-5 py-2 bg-green-600 text-white text-sm rounded hover:bg-green-700 disabled:opacity-50"
            >
              {busy ? "Processing…" : "Complete Transfer"}
            </button>
            <button onClick={() => setStep("new-owner")} className="px-4 py-2 text-sm text-gray-500 hover:text-gray-800">
              ← Back
            </button>
          </div>
        </div>
      )}

      {/* Done */}
      {step === "done" && (
        <div className="text-center py-10">
          <div className="text-5xl mb-4">✓</div>
          <h2 className="text-xl font-semibold text-green-700 mb-2">Transfer Complete</h2>
          <p className="text-sm text-gray-500 mb-1">
            Lot {wiz.lot?.lot_number} has been transferred as of {wiz.transferDate}.
          </p>
          <p className="text-sm text-gray-400 mb-6">
            The new owner will appear in Lots and Owners. Any open assessments remain on the lot.
          </p>
          <button onClick={reset} className="px-5 py-2 bg-blue-600 text-white text-sm rounded hover:bg-blue-700">
            Transfer Another Lot
          </button>
        </div>
      )}
    </div>
    </PageLayout>
  );
}
