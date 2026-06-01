#!/usr/bin/env node
/**
 * Smart dev launcher — finds the first free port starting at 1420 and
 * passes it to both Vite and Tauri so the webview connects to the right URL.
 *
 * Usage: node scripts/dev.js              (tries 1420, 1421, 1422 …)
 *        node scripts/dev.js --port 1430  (starts search at 1430)
 */
import net from "net";
import { spawn } from "child_process";

// Check both IPv4 (127.0.0.1) and IPv6 (::1) — on macOS, Vite listens on
// ::1 by default, so an IPv4-only check gives a false "port is free" result.
function tryConnect(port, host) {
  return new Promise((resolve) => {
    const client = new net.Socket();
    const done = (result) => { client.destroy(); resolve(result); };
    client.setTimeout(300);
    client.once("connect", () => done(true));
    client.once("timeout", () => done(false));
    client.once("error", () => done(false));
    client.connect(port, host);
  });
}

async function isPortInUse(port) {
  const [v4, v6] = await Promise.all([
    tryConnect(port, "127.0.0.1"),
    tryConnect(port, "::1"),
  ]);
  return v4 || v6;
}

async function findFreePort(start = 1420) {
  for (let port = start; port < start + 20; port++) {
    if (!(await isPortInUse(port))) return port;
  }
  throw new Error(`No free port found in range ${start}–${start + 19}`);
}

const args = process.argv.slice(2);
const portArgIdx = args.indexOf("--port");
const startPort = portArgIdx !== -1 ? parseInt(args[portArgIdx + 1] ?? "1420") : 1420;

const port = await findFreePort(startPort);

if (port !== startPort) {
  console.log(`⚠  Port ${startPort} is in use — using port ${port} instead`);
} else {
  console.log(`Starting HOA Accounting on port ${port}`);
}

// Override devUrl and beforeDevCommand so Tauri's webview connects to the
// right port. --strictPort tells Vite to error out rather than silently
// picking yet another port on its own.
const config = JSON.stringify({
  build: {
    devUrl: `http://localhost:${port}`,
    beforeDevCommand: `npm run dev -- --port ${port} --strictPort`,
  },
});

const proc = spawn("npx", ["tauri", "dev", "--config", config], {
  stdio: "inherit",
  shell: process.platform === "win32",
});

proc.on("exit", (code) => process.exit(code ?? 0));
