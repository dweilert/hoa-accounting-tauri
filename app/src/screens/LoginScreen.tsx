import { useState, useEffect } from "react";
import { verifyPassword, saveSession, hashPassword } from "../lib/auth";
import { getUserByEmail, recordLogin, createUser } from "../repositories/userRepo";
import { getDb, getConfiguredDbPath } from "../lib/db";
import { useAuth } from "../contexts/AuthContext";

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

// ── Login form ────────────────────────────────────────────────────────────────

export function LoginScreen({ onNoUsers, onForgotPassword }: { onNoUsers: () => void; onForgotPassword: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dbInfo, setDbInfo] = useState<{ path: string; users: number | string } | null>(null);

  useEffect(() => {
    const path = getConfiguredDbPath();
    getDb()
      .then((db) => db.select<[{ n: number }]>("SELECT COUNT(*) as n FROM local_users"))
      .then(([row]) => setDbInfo({ path, users: row?.n ?? 0 }))
      .catch((e: unknown) => setDbInfo({ path, users: `ERROR: ${String(e)}` }));
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

  if (state.status === "loading") {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  if (state.status === "authenticated") return <>{children}</>;

  if (showSetup) {
    return <FirstRunSetup onCreated={() => setShowSetup(false)} />;
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
