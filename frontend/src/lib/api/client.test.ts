import { afterEach, describe, expect, it, vi } from "vitest";

import {
  analyzeChangeImpact,
  eventsUrl,
  fetchChangeImpact,
  fetchDemoChangeImpact,
} from "@/lib/api/client";
import type { ChangeImpactResponse } from "@/lib/api/client";

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

let lastUrl: string | null = null;
let lastInit: RequestInit | undefined;

function stubFetch(response: Response): void {
  lastUrl = null;
  lastInit = undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      lastUrl = String(input);
      lastInit = init;
      return response;
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("change intelligence client", () => {
  it("analyzeChangeImpact POSTs the request to the analyze endpoint", async () => {
    stubFetch(jsonResponse({ analysis: { risk: { level: "low" } } }));
    const r = await analyzeChangeImpact({
      repository_url: "C:/repo",
      base_revision: "base",
      target_revision: "target",
      deployment_id: null,
    });
    expect(lastUrl).toMatch(/\/api\/change-impact\/analyze$/);
    expect(lastInit?.method).toBe("POST");
    const body = JSON.parse(String(lastInit?.body));
    expect(body).toMatchObject({
      repository_url: "C:/repo",
      base_revision: "base",
      target_revision: "target",
    });
    expect(r.analysis.risk.level).toBe("low");
  });

  it("analyzeChangeImpact surfaces backend error code", async () => {
    stubFetch(
      jsonResponse(
        { error: { code: "REPO_NOT_FOUND", message: "path missing" } },
        false,
        400,
      ),
    );
    await expect(
      analyzeChangeImpact({
        repository_url: "C:/nope",
        base_revision: "base",
        target_revision: "target",
      }),
    ).rejects.toMatchObject({ status: 400, code: "REPO_NOT_FOUND" });
  });

  it("fetchChangeImpact reads a persisted analysis by deployment id", async () => {
    stubFetch(jsonResponse({ deployment_id: "dep_1", analysis: {} } as ChangeImpactResponse));
    await fetchChangeImpact("dep_1");
    expect(lastUrl).toMatch(/\/api\/deploy\/dep_1\/change-impact$/);
  });

  it("fetchDemoChangeImpact hits the demo fixture endpoint", async () => {
    stubFetch(
      jsonResponse({
        is_demo: true,
        label: "DEMO/MOCK",
        analysis: { risk: { level: "high" } },
      } as ChangeImpactResponse),
    );
    const r = await fetchDemoChangeImpact();
    expect(lastUrl).toMatch(/\/api\/change-impact\/demo\/fixture$/);
    expect(r.is_demo).toBe(true);
    expect(r.label).toBe("DEMO/MOCK");
  });

  it("encodes deployment ids in SSE and artifact URLs", async () => {
    expect(eventsUrl("dep_abc 123/..")).toContain(
      `/api/deploy/${encodeURIComponent("dep_abc 123/..")}/events`,
    );
    stubFetch(jsonResponse({ deployment_id: "dep_1", analysis: {} } as ChangeImpactResponse));
    await fetchChangeImpact("dep_a/b");
    expect(lastUrl).toContain(`/api/deploy/${encodeURIComponent("dep_a/b")}/change-impact`);
  });
});