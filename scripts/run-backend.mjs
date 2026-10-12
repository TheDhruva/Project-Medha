// Local dev supervisor for the MEDHA FastAPI backend.
//
// `npm run dev` runs this from the repository root. It:
//   1. loads the repository-root .env (the canonical local configuration),
//   2. resolves the backend virtualenv python (backend/.venv) so no manual
//      activation is needed,
//   3. refuses to start if the port is already taken (no duplicate servers),
//   4. runs uvicorn and restarts it when a file under backend/app changes,
//   5. mirrors a startup failure to the caller so `concurrently -k` stops the
//      frontend too, and shuts the server down on Ctrl+C.
//
// Why not `uvicorn --reload`? On Windows uvicorn's reloader restarts its worker
// by sending CTRL_C_EVENT and blocking in join()
// (uvicorn/supervisors/basereload.py). That only works when the worker has an
// attached console; under any piped/redirected stdio — which is exactly how
// `concurrently` captures logs — the event is never delivered and the reloader
// hangs after printing "Reloading...". This supervisor owns the child process
// directly, so restart and termination are reliable regardless of stdio.
//
// Reload scope is intentionally narrow: only `backend/app/**/*.py` is polled,
// so the virtualenv (.venv), data/, caches, and build output are never watched.
// A full restart (`Ctrl+C`, then `npm run dev`) is still required after .env
// changes or new pip installs.
//
// Port defaults (127.0.0.1:8000) match frontend/next.config.js rewrites and
// .env.example. Overridable via MEDHA_HOST / MEDHA_PORT for testing only —
// overriding the port breaks the Next.js dev proxy, which is baked to 8000.
import { spawn } from "node:child_process";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { createConnection } from "node:net";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const ROOT = dirname(here);
const BACKEND_DIR = join(ROOT, "backend");
const WATCH_DIR = join(BACKEND_DIR, "app");
const POLL_INTERVAL_MS = 900;
const STARTED_GRACE_MS = 2500;
const IGNORED_DIRS = new Set([
  "__pycache__",
  ".mypy_cache",
  ".ruff_cache",
  ".pytest_cache",
  ".venv",
  "node_modules",
]);

// Minimal .env parser (KEY=VALUE, optional quotes, `#` comments). Dependency
// free on purpose: the dev runner must not add packages just to start.
function parseDotenv(text) {
  const out = {};
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const eq = line.indexOf("=");
    if (eq === -1) continue;
    const key = line.slice(0, eq).trim().replace(/^export\s+/, "");
    if (!key) continue;
    let value = line.slice(eq + 1).trim();
    if (
      (value.startsWith('"') && value.endsWith('"')) ||
      (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    out[key] = value;
  }
  return out;
}

// The repository-root `.env` is the canonical local configuration (see
// .env.example and the README). FastAPI's Settings resolves `.env` relative
// to the backend directory, so without this the root file is silently
// ignored and a stale backend/.env (e.g. an unreachable Postgres URL) wins.
// Values already exported in the shell are never overwritten, so an explicit
// `$env:MEDHA_DATABASE_URL=...` override still takes precedence over the file.
function loadLocalEnv() {
  const envPath = join(ROOT, ".env");
  if (!existsSync(envPath)) return;
  let parsed;
  try {
    parsed = parseDotenv(readFileSync(envPath, "utf8"));
  } catch (err) {
    console.warn(`[backend] Could not read ${envPath}: ${err.message}`);
    return;
  }
  for (const [key, value] of Object.entries(parsed)) {
    if (process.env[key] === undefined) process.env[key] = value;
  }
}

loadLocalEnv();

const HOST = process.env.MEDHA_HOST || "127.0.0.1";
const PORT = Number(process.env.MEDHA_PORT || "8000");

function candidatePythons() {
  const cands =
    process.platform === "win32"
      ? [join(BACKEND_DIR, ".venv", "Scripts", "python.exe")]
      : [join(BACKEND_DIR, ".venv", "bin", "python")];
  // Fall back to whatever python is on PATH (works when the venv is
  // activated, or when deps were installed into the system python).
  cands.push(process.platform === "win32" ? "python" : "python3");
  return cands;
}

function resolvePython() {
  for (const cand of candidatePythons()) {
    // Absolute venv paths must exist; bare "python"/"python3" rely on PATH.
    if (cand === "python" || cand === "python3") return cand;
    if (existsSync(cand)) return cand;
  }
  return candidatePythons().at(-1);
}

function portInUse(host, port) {
  return new Promise((resolve) => {
    const socket = createConnection({ host, port });
    socket.once("connect", () => {
      socket.end();
      resolve(true);
    });
    socket.once("error", () => resolve(false));
  });
}

// Snapshot mtimes of *.py files under WATCH_DIR (ignoring caches/venv).
function snapshot() {
  const mtimes = new Map();
  const stack = [WATCH_DIR];
  while (stack.length) {
    const dir = stack.pop();
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const entry of entries) {
      const full = join(dir, entry.name);
      if (entry.isDirectory()) {
        if (!IGNORED_DIRS.has(entry.name)) stack.push(full);
      } else if (entry.name.endsWith(".py")) {
        try {
          mtimes.set(full, statSync(full).mtimeMs);
        } catch {
          /* file vanished mid-scan */
        }
      }
    }
  }
  return mtimes;
}

function changedFiles(before, after) {
  const changed = [];
  for (const [file, mtime] of after) {
    if (before.get(file) !== mtime) changed.push(file);
  }
  for (const file of before.keys()) {
    if (!after.has(file)) changed.push(file);
  }
  return changed;
}

const python = resolvePython();

const envLocation = existsSync(join(ROOT, ".env"))
  ? "root .env"
  : "(root .env absent — shell env only)";
const dbUrl = (process.env.MEDHA_DATABASE_URL || "").trim();
const dbScheme = dbUrl.includes("://") ? dbUrl.split("://", 1)[0].toLowerCase() : "";
const dbMode = ["postgres", "postgresql"].includes(dbScheme)
  ? "postgres (MEDHA_DATABASE_URL set)"
  : "sqlite (local default)";

const uvicornArgs = [
  "-m",
  "uvicorn",
  "app.main:app",
  "--host",
  HOST,
  "--port",
  String(PORT),
];

let child = null;
let shuttingDown = false;
let reloadPending = false;
let hasStartedOnce = false;

function spawnServer() {
  const proc = spawn(python, uvicornArgs, {
    cwd: BACKEND_DIR,
    stdio: "inherit",
    env: process.env,
  });
  child = proc;

  const startedTimer = setTimeout(() => {
    if (child === proc) hasStartedOnce = true;
  }, STARTED_GRACE_MS);

  proc.on("exit", (code, signal) => {
    clearTimeout(startedTimer);
    if (child === proc) child = null;
    if (shuttingDown) return;

    if (reloadPending) {
      reloadPending = false;
      spawnServer();
      return;
    }
    if (!hasStartedOnce) {
      // Failed before it ever served (bad import, port race, missing deps):
      // surface it so concurrently -k stops the frontend as well.
      console.error(
        `[backend] failed to start (exit ${code ?? signal ?? "unknown"}); stopping.`,
      );
      process.exit(typeof code === "number" ? code || 1 : 1);
    }
    console.warn(
      `[backend] process exited (code ${code ?? signal ?? "unknown"}); ` +
        `watching for changes — fix the error and save a file.`,
    );
  });
}

function requestReload(reason) {
  if (shuttingDown) return;
  console.log(`[backend] change detected (${reason}); reloading...`);
  if (child) {
    reloadPending = true;
    child.kill();
  } else {
    spawnServer();
  }
}

function shutdown(signal) {
  if (shuttingDown) return;
  shuttingDown = true;
  if (child) child.kill();
  setTimeout(() => process.exit(0), 300);
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => shutdown(signal));
}

if (await portInUse(HOST, PORT)) {
  console.error(
    `[backend] Port ${PORT} on ${HOST} is already in use — ` +
      `is another backend running? Stop it (or free the port) and retry. ` +
      `Not starting a duplicate process.`,
  );
  process.exit(1);
}

console.log(`[backend] config=${envLocation} db=${dbMode}`);
console.log(
  `[backend] ${python} ${uvicornArgs.join(" ")} ` +
    `(cwd=backend, watching app/**/*.py)`,
);

spawnServer();

let lastSnapshot = snapshot();
setInterval(() => {
  const current = snapshot();
  const changed = changedFiles(lastSnapshot, current);
  lastSnapshot = current;
  if (changed.length > 0 && !shuttingDown) {
    requestReload(changed.map((f) => relative(BACKEND_DIR, f)).join(", "));
  }
}, POLL_INTERVAL_MS);
