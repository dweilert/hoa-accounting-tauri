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

// Common database locations — pick the one that matches your app
const TAURI_DB  = join(homedir(), "Library/Application Support/io.github.dweilert.hoa-accounting/hoa.db");
const PYTHON_DB = join(homedir(), "Library/Application Support/HOAAccounting/hoa_accounting.db");

// Default to whichever exists; prefer the Tauri app
import { existsSync } from "node:fs";
const DEFAULT_DB = existsSync(TAURI_DB) ? TAURI_DB : existsSync(PYTHON_DB) ? PYTHON_DB : TAURI_DB;

let [, , dbPathArg, emailArg, passwordArg] = process.argv;

console.log("\n── HOA Accounting: Emergency Password Reset ──\n");

const rawPath = dbPathArg ?? await prompt(`Database path [${DEFAULT_DB}]: `);
const dbPath = rawPath?.trim() || DEFAULT_DB;

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

// Detect which users table this database has
const tableCheck = db.exec(
  "SELECT name FROM sqlite_master WHERE type='table' AND name IN ('local_users','users')"
);
const tableNames = tableCheck[0]?.values?.map((r) => r[0]) ?? [];
const usersTable = tableNames.includes("local_users")
  ? "local_users"
  : tableNames.includes("users")
  ? "users"
  : null;

if (!usersTable) {
  console.error("No users table found in this database (looked for 'local_users' and 'users').");
  process.exit(1);
}

console.log(`Using table: ${usersTable}\n`);

// List users
const stmt = db.prepare(
  `SELECT id, email, role, is_active FROM ${usersTable} ORDER BY role DESC, email`
);
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

db.run(`UPDATE ${usersTable} SET password_hash = ?, is_active = 1 WHERE id = ?`, [hash, user.id]);

// Write back
const updated = db.export();
writeFileSync(dbPath, Buffer.from(updated));
db.close();

console.log(`\n✓ Password reset for ${email}`);
console.log("You can now sign in with the new password.\n");

rl.close();
