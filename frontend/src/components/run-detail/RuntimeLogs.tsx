"use client";

import type { ExecutionMode, RuntimeLogsView } from "@/lib/demo/types";

/**
 * Real container stdout/stderr for `real` executions, from GET /logs
 * `runtime_logs`. Renders only backend-provided strings — never synthesized
 * output, and never the SSE event replay (that lives in the event timeline).
 * Returns null when runtime logs don't apply to this run.
 */
export function RuntimeLogsPanel({
  executionMode,
  runtimeLogs,
}: {
  executionMode: ExecutionMode | null;
  runtimeLogs: RuntimeLogsView | null;
}) {
  if (executionMode !== "real" && runtimeLogs == null) return null;
  const logs = runtimeLogs;

  return (
    <section
      aria-label="Runtime logs"
      className="rounded-xl border border-medha-border bg-white p-5 sm:p-6"
    >
      <p className="text-[11px] font-semibold uppercase tracking-[0.1em] text-medha-tertiary">
        Runtime logs
      </p>
      <h2 className="mt-1 text-lg font-semibold tracking-tight text-medha-text">
        Application container output
      </h2>

      {logs == null || logs.available === false ? (
        <div className="mt-3">
          <p className="text-sm text-medha-secondary">
            {logs == null
              ? "Container logs are not available for this run yet."
              : "Container logs are unavailable."}
          </p>
          {logs?.container ? (
            <p className="medha-mono mt-1 text-[11px] text-medha-tertiary">
              container: {logs.container}
              {logs.code ? ` · ${logs.code}` : ""}
            </p>
          ) : null}
          <p className="mt-1 text-xs text-medha-tertiary">
            Event history is still available in the timeline below — it is orchestration
            history, not container output.
          </p>
        </div>
      ) : (logs.stdout ?? "") === "" && (logs.stderr ?? "") === "" ? (
        <p className="mt-3 text-sm text-medha-secondary">
          The container is running but produced no output yet.
          {logs.container ? (
            <span className="medha-mono mt-1 block text-[11px] text-medha-tertiary">
              container: {logs.container}
            </span>
          ) : null}
        </p>
      ) : (
        <div className="mt-3 space-y-3">
          {logs.container ? (
            <p className="medha-mono text-[11px] text-medha-tertiary">
              container: {logs.container}
            </p>
          ) : null}
          {(logs.stdout ?? "") !== "" ? (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
                stdout
              </p>
              <pre className="medha-mono max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-medha-border bg-medha-muted p-3 text-[11px] leading-relaxed text-medha-text">
                {logs.stdout}
              </pre>
            </div>
          ) : null}
          {(logs.stderr ?? "") !== "" ? (
            <div>
              <p className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-medha-tertiary">
                stderr
              </p>
              <pre className="medha-mono max-h-64 overflow-auto whitespace-pre-wrap rounded-lg border border-medha-border bg-medha-muted p-3 text-[11px] leading-relaxed text-medha-text">
                {logs.stderr}
              </pre>
            </div>
          ) : null}
        </div>
      )}
    </section>
  );
}
