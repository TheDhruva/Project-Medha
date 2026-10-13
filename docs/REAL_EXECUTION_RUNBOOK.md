# Real Execution Runbook (isolated Docker runtime)

This is the operator guide for MEDHA's real application deployment path.
The demo engine is disabled by default (isolated tests only) and there is
no simulated fallback: unconfigured execution fails closed with
`EXECUTION_NOT_CONFIGURED`, never a substituted success.

## 1. What "real" means here

A `real` deployment builds the approved commit with a **MEDHA-authored**
Dockerfile (repository Dockerfiles are never built) and runs it in an
isolated Docker container behind a blocking HTTP readiness gate. Supported
profiles only — anything else fails closed with `UNSUPPORTED_STACK`:

| Profile | Detected from | Base image | Serves |
|---|---|---|---|
| `static` | `index.html` | `nginx:1.27-alpine` | static site |
| `python` | `requirements.txt`/`pyproject.toml` + app entrypoint | `python:3.12-slim` | FastAPI via `uvicorn`, else `gunicorn` |
| `node` | `package.json` | `node:22-alpine` | `npm start` / `node server.js` |

Readiness: loopback HTTP probe of the profile health endpoint (`/`) until
2xx–4xx or `MEDHA_REAL_READINESS_TIMEOUT_SECONDS` (default 90s).

## 2. Prerequisites

- A Docker daemon reachable from the backend host (`docker version` works).
- A **non-production** host (`MEDHA_ENV` anything but `production`; the
  hosted control plane refuses execution with `EXECUTION_DISABLED_HOSTED`).
- The daemon must allow image builds and container runs with the flags MEDHA
  enforces: `--cap-drop ALL`, `no-new-privileges`, memory/CPU/pids limits,
  loopback-only port publishing. Rootless Docker is fine.
- Outbound network for base-image pulls (`nginx:1.27-alpine`,
  `python:3.12-slim`, `node:22-alpine`) on first use.

## 3. Configuration

```env
MEDHA_ENV=development
MEDHA_EXECUTOR_MODE=real        # or "docker" (legacy alias); needs the next line too
MEDHA_DOCKER_EXECUTE=true
MEDHA_DOCKER_CLEANUP=true
MEDHA_REAL_BUILD_TIMEOUT_SECONDS=600
MEDHA_REAL_READINESS_TIMEOUT_SECONDS=90
```

Validation is fail-closed at startup/request time: missing daemon, production
env, or non-positive timeouts produce structured errors (`REAL_BUILDER_UNAVAILABLE`,
`REAL_EXECUTION_DISABLED_HOSTED`, `BUILD_FAILED`, `READINESS_FAILED`) — never
a silent simulation presented as real.

For private GitHub repos also set (server-only, never logged or persisted):

```env
GITHUB_APP_ID=
GITHUB_APP_PRIVATE_KEY=
GITHUB_APP_INSTALLATION_ID=
```

The backend mints a short-lived installation token per run, verifies the
installation can access the requested repo, and passes it to git via
`http.extraHeader` (never in the URL).

## 4. Run a controlled real deployment

1. Start the stack (repo root): `npm run dev` (backend :8000, frontend :3000).
2. Create a deployment with `mode: "real"`, the repo URL, and an exact
   commit SHA (or a branch/tag — it is resolved to an immutable SHA and
   re-validated before execution; a moved ref fails with `STALE_SOURCE`).
3. Watch the pipeline: analyze → CNP → verify → **real build** → readiness gate.
4. Success requires the readiness gate. Check `execution_mode: "real"`,
   `image_digest`, and `readiness` in the result, and container output under
   `GET /api/deploy/{id}/logs` → `runtime_logs` (also shown in the run-detail
   "Application container output" panel).

## 5. Troubleshooting

| Symptom | Likely cause | Action |
|---|---|---|
| `REAL_BUILDER_UNAVAILABLE` | no daemon / wrong host | run `docker version` on the backend host |
| `REAL_EXECUTION_NOT_ENABLED` | flags missing | set both `MEDHA_EXECUTOR_MODE=real` and `MEDHA_DOCKER_EXECUTE=true` |
| `REAL_EXECUTION_DISABLED_HOSTED` | `MEDHA_ENV=production` | real runs are control-plane-forbidden; use a separate builder host |
| `UNSUPPORTED_STACK` | manifests not recognized | add `package.json` / requirements+entrypoint / `index.html` |
| `EXECUTION_NOT_CONFIGURED` | no executor configured | set simulator explicitly (test-only) or real+DOCKER_EXECUTE with a builder |
| `EXECUTION_DISABLED_HOSTED` | `MEDHA_ENV=production` | execution is control-plane-forbidden; use a separate builder host |
| `BUILD_FAILED` | deps or Dockerfile error | tail in the result message; fix the app, not the policy |
| `READINESS_FAILED` / timed out | app crashed or wrong port | check `runtime_logs.stderr`; confirm the app listens on the target port |
| `STALE_SOURCE` / `SHA_MISMATCH` | ref moved mid-flight | re-plan against the new SHA (by design, never auto-follow) |
| `GITHUB_*` | app/installation/token problem | verify App id/key/installation and repo access; tokens are never logged |

## 6. Cleanup

- Failed builds remove their workload automatically (container + image +
  build marker). Successful containers carry `com.medha.*` labels and are
  removed by `POST /api/deploy/{id}/cancel` or the periodic deployment
  cleanup. Cleanup never touches unlabeled/foreign resources (verified by
  unit tests).
- To remove everything for one deployment manually:
  `docker ps -a --filter label=com.medha.deployment_id=<dep_id>`, then
  `docker rm -f` only those names, plus the `medha_<shortid>_<profile>` image.

## 7. Live verification checklist (for the audit trail)

When a daemon is available, run the gated suite and keep its output:

```powershell
$env:MEDHA_E2E_REAL = "1"
python -m pytest backend/tests/test_real_e2e_gated.py -q
```

Record: source SHA, profile, image digest, readiness attempts/status, log
tail, and the persisted `execution_mode`. Do not run this against production
systems or untrusted repositories.
