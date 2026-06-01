import { useState } from "react";
import { PageLayout } from "../components/PageLayout";
import { useAuth, useCurrentUser } from "../contexts/AuthContext";
import { updateUser, setPassword, getUserByEmail } from "../repositories/userRepo";
import { verifyPassword, saveSession } from "../lib/auth";

export function ProfileScreen() {
  const { login } = useAuth();
  const currentUser = useCurrentUser();

  const [displayName, setDisplayName] = useState(currentUser?.displayName ?? "");
  const [savingName, setSavingName] = useState(false);
  const [nameMsg, setNameMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const [currentPw, setCurrentPw] = useState("");
  const [newPw, setNewPw] = useState("");
  const [confirmPw, setConfirmPw] = useState("");
  const [savingPw, setSavingPw] = useState(false);
  const [pwMsg, setPwMsg] = useState<{ ok: boolean; text: string } | null>(null);

  if (!currentUser) return null;

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    if (!displayName.trim()) { setNameMsg({ ok: false, text: "Name cannot be blank." }); return; }
    setSavingName(true);
    setNameMsg(null);
    try {
      await updateUser(currentUser!.id, displayName.trim(), currentUser!.role, true);
      const updated = { ...currentUser!, displayName: displayName.trim() };
      saveSession(updated);
      login(updated);
      setNameMsg({ ok: true, text: "Name updated." });
    } catch (e) {
      setNameMsg({ ok: false, text: String(e) });
    } finally {
      setSavingName(false);
    }
  }

  async function handleChangePassword(e: React.FormEvent) {
    e.preventDefault();
    if (!currentPw) { setPwMsg({ ok: false, text: "Enter your current password." }); return; }
    if (!newPw) { setPwMsg({ ok: false, text: "Enter a new password." }); return; }
    if (newPw.length < 8) { setPwMsg({ ok: false, text: "Password must be at least 8 characters." }); return; }
    if (newPw !== confirmPw) { setPwMsg({ ok: false, text: "Passwords do not match." }); return; }
    setSavingPw(true);
    setPwMsg(null);
    try {
      const user = await getUserByEmail(currentUser!.email);
      if (!user) throw new Error("User not found.");
      const result = await verifyPassword(currentPw, user.password_hash);
      if (result === "bcrypt") {
        setPwMsg({ ok: false, text: "Your current password uses a legacy format. An admin must set a new password for you in Admin → Users." });
        return;
      }
      if (result !== "ok") { setPwMsg({ ok: false, text: "Current password is incorrect." }); return; }
      await setPassword(currentUser!.id, newPw);
      setCurrentPw(""); setNewPw(""); setConfirmPw("");
      setPwMsg({ ok: true, text: "Password changed." });
    } catch (e) {
      setPwMsg({ ok: false, text: String(e) });
    } finally {
      setSavingPw(false);
    }
  }

  return (
    <PageLayout title="Profile" subtitle="Your account settings." helpId="profile">
    <div className="max-w-lg">
      <p className="text-sm text-gray-500 mb-8">{currentUser.email} · {currentUser.role}</p>

      {/* Display name */}
      <section className="mb-8">
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Display Name</h2>
        <form onSubmit={handleSaveName} className="flex gap-2 items-end">
          <div className="flex-1">
            <input
              value={displayName}
              onChange={(e) => setDisplayName(e.target.value)}
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <button
            type="submit"
            disabled={savingName}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {savingName ? "Saving…" : "Save"}
          </button>
        </form>
        {nameMsg && (
          <p className={`mt-2 text-xs ${nameMsg.ok ? "text-green-600" : "text-red-600"}`}>{nameMsg.text}</p>
        )}
      </section>

      {/* Change password */}
      <section>
        <h2 className="text-sm font-semibold text-gray-700 mb-3">Change Password</h2>
        <form onSubmit={handleChangePassword} className="space-y-3">
          <div>
            <label className="block text-xs text-gray-500 mb-1">Current password</label>
            <input
              type="password"
              value={currentPw}
              onChange={(e) => setCurrentPw(e.target.value)}
              autoComplete="current-password"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          <div>
            <label className="block text-xs text-gray-500 mb-1">New password</label>
            <input
              type="password"
              value={newPw}
              onChange={(e) => setNewPw(e.target.value)}
              autoComplete="new-password"
              className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
            />
          </div>
          {newPw && (
            <div>
              <label className="block text-xs text-gray-500 mb-1">Confirm new password</label>
              <input
                type="password"
                value={confirmPw}
                onChange={(e) => setConfirmPw(e.target.value)}
                autoComplete="new-password"
                className="w-full border border-gray-300 rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-blue-500"
              />
            </div>
          )}
          <button
            type="submit"
            disabled={savingPw}
            className="px-4 py-1.5 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
          >
            {savingPw ? "Saving…" : "Change Password"}
          </button>
          {pwMsg && (
            <p className={`text-xs ${pwMsg.ok ? "text-green-600" : "text-red-600"}`}>{pwMsg.text}</p>
          )}
        </form>
      </section>
    </div>
    </PageLayout>
  );
}
