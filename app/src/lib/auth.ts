// PBKDF2-based password hashing via WebCrypto (available in Tauri WebView + browser)

const ITERATIONS = 100_000;
const HASH = "SHA-256";

function toHex(buf: ArrayBuffer): string {
  return Array.from(new Uint8Array(buf))
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

function fromHex(hex: string): Uint8Array {
  const arr = hex.match(/.{2}/g) ?? [];
  return new Uint8Array(arr.map((b) => parseInt(b, 16)));
}

export async function hashPassword(password: string): Promise<string> {
  const salt = crypto.getRandomValues(new Uint8Array(16));
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: ITERATIONS, hash: HASH },
    key, 256
  );
  return `pbkdf2:${toHex(salt.buffer)}:${toHex(bits)}`;
}

export async function verifyPassword(password: string, stored: string): Promise<"ok" | "wrong" | "bcrypt"> {
  if (stored.startsWith("$2b$") || stored.startsWith("$2a$")) return "bcrypt";
  if (!stored.startsWith("pbkdf2:")) return "wrong";
  const parts = stored.split(":");
  if (parts.length !== 3) return "wrong";
  const salt = fromHex(parts[1]!);
  const expected = parts[2]!;
  const key = await crypto.subtle.importKey(
    "raw", new TextEncoder().encode(password), "PBKDF2", false, ["deriveBits"]
  );
  const bits = await crypto.subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: ITERATIONS, hash: HASH },
    key, 256
  );
  return toHex(bits) === expected ? "ok" : "wrong";
}

// ── Session ───────────────────────────────────────────────────────────────────

const SESSION_KEY = "hoa_session";
const SESSION_TTL_MS = 8 * 60 * 60 * 1000; // 8 hours

export type SessionUser = {
  id: number;
  email: string;
  displayName: string;
  role: "admin" | "reports";
};

export function saveSession(user: SessionUser): void {
  localStorage.setItem(SESSION_KEY, JSON.stringify({
    ...user,
    expiresAt: Date.now() + SESSION_TTL_MS,
  }));
}

export function loadSession(): SessionUser | null {
  try {
    const raw = localStorage.getItem(SESSION_KEY);
    if (!raw) return null;
    const data = JSON.parse(raw) as SessionUser & { expiresAt: number };
    if (data.expiresAt < Date.now()) { clearSession(); return null; }
    return { id: data.id, email: data.email, displayName: data.displayName, role: data.role };
  } catch {
    return null;
  }
}

export function clearSession(): void {
  localStorage.removeItem(SESSION_KEY);
}
