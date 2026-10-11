import { afterEach, describe, expect, it, vi } from "vitest";

import {
  decideProposal,
  fetchAiStatus,
  fetchProposals,
} from "@/lib/api/client";

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

describe("AI status + proposals client", () => {
  it("fetchAiStatus hits the status endpoint without credentials", async () => {
    stubFetch(
      jsonResponse({
        enabled: false,
        primary_provider: "groq",
        health: { providers: { groq: { configured: false } } },
      }),
    );
    const status = await fetchAiStatus();
    expect(lastUrl).toMatch(/\/api\/ai\/status$/);
    expect(status.enabled).toBe(false);
    expect(JSON.stringify(status)).not.toMatch(/gsk_|sk-/);
  });

  it("fetchProposals lists proposals", async () => {
    stubFetch(jsonResponse({ proposals: [{ proposal_id: "prp_1", status: "ready" }], total: 1 }));
    const body = await fetchProposals({ status: "ready" });
    expect(lastUrl).toMatch(/\/api\/proposals\?status=ready$/);
    expect(body.proposals).toHaveLength(1);
  });

  it("decideProposal POSTs approve decisions", async () => {
    stubFetch(jsonResponse({ proposal_id: "prp_1", status: "executing" }));
    const body = await decideProposal("prp_1", "approve");
    expect(lastUrl).toMatch(/\/api\/proposals\/prp_1\/approve$/);
    expect(lastInit?.method).toBe("POST");
    expect(body.status).toBe("executing");
  });

  it("decideProposal surfaces backend error codes", async () => {
    stubFetch(
      jsonResponse({ error: { code: "STALE_PROPOSAL", message: "stale" } }, false, 409),
    );
    await expect(decideProposal("prp_1", "approve")).rejects.toMatchObject({
      status: 409,
      code: "STALE_PROPOSAL",
    });
  });
});
