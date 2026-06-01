// Copies sql.js WASM files into public/ so the browser preview can load them.
// Runs automatically after every `npm install` via the postinstall script.
const { cpSync, existsSync, mkdirSync } = require("fs");
const { join } = require("path");

const root = join(__dirname, "..");
const dist = join(root, "node_modules", "sql.js", "dist");

if (!existsSync(join(root, "public"))) mkdirSync(join(root, "public"));

// Vite uses the browser-specific build (sql-wasm-browser.js) which loads
// sql-wasm-browser.wasm. Copy both so either variant works.
for (const name of ["sql-wasm.wasm", "sql-wasm-browser.wasm"]) {
  cpSync(join(dist, name), join(root, "public", name));
  console.log(`${name} → public/`);
}
