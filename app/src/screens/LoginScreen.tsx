import { useState, useEffect } from "react";
import { verifyPassword, saveSession, hashPassword } from "../lib/auth";
import { getUserByEmail, recordLogin, createUser } from "../repositories/userRepo";
import { getDb } from "../lib/db";
import { readConfig } from "../lib/config";
import { useAuth } from "../contexts/AuthContext";
import { saveHoaIdentity, markSetupComplete, isSetupComplete } from "../repositories/setupRepo";
import { insertBankAccount } from "../repositories/bankAccountRepo";
import type { BankAccountFormValues } from "../types/bankAccount";

// ── First-run setup (no users exist) ─────────────────────────────────────────

function FirstRunSetup({ onCreated }: { onCreated: () => void }) {
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !name || !password) { setError("All fields are required."); return; }
    if (password !== confirm) { setError("Passwords do not match."); return; }
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    setSaving(true);
    try {
      await createUser(email, name, "admin", password);
      onCreated();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-md p-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">Welcome to HOA Accounting</h1>
        <p className="text-sm text-gray-500 mb-6">No users are set up yet. Create your admin account to get started.</p>

        {error && <p className="mb-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Your Name</label>
            <input
              type="text"
              value={name}
              onChange={(e) => setName(e.target.value)}
              autoFocus
              placeholder="e.g. Jane Smith"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="admin@example.com"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Confirm Password</label>
            <input
              type="password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            disabled={saving}
            className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 mt-2"
          >
            {saving ? "Creating account…" : "Create Admin Account"}
          </button>
        </form>
      </div>
    </div>
  );
}

// ── HOA Setup Wizard (runs after first admin account is created) ──────────────

type SetupStep = "identity" | "bank" | "done";

function SetupWizard({ onComplete }: { onComplete: () => void }) {
  const [step, setStep] = useState<SetupStep>("identity");

  // Step 1 state
  const [hoaName, setHoaName] = useState("");
  const [fiscalMonth, setFiscalMonth] = useState(1);
  const [timezone, setTimezone] = useState("America/Chicago");
  const [step1Error, setStep1Error] = useState<string | null>(null);
  const [step1Saving, setStep1Saving] = useState(false);

  // Step 2 state
  const [bankName, setBankName] = useState("");
  const [institution, setInstitution] = useState("");
  const [last4, setLast4] = useState("");
  const [openingBalance, setOpeningBalance] = useState("0");
  const [openingDate, setOpeningDate] = useState(new Date().toISOString().slice(0, 10));
  const [step2Error, setStep2Error] = useState<string | null>(null);
  const [step2Saving, setStep2Saving] = useState(false);

  async function saveIdentity(e: React.FormEvent) {
    e.preventDefault();
    if (!hoaName.trim()) { setStep1Error("HOA Name is required."); return; }
    setStep1Saving(true);
    setStep1Error(null);
    try {
      await saveHoaIdentity(hoaName.trim(), fiscalMonth, timezone);
      setStep("bank");
    } catch (err) {
      setStep1Error(String(err));
    } finally {
      setStep1Saving(false);
    }
  }

  async function saveBank(e: React.FormEvent) {
    e.preventDefault();
    if (!bankName.trim() || !institution.trim()) { setStep2Error("Account name and institution are required."); return; }
    setStep2Saving(true);
    setStep2Error(null);
    try {
      const vals: BankAccountFormValues = {
        account_name: bankName.trim(),
        institution_name: institution.trim(),
        account_last4: last4.trim() || undefined,
        account_type: "CHECKING",
        fund_code: "OPERATING",
        active_flag: 1,
        opening_balance: Number(openingBalance) || 0,
        opening_balance_date: openingDate || undefined,
      };
      await insertBankAccount(vals);
      await markSetupComplete();
      setStep("done");
    } catch (err) {
      setStep2Error(String(err));
    } finally {
      setStep2Saving(false);
    }
  }

  async function skipBank() {
    await markSetupComplete();
    setStep("done");
  }

  const MONTHS = ["January","February","March","April","May","June","July","August","September","October","November","December"];

  const stepNum = step === "identity" ? 1 : step === "bank" ? 2 : 3;

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-lg p-8">
        {/* Progress indicator */}
        <div className="flex items-center gap-2 mb-6">
          {[1,2,3].map((n) => (
            <div key={n} className="flex items-center gap-2">
              <div className={`w-7 h-7 rounded-full flex items-center justify-center text-xs font-bold ${
                n < stepNum ? "bg-green-500 text-white" :
                n === stepNum ? "bg-blue-600 text-white" :
                "bg-gray-200 text-gray-400"
              }`}>{n < stepNum ? "✓" : n}</div>
              {n < 3 && <div className={`h-0.5 w-8 ${n < stepNum ? "bg-green-400" : "bg-gray-200"}`} />}
            </div>
          ))}
          <span className="ml-2 text-xs text-gray-400">
            {step === "identity" ? "HOA Identity" : step === "bank" ? "Bank Account" : "All set!"}
          </span>
        </div>

        {/* Step 1: HOA Identity */}
        {step === "identity" && (
          <>
            <h1 className="text-xl font-bold text-gray-900 mb-1">Set Up Your HOA</h1>
            <p className="text-sm text-gray-500 mb-5">Basic information about your association.</p>
            {step1Error && <p className="mb-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{step1Error}</p>}
            <form onSubmit={saveIdentity} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">HOA Name <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={hoaName}
                  onChange={(e) => setHoaName(e.target.value)}
                  autoFocus
                  placeholder="e.g. Maple Manor Property Owners Association"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Fiscal Year Starts</label>
                  <select
                    value={fiscalMonth}
                    onChange={(e) => setFiscalMonth(Number(e.target.value))}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    {MONTHS.map((m, i) => <option key={i+1} value={i+1}>{m}</option>)}
                  </select>
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Timezone</label>
                  <select
                    value={timezone}
                    onChange={(e) => setTimezone(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="America/New_York">Eastern</option>
                    <option value="America/Chicago">Central</option>
                    <option value="America/Denver">Mountain</option>
                    <option value="America/Los_Angeles">Pacific</option>
                    <option value="America/Phoenix">Arizona</option>
                    <option value="America/Anchorage">Alaska</option>
                    <option value="Pacific/Honolulu">Hawaii</option>
                  </select>
                </div>
              </div>
              <button
                type="submit"
                disabled={step1Saving}
                className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 mt-2"
              >
                {step1Saving ? "Saving…" : "Next: Bank Account →"}
              </button>
            </form>
          </>
        )}

        {/* Step 2: Bank Account */}
        {step === "bank" && (
          <>
            <h1 className="text-xl font-bold text-gray-900 mb-1">Primary Bank Account</h1>
            <p className="text-sm text-gray-500 mb-5">Add your operating checking account. You can add more later in Bank → Accounts.</p>
            {step2Error && <p className="mb-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{step2Error}</p>}
            <form onSubmit={saveBank} className="space-y-4">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Account Name <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={bankName}
                  onChange={(e) => setBankName(e.target.value)}
                  autoFocus
                  placeholder="e.g. Operating Checking"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Bank / Institution <span className="text-red-500">*</span></label>
                <input
                  type="text"
                  value={institution}
                  onChange={(e) => setInstitution(e.target.value)}
                  placeholder="e.g. First National Bank"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Last 4 digits (optional)</label>
                  <input
                    type="text"
                    maxLength={4}
                    value={last4}
                    onChange={(e) => setLast4(e.target.value.replace(/\D/g, ""))}
                    placeholder="1234"
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div>
                  <label className="block text-xs font-medium text-gray-700 mb-1">Opening Balance</label>
                  <input
                    type="number"
                    step="0.01"
                    value={openingBalance}
                    onChange={(e) => setOpeningBalance(e.target.value)}
                    className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Opening Balance Date</label>
                <input
                  type="date"
                  value={openingDate}
                  onChange={(e) => setOpeningDate(e.target.value)}
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <button
                type="submit"
                disabled={step2Saving}
                className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 mt-2"
              >
                {step2Saving ? "Saving…" : "Save & Continue →"}
              </button>
            </form>
            <button
              onClick={() => void skipBank()}
              className="mt-3 text-xs text-gray-400 hover:text-gray-600 w-full text-center"
            >
              Skip for now — I'll add accounts in Settings
            </button>
          </>
        )}

        {/* Step 3: Done */}
        {step === "done" && (
          <div className="text-center py-4">
            <div className="w-16 h-16 bg-green-100 rounded-full flex items-center justify-center mx-auto mb-4 text-3xl">✓</div>
            <h1 className="text-xl font-bold text-gray-900 mb-2">You're all set!</h1>
            <p className="text-sm text-gray-500 mb-6">Your HOA Accounting system is ready to use.</p>
            <button
              onClick={onComplete}
              className="px-8 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              Go to Dashboard →
            </button>
          </div>
        )}
      </div>
    </div>
  );
}

// ── Login form ────────────────────────────────────────────────────────────────

export function LoginScreen({ onNoUsers, onForgotPassword }: { onNoUsers: () => void; onForgotPassword: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dbInfo, setDbInfo] = useState<{ path: string; users: number | string } | null>(null);

  useEffect(() => {
    Promise.all([getDb(), readConfig()])
      .then(([db, cfg]) =>
        db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM local_users")
          .then(([row]) => setDbInfo({ path: cfg?.db_path ?? "browser (in-memory)", users: row?.n ?? 0 }))
      )
      .catch((e: unknown) => setDbInfo({ path: "unknown", users: `ERROR: ${String(e)}` }));
  }, []);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email || !password) { setError("Email and password are required."); return; }
    setLoading(true);
    setError(null);
    try {
      const user = await getUserByEmail(email);
      if (!user || !user.is_active) {
        setError("Invalid email or password.");
        return;
      }
      const result = await verifyPassword(password, user.password_hash);
      if (result === "bcrypt") {
        setError("This account was created in the web app and uses a password format not supported here. Ask an admin to reset your password in Admin → Users.");
        return;
      }
      if (result !== "ok") {
        setError("Invalid email or password.");
        return;
      }
      await recordLogin(user.id);
      const session = {
        id: user.id,
        email: user.email,
        displayName: user.display_name || user.email,
        role: user.role,
      };
      saveSession(session);
      login(session);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-sm p-8">
        <h1 className="text-2xl font-bold text-gray-900 mb-1">HOA Accounting</h1>
        <p className="text-sm text-gray-500 mb-3">Sign in to continue.</p>
        {dbInfo && (
          <div className="mb-4 p-2 bg-gray-50 border border-gray-200 rounded text-xs font-mono break-all">
            <p className="text-gray-500">DB: {dbInfo.path}</p>
            <p className={typeof dbInfo.users === "string" && dbInfo.users.startsWith("ERROR") ? "text-red-600" : "text-gray-500"}>
              Users: {String(dbInfo.users)}
            </p>
          </div>
        )}

        {error && <p className="mb-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}

        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Email</label>
            <input
              type="email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoFocus
              autoComplete="email"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-gray-700 mb-1">Password</label>
            <input
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50"
          >
            {loading ? "Signing in…" : "Sign In"}
          </button>
        </form>

        <button
          onClick={onNoUsers}
          className="mt-4 text-xs text-gray-400 hover:text-gray-500 w-full text-center"
        >
          First time? Set up admin account →
        </button>
        <button
          onClick={onForgotPassword}
          className="mt-1 text-xs text-gray-300 hover:text-gray-500 w-full text-center"
        >
          Forgot password?
        </button>
      </div>
    </div>
  );
}

// ── Emergency password reset (local-app only — physical access = authorization) ──

function EmergencyReset({ onDone }: { onDone: () => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirm, setConfirm] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!email) { setError("Enter the account email."); return; }
    if (!password) { setError("Enter a new password."); return; }
    if (password.length < 8) { setError("Password must be at least 8 characters."); return; }
    if (password !== confirm) { setError("Passwords do not match."); return; }
    setSaving(true);
    setError(null);
    try {
      const db = await getDb();
      const rows = await db.select<{ id: number }[]>(
        "SELECT id FROM local_users WHERE email = ? COLLATE NOCASE",
        [email.trim()]
      );
      if (rows.length === 0) { setError("No account found with that email."); return; }
      const hash = await hashPassword(password);
      await db.execute("UPDATE local_users SET password_hash = ? WHERE id = ?", [hash, rows[0]!.id]);
      setSuccess(true);
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center p-4">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-sm p-8">
        <h1 className="text-xl font-bold text-gray-900 mb-1">Reset Password</h1>
        <p className="text-xs text-gray-400 mb-5">
          Emergency reset — enter the email of the account and a new password.
          No old password required.
        </p>

        {success ? (
          <div className="text-center">
            <p className="text-sm text-green-700 font-medium mb-4">Password reset. You can now sign in.</p>
            <button
              onClick={onDone}
              className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700"
            >
              Back to Sign In
            </button>
          </div>
        ) : (
          <>
            {error && <p className="mb-4 text-sm text-red-600 bg-red-50 rounded px-3 py-2">{error}</p>}
            <form onSubmit={handleSubmit} className="space-y-3">
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Account Email</label>
                <input
                  type="email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  autoFocus
                  autoComplete="email"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">New Password</label>
                <input
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="new-password"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-gray-700 mb-1">Confirm Password</label>
                <input
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  autoComplete="new-password"
                  className="w-full border border-gray-300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
                />
              </div>
              <button
                type="submit"
                disabled={saving}
                className="w-full py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 disabled:opacity-50 mt-1"
              >
                {saving ? "Resetting…" : "Reset Password"}
              </button>
            </form>
            <button
              onClick={onDone}
              className="mt-4 text-xs text-gray-400 hover:text-gray-500 w-full text-center"
            >
              ← Back to Sign In
            </button>
          </>
        )}
      </div>
    </div>
  );
}

// ── Auth gate (decides which screen to show) ──────────────────────────────────

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();
  const [showSetup, setShowSetup] = useState(false);
  const [showReset, setShowReset] = useState(false);
  const [showWizard, setShowWizard] = useState(false);
  const [setupChecked, setSetupChecked] = useState(false);

  // After login, check if HOA setup wizard has been completed
  useEffect(() => {
    if (state.status === "authenticated" && !setupChecked) {
      isSetupComplete()
        .then((done) => {
          if (!done) setShowWizard(true);
          setSetupChecked(true);
        })
        .catch(() => setSetupChecked(true));
    }
  }, [state.status, setupChecked]);

  if (state.status === "loading" || (state.status === "authenticated" && !setupChecked)) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  if (state.status === "authenticated") {
    if (showWizard) {
      return <SetupWizard onComplete={() => setShowWizard(false)} />;
    }
    return <>{children}</>;
  }

  if (showSetup) {
    return <FirstRunSetup onCreated={() => {
      setShowSetup(false);
      setShowWizard(true);
      setSetupChecked(true);
    }} />;
  }

  if (showReset) {
    return <EmergencyReset onDone={() => setShowReset(false)} />;
  }

  return (
    <LoginScreen
      onNoUsers={() => setShowSetup(true)}
      onForgotPassword={() => setShowReset(true)}
    />
  );
}
