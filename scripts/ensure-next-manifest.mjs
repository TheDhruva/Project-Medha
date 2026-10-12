// One-time frontend bootstrap for `npm run dev` (repository root).
//
// Next.js 15 `next dev` reads `frontend/.next/routes-manifest.json` from
// disk when rendering pages but does not generate it on a fresh clone —
// without it `/` returns 500 ENOENT while `/health` rewrites still work.
// `next build` generates the file, so this script runs exactly one build
// when the manifest is missing, and is a no-op on every later start
// (no reinstalls, no rebuilds). A failed build exits non-zero so
// `concurrently --kill-others-on-fail` stops the backend too instead of
// serving a broken homepage.
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = dirname(dirname(fileURLToPath(import.meta.url)));
const MANIFEST = join(ROOT, "frontend", ".next", "routes-manifest.json");

if (existsSync(MANIFEST)) process.exit(0);

console.log(
  "[frontend] routes-manifest.json missing — running one-time `next build`...",
);
const res = spawnSync("npm", ["--prefix", "frontend", "run", "build"], {
  cwd: ROOT,
  stdio: "inherit",
  shell: process.platform === "win32",
});
if (res.status !== 0 || !existsSync(MANIFEST)) {
  console.error(
    "[frontend] one-time build failed; fix the error above and retry `npm run dev`.",
  );
  process.exit(typeof res.status === "number" && res.status !== 0 ? res.status : 1);
}
console.log("[frontend] one-time build done.");
