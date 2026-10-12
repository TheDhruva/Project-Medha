/* Lightweight Web-Vitals + navigation diagnostics (no new deps, no PII).
 * Uses the Performance API only. Samples are kept in a bounded ring buffer
 * (last 50) for local debugging via getPerfDiagnostics(). Nothing is
 * transmitted — no telemetry endpoint exists in V1.
 */

export interface PerfSample {
  name: string;
  value: number;
  at: number;
}

const samples: PerfSample[] = [];

function push(name: string, value: number): void {
  if (!Number.isFinite(value) || value < 0) return;
  samples.push({ name, value: Math.round(value * 10) / 10, at: Date.now() });
  if (samples.length > 50) samples.splice(0, samples.length - 50);
}

export function getPerfDiagnostics(): PerfSample[] {
  return [...samples];
}

export function markHydration(label: string, t0: number): void {
  try {
    push(`hydration.${label}`, performance.now() - t0);
  } catch {
    /* Performance API unavailable — skip silently */
  }
}

/** Observe LCP/INP/CLS once per page load (no callbacks retained). */
export function initWebVitals(): void {
  try {
    if (typeof window === "undefined" || typeof PerformanceObserver === "undefined") return;
    const lcp = new PerformanceObserver((entryList) => {
      for (const entry of entryList.getEntries()) {
        const e = entry as PerformanceEntry & { renderTime?: number; loadTime?: number };
        push("vitals.lcp", e.renderTime ?? e.loadTime ?? 0);
      }
      lcp.disconnect();
    });
    lcp.observe({ type: "largest-contentful-paint", buffered: true });
    const cls = new PerformanceObserver((entryList) => {
      let value = 0;
      for (const entry of entryList.getEntries()) {
        const e = entry as PerformanceEntry & { value?: number; hadRecentInput?: boolean };
        if (!e.hadRecentInput) value += e.value ?? 0;
      }
      push("vitals.cls", value);
    });
    cls.observe({ type: "layout-shift", buffered: true });
    // INP via event timing (longtask fallback avoided — keep observer count low).
    const inp = new PerformanceObserver((entryList) => {
      for (const entry of entryList.getEntries()) {
        const e = entry as PerformanceEntry & { duration?: number };
        push("vitals.inp", e.duration ?? 0);
      }
    });
    inp.observe({ type: "event", buffered: true, durationThreshold: 40 } as PerformanceObserverInit);
    setTimeout(() => {
      try {
        inp.disconnect();
        cls.disconnect();
      } catch {
        /* noop */
      }
    }, 30000);
  } catch {
    /* unsupported browser — skip silently */
  }
}
