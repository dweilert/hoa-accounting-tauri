import { useState } from "react";
import { verifyPassword, saveSession } from "../lib/auth";
import { getUserByEmail, recordLogin, createUser } from "../repositories/userRepo";
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

export function LoginScreen({ onNoUsers }: { onNoUsers: () => void }) {
  const { login } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

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
        <p className="text-sm text-gray-500 mb-6">Sign in to continue.</p>

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
      </div>
    </div>
  );
}

// ── Auth gate (decides which screen to show) ──────────────────────────────────

export function AuthGate({ children }: { children: React.ReactNode }) {
  const { state } = useAuth();
  const [showSetup, setShowSetup] = useState(false);

  if (state.status === "loading") {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <p className="text-sm text-gray-400">Loading…</p>
      </div>
    );
  }

  if (state.status === "authenticated") return <>{children}</>;

  if (showSetup) {
    return (
      <FirstRunSetup
        onCreated={() => setShowSetup(false)}
      />
    );
  }

  return (
    <LoginScreen onNoUsers={() => setShowSetup(true)} />
  );
}
