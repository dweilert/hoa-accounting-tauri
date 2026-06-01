#!/usr/bin/env node
/**
 * Emergency admin password reset — run from terminal when you can't log in.
 *
 * Usage:
 *   node scripts/reset-password.mjs [db-path] [email] [new-password]
 *
 * If arguments are omitted you will be prompted interactively.
 *
 * The default database location on macOS is:
 *   ~/Library/Application Support/io.github.dweilert.hoa-accounting/hoa.db
 *
 * Examples:
 *   node scripts/reset-password.mjs
 *   node scripts/reset-password.mjs ~/Library/Application\ Support/io.github.dweilert.hoa-accounting/hoa.db admin@example.com newpass123
 */

import { createInterface } from "node:readline/promises";
import { readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

// ── PBKDF2 via Node.js built-in crypto (same algorithm as the app) ────────────

const ITERATIONS = 100_000;

function toHex(buf) {
  return Buffer.from(buf).toString("hex");
}

async function hashPassword(password) {
  const { subtle } = globalThis.crypto;
  const salt = globalThis.crypto.getRandomValues(new Uint8Array(16));
  const key = await subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveBits"]
  );
  const bits = await subtle.deriveBits(
    { name: "PBKDF2", salt, iterations: ITERATIONS, hash: "SHA-256" },
    key,
    256
  );
  return `pbkdf2:${toHex(salt)}:${toHex(bits)}`;
}

// ── Prompt helper ─────────────────────────────────────────────────────────────

const rl = createInterface({ input: process.stdin, output: process.stdout });

async function prompt(question) {
  return rl.question(question);
}

// ── Main ──────────────────────────────────────────────────────────────────────

const DEFAULT_DB = join(
  homedir(),
  "Library/Application Support/io.github.dweilert.hoa-accounting/hoa.db"
);

let [, , dbPathArg, emailArg, passwordArg] = process.argv;

console.log("\n── HOA Accounting: Emergency Password Reset ──\n");

const dbPath = dbPathArg ?? await prompt(`Database path [${DEFAULT_DB}]: `) || DEFAULT_DB;

// Load sql.js and open the database
let SQL;
try {
  SQL = require("sql.js");
} catch {
  console.error("sql.js not found. Run `npm install` in the app directory first.");
  process.exit(1);
}

const initSqlJs = SQL.default ?? SQL;
const sqlJs = await initSqlJs();

let dbData;
try {
  dbData = readFileSync(dbPath);
} catch {
  console.error(`Cannot read database at: ${dbPath}`);
  console.error("Check the path and try again.");
  process.exit(1);
}

const db = new sqlJs.Database(dbData);

// List users
const stmt = db.prepare("SELECT id, email, role, is_active FROM local_users ORDER BY role DESC, email");
const users = [];
while (stmt.step()) users.push(stmt.getAsObject());
stmt.free();

if (users.length === 0) {
  console.error("No users found in this database.");
  process.exit(1);
}

console.log("Users in database:");
users.forEach((u) => {
  console.log(`  ${u.email}  [${u.role}]${u.is_active ? "" : "  (inactive)"}`);
});
console.log();

const email = emailArg ?? await prompt("Email to reset: ");
const user = users.find((u) => u.email.toLowerCase() === email.trim().toLowerCase());
if (!user) {
  console.error(`No user found with email: ${email}`);
  process.exit(1);
}

const password = passwordArg ?? await prompt("New password (min 8 chars): ");
if (password.length < 8) {
  console.error("Password must be at least 8 characters.");
  process.exit(1);
}

console.log("\nHashing password…");
const hash = await hashPassword(password);

db.run("UPDATE local_users SET password_hash = ?, is_active = 1 WHERE id = ?", [hash, user.id]);

// Write back
const updated = db.export();
writeFileSync(dbPath, Buffer.from(updated));
db.close();

console.log(`\n✓ Password reset for ${email}`);
console.log("You can now sign in with the new password.\n");

rl.close();
