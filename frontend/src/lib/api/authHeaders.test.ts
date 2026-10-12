import { afterEach, describe, expect, it, vi } from "vitest";

import {
  clearApiCache,
  decideProposal,
  fetchAiStatus,
  fetchDeployment,
  fetchProposals,
  fetchRunsList,
  registerAuthTokenGetter,
  subscribeDeploymentEvents,
} from "@/lib/api/client";

/**
 * Regression tests for the shared API client auth contract:
 * - apiFetch delegates to the underlying fetch exactly once (no recursion).
 * - The Clerk Bearer token is attached to every protected endpoint.
 * - Signed-out callers send no Authorization header.
 * - The SSE subscription path carries the token (EventSource can't).
 */

function jsonResponse(body: unknown, ok = true, status = 200): Response {
  return {
    ok,
    status,
    statusText: ok ? "OK" : "Error",
    json: async () => body,
  } as Response;
}

interface SeenCall {
  url: string;
  init?: RequestInit;
}

let calls: SeenCall[] = [];

function stubFetch(response: Response): void {
  calls = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      calls.push({ url: String(input), init });
      return response;
    }),
  );
}

function authOf(call: SeenCall): string | null {
  const headers = new Headers(call.init?.headers);
  return headers.get("Authorization");
}

afterEach(() => {
  vi.unstubAllGlobals();
  registerAuthTokenGetter(null);
  clearApiCache();
});

describe("shared API client auth", () => {
  it("delegates to fetch exactly once per call (no recursion)", async () => {
    stubFetch(jsonResponse({ proposals: [], total: 0 }));
    await fetchProposals({ limit: 5 });
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toMatch(/\/api\/proposals\?limit=5$/);
  });

  it("sends no Authorization header when signed out", async () => {
    stubFetch(jsonResponse({ runs: [], total: 0, limit: 1, offset: 0, filters: {} }));
    await fetchRunsList({ limit: 1 });
    expect(calls).toHaveLength(1);
    expect(authOf(calls[0]!)).toBeNull();
  });

  it("attaches the Clerk Bearer token to protected reads", async () => {
    registerAuthTokenGetter(async () => "sess_test_jwt");
    stubFetch(
      jsonResponse({
        deployment_id: "dep_1",
        status: "completed",
        mode: "real",
        is_demo: false,
      }),
    );
    await fetchDeployment("dep_1");
    expect(calls).toHaveLength(1);
    expect(authOf(calls[0]!)).toBe("Bearer sess_test_jwt");
  });

  it("attaches the token to AI status and proposal reads", async () => {
    registerAuthTokenGetter(async () => "sess_test_jwt");
    stubFetch(jsonResponse({ enabled: false }));
    await fetchAiStatus();
    expect(calls).toHaveLength(1);
    expect(authOf(calls[0]!)).toBe("Bearer sess_test_jwt");

    stubFetch(jsonResponse({ proposals: [], total: 0 }));
    await fetchProposals({});
    expect(calls).toHaveLength(1);
    expect(authOf(calls[0]!)).toBe("Bearer sess_test_jwt");
  });

  it("attaches the token to approve/reject decisions", async () => {
    registerAuthTokenGetter(async () => "sess_test_jwt");
    stubFetch(jsonResponse({ proposal_id: "prp_1", status: "executing" }));
    await decideProposal("prp_1", "reject", "not now");
    expect(calls).toHaveLength(1);
    expect(calls[0]?.init?.method).toBe("POST");
    expect(authOf(calls[0]!)).toBe("Bearer sess_test_jwt");
  });

  it("attaches the token to the SSE subscription request", async () => {
    registerAuthTokenGetter(async () => "sess_test_jwt");
    const reader = {
      read: async () => ({ done: true as const, value: undefined }),
      releaseLock: () => undefined,
    };
    stubFetch({ ok: true, body: { getReader: () => reader } } as unknown as Response);
    const sub = subscribeDeploymentEvents("dep_1", { onEvent: () => undefined });
    await new Promise((resolve) => setTimeout(resolve, 0));
    sub.close();
    expect(calls).toHaveLength(1);
    expect(calls[0]?.url).toMatch(/\/api\/deploy\/dep_1\/events(\?.*)?$/);
    expect(authOf(calls[0]!)).toBe("Bearer sess_test_jwt");
  });

  it("proceeds without credentials when the token getter throws", async () => {
    registerAuthTokenGetter(async () => {
      throw new Error("signed out");
    });
    stubFetch(jsonResponse({ runs: [], total: 0, limit: 1, offset: 0, filters: {} }));
    await fetchRunsList({ limit: 1 });
    expect(calls).toHaveLength(1);
    expect(authOf(calls[0]!)).toBeNull();
  });
});
