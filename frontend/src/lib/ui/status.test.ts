import { describe, expect, it } from "vitest";

import { labelStatus, runSourceLabel, statusGlyph, stageTone } from "@/lib/ui/status";

describe("runSourceLabel", () => {
  it("resolves DEMO when selected mode is demo", () => {
    expect(runSourceLabel("demo", false)).toBe("DEMO");
  });

  it("resolves LIVE only when mode is real and snapshot is not demo", () => {
    expect(runSourceLabel("real", false)).toBe("LIVE");
  });

  it("resolves DEMO when the active snapshot is a demo run even if form says real", () => {
    expect(runSourceLabel("real", true)).toBe("DEMO");
  });
});

describe("status helpers", () => {
  it("computes a glyph for every status", () => {
    expect(statusGlyph("success")).toBe("✓");
    expect(statusGlyph("failed")).toBe("✕");
    expect(statusGlyph("running")).toBe("●");
    expect(statusGlyph("skipped")).toBe("–");
  });

  it("labels statuses uppercase with underscores expanded", () => {
    expect(labelStatus("rolled_back")).toBe("ROLLED BACK");
  });

  it("always returns a tailwind class for stage tones", () => {
    for (const status of ["pending", "running", "success", "warning", "failed", "skipped"]) {
      expect(stageTone(status as Parameters<typeof stageTone>[0])).toContain("medha-");
    }
  });
});