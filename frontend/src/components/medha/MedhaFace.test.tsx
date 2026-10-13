import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { MedhaFace, faceStateFromRun } from "@/components/medha/MedhaFace";

describe("faceStateFromRun", () => {
  it("maps terminal failure to failed", () => {
    expect(faceStateFromRun({ status: "failed" })).toBe("failed");
    expect(faceStateFromRun({ status: "cancelled" })).toBe("failed");
    // A finished run whose verification actually failed is a failure.
    expect(faceStateFromRun({ status: "completed", verificationPassed: false })).toBe("failed");
  });

  it("maps verified completion to verified only with evidence", () => {
    expect(faceStateFromRun({ status: "succeeded", verificationPassed: true })).toBe("verified");
    expect(faceStateFromRun({ status: "completed", verificationPassed: true })).toBe("verified");
    // Completed without a verification artifact stays neutral — never fake success.
    expect(faceStateFromRun({ status: "completed" })).toBe("idle");
    expect(faceStateFromRun({ status: "succeeded", verificationPassed: null })).toBe("idle");
  });

  it("maps in-flight stages honestly", () => {
    expect(faceStateFromRun({ status: "running", stage: "PREFLIGHT" })).toBe("inspecting");
    expect(faceStateFromRun({ status: "running", stage: "NEGOTIATE" })).toBe("analyzing");
    expect(faceStateFromRun({ status: "started", stage: "VERIFY" })).toBe("verifying");
    expect(faceStateFromRun({ status: "running", stage: "EXECUTE" })).toBe("analyzing");
    expect(faceStateFromRun({ status: "running", stage: "RECOVER" })).toBe("recovering");
    expect(faceStateFromRun({ status: "queued" })).toBe("analyzing");
  });

  it("stays neutral for waiting and unknown states", () => {
    expect(faceStateFromRun({ status: "awaiting_approval" })).toBe("idle");
    expect(faceStateFromRun({ status: "partial_recovery" })).toBe("recovering");
    expect(faceStateFromRun({ status: null })).toBe("idle");
    expect(faceStateFromRun({ status: "something-new" })).toBe("idle");
  });
});

describe("MedhaFace", () => {
  it("announces each state accessibly without animation loops", () => {
    const { rerender } = render(<MedhaFace state="idle" />);
    expect(screen.getByRole("img", { name: "Medha is idle" })).toBeInTheDocument();
    rerender(<MedhaFace state="verified" />);
    expect(screen.getByRole("img", { name: "Verified successfully" })).toBeInTheDocument();
    rerender(<MedhaFace state="failed" />);
    expect(screen.getByRole("img", { name: "Run failed" })).toBeInTheDocument();
    // No SMIL, CSS animation, or timers: a single static SVG.
    const svg = screen.getByRole("img");
    expect(svg.querySelectorAll("animate, animateTransform, set").length).toBe(0);
  });
});
