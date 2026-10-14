import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearApiCache,
  fetchConstraintsArtifact,
  fetchRunsList,
  getSseDiagnostics,
} from "@/lib/api/client";
import { applyBackendEvent, createRunningSnapshot } from "@/lib/api/eventMapper";
import type { BackendSystemEvent } from "@/lib/api/client";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
  clearApiCache();
});

describe("shared GET cache", () => {
  it("fetchRunsList serves repeat calls from cache within TTL", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ runs: [], total: 0, limit: 100, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchRunsList({ repository: "https://github.com/x/y", limit: 100 });
    await fetchRunsList({ repository: "https://github.com/x/y", limit: 100 });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("clearApiCache forces refetch", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ runs: [], total: 0, limit: 100, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchRunsList({ repository: "https://github.com/x/y", limit: 100 });
    clearApiCache("/api/deploys");
    await fetchRunsList({ repository: "https://github.com/x/y", limit: 100 });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("deduplicates identical concurrent requests into one fetch", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ runs: [], total: 0, limit: 100, offset: 0 }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await Promise.all([
      fetchRunsList({ repository: "https://github.com/x/y", limit: 100 }),
      fetchRunsList({ repository: "https://github.com/x/y", limit: 100 }),
      fetchRunsList({ repository: "https://github.com/x/y", limit: 100 }),
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("fetchConstraintsArtifact caches repeat hydration reads", async () => {
    const fetchMock = vi.fn(async () =>
      jsonResponse({ constraints: [], negotiation: null }),
    );
    vi.stubGlobal("fetch", fetchMock);
    await fetchConstraintsArtifact("dep_1");
    await fetchConstraintsArtifact("dep_1");
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});

describe("bounded trace state", () => {
  function evt(id: string): BackendSystemEvent {
    return {
      event_id: id,
      deployment_id: "dep_1",
      ts: "2026-01-01T00:00:00Z",
      stage: "ANALYZE",
      type: "stage.started",
      level: "info",
      message: `event ${id}`,
      status: null,
      is_demo: true,
    };
  }

  it("applyBackendEvent caps trace at 500 entries", () => {
    let snapshot = createRunningSnapshot("dep_1", null, true);
    for (let i = 0; i < 650; i += 1) {
      snapshot = applyBackendEvent(snapshot, evt(`evt_${i}`));
    }
    expect(snapshot.trace.length).toBeLessThanOrEqual(500);
    // Newest events are retained.
    expect(snapshot.trace[snapshot.trace.length - 1].id).toBe("evt_649");
  });
});

describe("sse diagnostics", () => {
  it("exposes bounded counters", () => {
    const d = getSseDiagnostics();
    expect(d).toMatchObject({
      sseConnections: expect.any(Number),
      sseReconnects: expect.any(Number),
      sseEvents: expect.any(Number),
    });
  });
});
