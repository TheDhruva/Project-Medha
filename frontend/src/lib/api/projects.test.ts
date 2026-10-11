import { afterEach, describe, expect, it, vi } from "vitest";

import {
  createProject,
  createProjectRun,
  deleteProject,
  disconnectProject,
  fetchProjects,
  registerAuthTokenGetter,
  verifyProject,
} from "@/lib/api/client";

/**
 * Project connection client: endpoint shapes, Bearer propagation, and
 * honest error surfacing (duplicates, unverified repos, disconnected).
 */

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

function authHeader(): string | null {
  return new Headers(lastInit?.headers).get("Authorization");
}

afterEach(() => {
  vi.unstubAllGlobals();
  registerAuthTokenGetter(null);
});

const PROJECT = {
  project_id: "prj_1",
  name: "Demo",
  provider: "github",
  repo_owner: "octo",
  repo_name: "demo",
  repository: "octo/demo",
  canonical_url: "https://github.com/octo/demo.git",
  branch: "main",
  visibility: "pending",
  connection_status: "pending",
};

describe("project connections client", () => {
  it("creates a project connection via POST", async () => {
    stubFetch(jsonResponse(PROJECT, true, 201));
    const project = await createProject({ name: "Demo", repository: "octo/demo" });
    expect(lastUrl).toMatch(/\/api\/projects$/);
    expect(lastInit?.method).toBe("POST");
    expect(project.repository).toBe("octo/demo");
  });

  it("surfaces duplicate connections as 409", async () => {
    stubFetch(
      jsonResponse({ error: { code: "PROJECT_EXISTS", message: "dup" } }, false, 409),
    );
    await expect(createProject({ name: "Demo", repository: "octo/demo" })).rejects.toMatchObject({
      status: 409,
      code: "PROJECT_EXISTS",
    });
  });

  it("lists the caller's projects", async () => {
    stubFetch(jsonResponse({ projects: [PROJECT], total: 1 }));
    const body = await fetchProjects();
    expect(lastUrl).toMatch(/\/api\/projects$/);
    expect(body.total).toBe(1);
  });

  it("verifies readability without inventing access", async () => {
    stubFetch(jsonResponse({ project: PROJECT, reachable: false, reason: "private?" }));
    const body = await verifyProject("prj_1");
    expect(lastUrl).toMatch(/\/api\/projects\/prj_1\/verify$/);
    expect(body.reachable).toBe(false);
    expect(body.reason).toBeTruthy();
  });

  it("starts a project-bound run", async () => {
    stubFetch(
      jsonResponse({ deployment_id: "dep_1", status: "started", project_id: "prj_1" }, true, 202),
    );
    const run = await createProjectRun("prj_1", { intent: "analyze" });
    expect(lastUrl).toMatch(/\/api\/projects\/prj_1\/runs$/);
    expect(run.project_id).toBe("prj_1");
  });

  it("rejects runs for disconnected projects with the backend code", async () => {
    stubFetch(
      jsonResponse({ error: { code: "PROJECT_NOT_CONNECTED", message: "no" } }, false, 409),
    );
    await expect(createProjectRun("prj_1")).rejects.toMatchObject({
      code: "PROJECT_NOT_CONNECTED",
    });
  });

  it("disconnects and deletes with Bearer attached", async () => {
    registerAuthTokenGetter(async () => "sess_owner_jwt");
    stubFetch(jsonResponse({ ...PROJECT, connection_status: "disconnected" }));
    await disconnectProject("prj_1");
    expect(lastUrl).toMatch(/\/disconnect$/);
    expect(authHeader()).toBe("Bearer sess_owner_jwt");

    stubFetch(jsonResponse({ deleted: "prj_1" }));
    await deleteProject("prj_1");
    expect(lastInit?.method).toBe("DELETE");
    expect(authHeader()).toBe("Bearer sess_owner_jwt");
  });
});
