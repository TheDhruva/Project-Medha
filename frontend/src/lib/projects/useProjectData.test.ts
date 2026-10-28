import { describe, expect, it } from "vitest";

import type { AgentSnapshotRow, BackendSystemEvent, RunLogLine } from "@/lib/api/client";
import {
  agentsFromSnapshot,
  agentInitials,
  appendEventToFeed,
  buildRunFeed,
  buildRunRoster,
  derivePipeline,
  formatFeedTime,
  resolveAgents,
  type FeedKind,
  type RunHydration,
} from "@/lib/projects/useProjectData";

function log(
  partial: Partial<RunLogLine> & { ts: string; message: string; type: string },
): RunLogLine {
  return {
    level: "info",
    source: "system",
    stage: null,
    status: null,
    is_demo: false,
    ...partial,
  };
}

function row(partial: Partial<AgentSnapshotRow> & { id: string }): AgentSnapshotRow {
  return {
    name: partial.id,
    status: "idle",
    activity: "Waiting",
    lastEvent: "—",
    durationMs: null,
    startedAt: null,
    finishedAt: null,
    deps: [],
    ...partial,
  };
}

function event(
  partial: Partial<BackendSystemEvent> & { ts: string; type: string; message: string },
): BackendSystemEvent {
  return {
    event_id: `evt_${partial.ts}_${partial.type}`,
    deployment_id: "dep_1",
    stage: null,
    level: "info",
    status: null,
    is_demo: false,
    ...partial,
  };
}

function hydrationWith(agents: RunHydration["agents"]): RunHydration {
  return {
    logs: [],
    agents,
    executionMode: null,
    constraints: [],
    negotiation: null,
    verification: null,
    critic: null,
    coverage: null,
    graph: { nodes: [], edges: [] },
    rollback: null,
    changeImpact: null,
    changeImpactLabel: null,
    changeImpactIsDemo: false,
    health: null,
    runtimeLogs: null,
  };
}

describe("backend agent snapshot mapping", () => {
  it("maps backend statuses to display states without inventing progress", () => {
    const states = agentsFromSnapshot([
      row({ id: "preflight", status: "complete", activity: "Done", durationMs: 12.5 }),
      row({ id: "analyzer", status: "running", activity: "Analyzing" }),
      row({ id: "docker", status: "failed", activity: "Failed", error: "boom" }),
      row({ id: "nginx", status: "timed_out", activity: "Timed out" }),
      row({ id: "security", status: "cancelled", activity: "Cancelled" }),
      row({ id: "mediator", status: "skipped", activity: "Skipped" }),
      row({ id: "verifier", status: "bogus", activity: "??" }),
    ]);
    expect(states.map((s) => s.state)).toEqual([
      "done",
      "active",
      "blocked",
      "blocked",
      "idle",
      "idle",
      "idle",
    ]);
    expect(states[0].detail).toContain("0.0s");
    expect(states[2].detail).toContain("boom");
    expect(states[0].label).toBe("Preflight");
  });

  it("prefers the backend snapshot and falls back to logs only when absent", () => {
    const snapshot = [row({ id: "preflight", status: "complete", activity: "Done" })];
    const fromBackend = resolveAgents(hydrationWith(snapshot), null, "running");
    expect(fromBackend.source).toBe("backend");
    expect(fromBackend.agents).toHaveLength(1);
    expect(fromBackend.agents[0].state).toBe("done");

    const fromLogs = resolveAgents(hydrationWith(null), null, "failed");
    expect(fromLogs.source).toBe("logs");
    // Fallback never claims unobserved stages as done.
    expect(fromLogs.agents.every((a) => a.state !== "done")).toBe(true);
  });
});

describe("buildRunFeed", () => {
  it("orders recorded events chronologically and renders system updates factually", () => {
    const feed = buildRunFeed(
      [
        log({
          ts: "2026-10-23T10:00:10Z",
          type: "deployment.completed",
          message: "Deployment completed successfully.",
          status: "success",
        }),
        log({
          ts: "2026-10-23T10:00:00Z",
          type: "stage.started",
          source: "ANALYZE",
          stage: "ANALYZE",
          message: "MEDHA is identifying the application's deployment structure.",
        }),
      ],
      null,
    );
    expect(feed.map((e) => e.ts)).toEqual([
      "2026-10-23T10:00:00Z",
      "2026-10-23T10:00:10Z",
    ]);
    expect(feed[0]).toMatchObject({
      actor: "MEDHA",
      isAgent: false,
      message: "MEDHA is identifying the application's deployment structure.",
      outcome: null,
    });
    expect(feed[1].outcome).toBe("success");
    expect(feed[0].timeLabel).not.toBeNull();
  });

  it("attributes agent events and handoffs only from recorded evidence", () => {
    const snapshot = [
      row({
        id: "analyzer",
        status: "complete",
        activity: "Repository analysis found 2 services.",
        lastEvent: "Repository analysis found 2 services.",
        durationMs: 4000,
        deps: ["preflight"],
      }),
      row({
        id: "docker",
        status: "complete",
        activity: "Container plan ready.",
        lastEvent: "Container plan ready.",
        durationMs: 1500,
        deps: ["analyzer"],
      }),
    ];
    const feed = buildRunFeed(
      [
        log({ ts: "2026-10-23T10:00:01Z", type: "agent.started", message: "analyzer started" }),
        log({
          ts: "2026-10-23T10:00:05Z",
          type: "agent.completed",
          message: "Repository analysis found 2 services.",
          status: "success",
        }),
        log({ ts: "2026-10-23T10:00:06Z", type: "agent.started", message: "docker started" }),
      ],
      snapshot,
    );
    expect(feed[0]).toMatchObject({ actor: "Code Analyzer", isAgent: true, message: "Started." });
    // preflight never recorded a completion → no handoff is invented.
    expect(feed[0].handoffs).toEqual([]);
    expect(feed[1]).toMatchObject({ actor: "Code Analyzer", durationMs: 4000, outcome: "success" });
    // analyzer completed earlier in the feed and docker declares it as a dep.
    expect(feed[2].actor).toBe("Docker");
    expect(feed[2].handoffs).toEqual([{ fromIndex: 1, fromLabel: "Code Analyzer" }]);
  });

  it("never guesses attribution, severity comes from the record", () => {
    const ambiguous = [
      row({ id: "docker", status: "complete", activity: "Same summary." }),
      row({ id: "nginx", status: "complete", activity: "Same summary." }),
    ];
    const feed = buildRunFeed(
      [
        log({ ts: "2026-10-23T10:00:01Z", type: "agent.started", message: "docker started" }),
        log({ ts: "2026-10-23T10:00:02Z", type: "agent.completed", message: "Same summary.", status: "success" }),
        log({ ts: "2026-10-23T10:00:03Z", type: "agent.completed", message: "No snapshot recorded this.", status: "failed" }),
        log({ ts: "2026-10-23T10:00:04Z", type: "stage.completed", stage: "VERIFY", status: "warning", message: "One check to review." }),
        log({ ts: "2026-10-23T10:00:05Z", type: "deployment.failed", message: "Run failed." }),
      ],
      ambiguous,
    );
    // Two snapshot rows recorded the same text → stays generic, never guessed.
    expect(feed[1].actor).toBe("Agent");
    expect(feed[1].durationMs).toBeNull();
    expect(feed[2].actor).toBe("Agent");
    // "agent.completed" with a recorded failure is an error, not a success.
    expect(feed[2].outcome).toBe("error");
    expect(feed[3].outcome).toBe("warning");
    expect(feed[4].outcome).toBe("error");
  });

  it("dedupes repeated records, keeps unknown events and bad timestamps safe", () => {
    const dup = log({
      ts: "2026-10-23T10:00:01Z",
      type: "stage.started",
      source: "PREFLIGHT",
      stage: "PREFLIGHT",
      message: "Preflight started.",
    });
    const feed = buildRunFeed(
      [
        dup,
        // Same event returned twice by a refresh — must not double-render.
        { ...dup },
        log({ ts: "2026-10-23T10:00:02Z", type: "mystery.event", message: "Unrecognized but recorded." }),
        log({ ts: "not-a-timestamp", type: "stage.completed", message: "No parseable time." }),
      ],
      null,
    );
    expect(feed).toHaveLength(3);
    // Unknown event types stay factual system entries; nothing crashes.
    expect(feed[1]).toMatchObject({ isAgent: false, actor: "MEDHA", message: "Unrecognized but recorded." });
    // Unparseable ts sorts last and simply has no clock label.
    expect(feed[2].ts).toBe("not-a-timestamp");
    expect(feed[2].timeLabel).toBeNull();
    // Feed keys stay unique even for identical inputs.
    expect(new Set(feed.map((e) => e.key)).size).toBe(feed.length);
  });

  it("keeps runs isolated: the same helper on another run's records never mixes", () => {
    const runA = buildRunFeed(
      [log({ ts: "2026-10-23T10:00:01Z", type: "agent.started", message: "docker started" })],
      null,
    );
    const runB = buildRunFeed(
      [log({ ts: "2026-10-23T11:00:01Z", type: "stage.started", source: "VERIFY", stage: "VERIFY", message: "Verifying." })],
      null,
    );
    // Each call only reflects its own input — no cross-run leakage by construction.
    expect(runA.map((e) => e.message)).toEqual(["Started."]);
    expect(runA.map((e) => e.agentId)).toEqual(["docker"]);
    expect(runB.map((e) => e.message)).toEqual(["Verifying."]);
  });

  it("classifies badge kinds and keeps dedup keys from the original message", () => {
    const feed = buildRunFeed(
      [
        log({ ts: "2026-10-23T10:00:01Z", type: "constraint.published", message: "Constraint published." }),
        log({ ts: "2026-10-23T10:00:02Z", type: "agent.started", message: "analyzer started" }),
        log({ ts: "2026-10-23T10:00:03Z", type: "deployment.completed", message: "Done.", status: "success" }),
      ],
      null,
    );
    expect(feed.map((e) => e.kind)).toEqual(["hypothesis", "agent_activity", "final_decision"]);
    // The dedup key uses the ORIGINAL message (display rewrites agent.started).
    expect(feed[1].eventKey).toBe("2026-10-23T10:00:02Z|agent.started|analyzer started");
    expect(feed[1].longMessage).toBe(false);
    // REST lines carry no metadata — the technical line stays null.
    expect(feed[2].technical).toBeNull();
  });
});

describe("appendEventToFeed", () => {
  it("maps real backend event types to feed badge kinds", () => {
    const cases: Array<[string, FeedKind]> = [
      ["constraint.published", "hypothesis"],
      ["constraint.conflict", "challenge"],
      ["agent.started", "agent_activity"],
      ["agent.completed", "agent_activity"],
      ["verification.started", "verification_started"],
      ["verification.check", "verification_check"],
      ["verification.passed", "verification_passed"],
      ["verification.failed", "verification_failed"],
      ["negotiation.resolved", "coordinator_decision"],
      ["critic.completed", "coordinator_decision"],
      ["deployment.completed", "final_decision"],
      ["deployment.failed", "final_decision"],
      ["stage.started", "note"],
    ];
    for (const [type, kind] of cases) {
      const feed = appendEventToFeed(
        [],
        event({ ts: "2026-10-23T10:00:00Z", type, message: "recorded event" }),
      );
      expect(feed[0].kind, type).toBe(kind);
    }
  });

  it("reads merge decisions from SSE data and detects finding submissions", () => {
    const merge = appendEventToFeed(
      [],
      event({
        ts: "2026-10-23T10:01:00Z",
        type: "system.message",
        message: "Merge evaluation finished.",
        data: { merge_decision: { outcome: "blocked" } },
      }),
    );
    expect(merge[0].kind).toBe("merge_decision");

    const finding = appendEventToFeed(
      [],
      event({
        ts: "2026-10-23T10:02:00Z",
        type: "system.message",
        message: "Finding submitted: gitleaks detected a token.",
      }),
    );
    expect(finding[0].kind).toBe("finding_submitted");

    const note = appendEventToFeed(
      [],
      event({
        ts: "2026-10-23T10:03:00Z",
        type: "system.message",
        message: "Nothing else to report.",
      }),
    );
    expect(note[0].kind).toBe("note");
  });

  it("deduplicates against a REST-built feed by ts/type/message", () => {
    const rest = buildRunFeed(
      [log({ ts: "2026-10-23T10:00:01Z", type: "agent.started", message: "analyzer started" })],
      null,
    );
    // The stream replays the already-loaded line: same array, no double entry.
    const replay = appendEventToFeed(
      rest,
      event({ ts: "2026-10-23T10:00:01Z", type: "agent.started", message: "analyzer started" }),
    );
    expect(replay).toBe(rest);

    const appended = appendEventToFeed(
      rest,
      event({ ts: "2026-10-23T10:00:02Z", type: "stage.started", message: "New live event." }),
    );
    expect(appended).toHaveLength(rest.length + 1);
    expect(appended[appended.length - 1]).toMatchObject({
      message: "New live event.",
      kind: "note",
      longMessage: false,
      technical: null,
    });
  });

  it("keeps messages verbatim, flags long ones and carries technical lines", () => {
    const long = "a".repeat(200);
    const feed = appendEventToFeed(
      [],
      event({
        ts: "2026-10-23T10:04:00Z",
        type: "system.message",
        message: long,
        data: { technical: "scanner exited 1" },
      }),
    );
    expect(feed[0].message).toBe(long);
    expect(feed[0].longMessage).toBe(true);
    expect(feed[0].technical).toBe("scanner exited 1");

    const multiline = appendEventToFeed(
      [],
      event({ ts: "2026-10-23T10:05:00Z", type: "system.message", message: "line one\nline two" }),
    );
    expect(multiline[0].longMessage).toBe(true);
    expect(multiline[0].technical).toBeNull();
  });

  it("attributes agent events from the recorded message only", () => {
    const known = appendEventToFeed(
      [],
      event({ ts: "2026-10-23T10:06:00Z", type: "agent.started", message: "docker started" }),
    );
    expect(known[0]).toMatchObject({ isAgent: true, agentId: "docker", actor: "Docker" });

    const unknown = appendEventToFeed(
      [],
      event({ ts: "2026-10-23T10:07:00Z", type: "agent.started", message: "mystery started" }),
    );
    expect(unknown[0]).toMatchObject({ isAgent: false, actor: "MEDHA" });
  });
});

describe("buildRunRoster", () => {
  const started = (id: string, ts: string) =>
    log({ ts, type: "agent.started", message: `${id} started` });

  it("discovers participating agents from recorded evidence with stable sides", () => {
    const feed = buildRunFeed(
      [
        started("analyzer", "2026-10-23T10:00:01Z"),
        started("docker", "2026-10-23T10:00:02Z"),
      ],
      null,
    );
    const roster = buildRunRoster(feed, null);
    expect(roster.map((a) => a.id)).toEqual(["analyzer", "docker"]);
    expect(roster.map((a) => a.label)).toEqual(["Code Analyzer", "Docker"]);
    // Stable, visually balanced alternating sides; every agent still named.
    expect(roster.map((a) => a.side)).toEqual(["left", "right"]);
    expect(roster.every((a) => a.spoke)).toBe(true);
    // Sides are deterministic across rebuilds (refresh safety).
    expect(buildRunRoster(feed, null).map((a) => a.side)).toEqual(["left", "right"]);
  });

  it("includes observed snapshot agents, skips idle ones, adds no invented state", () => {
    const feed = buildRunFeed(
      [log({ ts: "2026-10-23T10:00:09Z", type: "agent.completed", message: "Repo scan done.", status: "success" })],
      [
        row({ id: "nginx", status: "complete", activity: "Config ready." }),
        row({ id: "security", status: "running", activity: "Scanning deps." }),
        row({ id: "verifier", status: "idle", activity: "Waiting" }),
      ],
    );
    const roster = buildRunRoster(feed, [
      row({ id: "nginx", status: "complete", activity: "Config ready." }),
      row({ id: "security", status: "running", activity: "Scanning deps." }),
      row({ id: "verifier", status: "idle", activity: "Waiting" }),
    ]);
    // nginx (complete) + security (running) in registry order; idle verifier
    // is not a participant; the unattributed slot appends last.
    expect(roster.map((a) => a.id)).toEqual(["nginx", "security", "unattributed"]);
    expect(roster[0].state).toBe("done");
    expect(roster[1].state).toBe("active");
    // The unattributed agent.completed gets a generic roster slot, honestly labeled.
    expect(roster[2].label).toBe("Agent");
    // Unattributed slot has no invented state or detail.
    expect(roster[2].state).toBeNull();
    expect(roster[2].detail).toBeNull();
  });

  it("returns an empty roster when nothing was recorded", () => {
    expect(buildRunRoster([], null)).toEqual([]);
  });
});

describe("agentInitials", () => {
  it("derives up to two initials from labels", () => {
    expect(agentInitials("Code Analyzer")).toBe("CA");
    expect(agentInitials("Mediator / CNP")).toBe("MC");
    expect(agentInitials("Docker")).toBe("DO");
  });
});

describe("formatFeedTime", () => {
  it("formats a real timestamp and returns null for unparseable input", () => {
    expect(formatFeedTime("2026-10-23T10:00:00Z")).toMatch(/\d{1,2}:\d{2}:\d{2} (AM|PM)/);
    expect(formatFeedTime("not-a-date")).toBeNull();
  });
});

describe("derivePipeline failure evidence", () => {
  it("never marks a started-but-unfinished stage done on a failed run", () => {
    const logs = [
      log({ ts: "t1", message: "PREFLIGHT started", type: "stage.started", stage: "PREFLIGHT" }),
      log({ ts: "t2", message: "PREFLIGHT completed", type: "stage.completed", stage: "PREFLIGHT" }),
      log({ ts: "t3", message: "ANALYZE started", type: "stage.started", stage: "ANALYZE" }),
    ];
    // The backend resets current_stage to COMPLETE on failure, erasing the
    // failing stage — completion evidence in the logs is the only truth.
    const stages = derivePipeline(logs, "COMPLETE", "failed");
    const byId = Object.fromEntries(stages.map((s) => [s.id, s.state]));

    expect(byId.preflight).toBe("done");
    expect(byId.analyze).toBe("blocked"); // started, never completed → failure point
    expect(byId.plan).toBe("idle"); // never reached — not done, not failed
    expect(byId.execute).toBe("idle");
  });
});
