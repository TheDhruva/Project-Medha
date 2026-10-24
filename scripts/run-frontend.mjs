// Run Next.js directly so the development process owns the actual Next child.
//
// On Windows, terminating `npm run dev` does not reliably terminate the
// nested next process. Orphaned Next processes then keep port 3000 and stale
// `.next` state alive, which makes later starts intermittently return 500.
// Keeping the child here lets us terminate it as part of the same process.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const FRONTEND_DIR = join(ROOT, "frontend");
const NEXT_BIN = join(
  FRONTEND_DIR,
  "node_modules",
  "next",
  "dist",
  "bin",
  "next",
);

if (!existsSync(NEXT_BIN)) {
  console.error(
    "[frontend] Next.js is not installed. Run `npm install` and retry.",
  );
  process.exit(1);
}

const child = spawn(process.execPath, [NEXT_BIN, "dev"], {
  cwd: FRONTEND_DIR,
  stdio: "inherit",
  env: process.env,
});

let shuttingDown = false;

function terminateChild() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (child.exitCode === null && !child.killed) child.kill();
}

for (const signal of ["SIGINT", "SIGTERM"]) {
  process.on(signal, () => {
    terminateChild();
    setTimeout(() => process.exit(0), 300);
  });
}

child.on("error", (error) => {
  console.error(`[frontend] failed to start Next.js: ${error.message}`);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (shuttingDown) return;
  process.exit(typeof code === "number" ? code : signal ? 1 : 0);
});
