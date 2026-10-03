import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { hashPassword, verifyPassword, saveSession, loadSession, clearSession, getRawSession } from "../auth";
import type { SessionUser } from "../auth";

// Provide a minimal localStorage shim for Node environment
const store: Record<string, string> = {};
const localStorageMock = {
  getItem: (k: string) => store[k] ?? null,
  setItem: (k: string, v: string) => { store[k] = v; },
  removeItem: (k: string) => { delete store[k]; },
  clear: () => { Object.keys(store).forEach((k) => delete store[k]); },
};
Object.defineProperty(globalThis, "localStorage", { value: localStorageMock, writable: true });

// ── hashPassword / verifyPassword ─────────────────────────────────────────────

describe("hashPassword", () => {
  it("returns a non-empty string", async () => {
    const hash = await hashPassword("secret");
    expect(typeof hash).toBe("string");
    expect(hash.length).toBeGreaterThan(0);
  });

  it("two calls produce different hashes (salted)", async () => {
    const h1 = await hashPassword("same");
    const h2 = await hashPassword("same");
    expect(h1).not.toBe(h2);
  });

  it("does not return plaintext password", async () => {
    const hash = await hashPassword("mypassword");
    expect(hash).not.toContain("mypassword");
  });

  it("hash starts with pbkdf2: prefix", async () => {
    const hash = await hashPassword("abc");
    expect(hash.startsWith("pbkdf2:")).toBe(true);
  });
});

describe("verifyPassword", () => {
  it("returns 'ok' for correct password", async () => {
    const hash = await hashPassword("correct");
    expect(await verifyPassword("correct", hash)).toBe("ok");
  });

  it("returns 'wrong' for incorrect password", async () => {
    const hash = await hashPassword("correct");
    expect(await verifyPassword("wrong", hash)).toBe("wrong");
  });

  it("returns 'wrong' for empty password against a real hash", async () => {
    const hash = await hashPassword("nonempty");
    expect(await verifyPassword("", hash)).toBe("wrong");
  });

  it("round-trips various passwords", async () => {
    const passwords = ["short", "A1b2C3d4!", "spaces in pass"];
    for (const pw of passwords) {
      const hash = await hashPassword(pw);
      expect(await verifyPassword(pw, hash)).toBe("ok");
    }
  });

  it("returns 'wrong' for malformed stored hash", async () => {
    expect(await verifyPassword("anything", "not-a-valid-hash")).toBe("wrong");
  });

  it("returns 'bcrypt' for bcrypt hash prefix", async () => {
    expect(await verifyPassword("anything", "$2b$10$fakebcrypthash")).toBe("bcrypt");
    expect(await verifyPassword("anything", "$2a$10$fakebcrypthash")).toBe("bcrypt");
  });
});

// ── Session management (requires DOM localStorage) ────────────────────────────

describe("session management", () => {
  const user: SessionUser = {
    id: 42,
    email: "bob@example.com",
    displayName: "Bob",
    role: "admin",
  };

  beforeEach(() => {
    clearSession();
  });

  afterEach(() => {
    clearSession();
    vi.restoreAllMocks();
  });

  it("loadSession returns null when nothing saved", () => {
    expect(loadSession()).toBeNull();
  });

  it("saveSession + loadSession round-trips user data", () => {
    saveSession(user);
    const loaded = loadSession();
    expect(loaded?.id).toBe(42);
    expect(loaded?.email).toBe("bob@example.com");
    expect(loaded?.displayName).toBe("Bob");
    expect(loaded?.role).toBe("admin");
  });

  it("clearSession removes saved session", () => {
    saveSession(user);
    clearSession();
    expect(loadSession()).toBeNull();
  });

  it("getRawSession returns expiry after save", () => {
    saveSession(user);
    const raw = getRawSession();
    expect(raw).not.toBeNull();
    expect(typeof raw?.expiresAt).toBe("number");
    expect(raw!.expiresAt).toBeGreaterThan(Date.now());
  });

  it("getRawSession returns null after clear", () => {
    saveSession(user);
    clearSession();
    expect(getRawSession()).toBeNull();
  });

  it("expired session returns null from loadSession", () => {
    saveSession(user);
    vi.spyOn(Date, "now").mockReturnValue(Date.now() + 1000 * 60 * 60 * 25);
    expect(loadSession()).toBeNull();
  });

  it("reports role correctly for reports user", () => {
    const reportsUser: SessionUser = { ...user, role: "reports" };
    saveSession(reportsUser);
    expect(loadSession()?.role).toBe("reports");
  });
});
