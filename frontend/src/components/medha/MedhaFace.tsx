"use client";

import { cn } from "@/lib/ui/cn";

/**
 * MedhaFace — a small, state-driven SVG character.
 *
 * The expression is derived ONLY from observed backend state via
 * `faceStateFromRun`. Unknown or absent state renders neutral `idle`.
 * Expression changes use a short CSS transition; there is no continuous
 * animation and no simulated progress.
 */

export type MedhaFaceState =
  | "idle"
  | "inspecting"
  | "analyzing"
  | "verifying"
  | "verified"
  | "failed"
  | "recovering";

export interface RunFaceInput {
  /** Backend run status (snapshot `runStatus` or list `status` vocabularies). */
  status: string | null | undefined;
  /** Current pipeline stage, when the backend reports one. */
  stage?: string | null | undefined;
  /** Stored verification outcome: true = passed, false = failed, null = none. */
  verificationPassed?: boolean | null | undefined;
}

/**
 * Map real lifecycle state to a face expression. Never invents activity:
 * anything unrecognized — including a finished run with no verification
 * artifact — stays neutral.
 */
export function faceStateFromRun(input: RunFaceInput): MedhaFaceState {
  const status = (input.status ?? "").toLowerCase();
  const stage = (input.stage ?? "").toLowerCase();

  if (status === "failed" || status === "cancelled") return "failed";
  if (status === "partial_recovery") return "recovering";
  if (status === "awaiting_approval") return "idle";
  if (status === "queued" || status === "started" || status === "running") {
    if (stage.includes("recover") || stage.includes("rollback")) return "recovering";
    if (stage.includes("verif")) return "verifying";
    if (stage.includes("preflight")) return "inspecting";
    return "analyzing";
  }
  if (status === "succeeded" || status === "completed") {
    if (input.verificationPassed === true) return "verified";
    if (input.verificationPassed === false) return "failed";
    return "idle";
  }
  return "idle";
}

const RING: Record<MedhaFaceState, string> = {
  idle: "var(--medha-border-strong)",
  inspecting: "var(--medha-run)",
  analyzing: "var(--medha-run)",
  verifying: "var(--medha-run)",
  verified: "var(--medha-success)",
  failed: "var(--medha-danger)",
  recovering: "var(--medha-warning)",
};

const INK: Record<MedhaFaceState, string> = {
  idle: "var(--medha-text-secondary)",
  inspecting: "var(--medha-run-ink)",
  analyzing: "var(--medha-run-ink)",
  verifying: "var(--medha-run-ink)",
  verified: "var(--medha-success)",
  failed: "var(--medha-danger)",
  recovering: "var(--medha-warning)",
};

const LABEL: Record<MedhaFaceState, string> = {
  idle: "Medha is idle",
  inspecting: "Medha is inspecting the repository",
  analyzing: "Medha is analyzing and negotiating",
  verifying: "Medha is verifying the plan",
  verified: "Verified successfully",
  failed: "Run failed",
  recovering: "Recovery in progress",
};

function Eyes({ state }: { state: MedhaFaceState }) {
  const ink = INK[state];
  if (state === "verified") {
    // Happy arcs.
    return (
      <g className="medha-face-shape" stroke={ink} strokeWidth="2" strokeLinecap="round" fill="none">
        <path d="M14 21 q3 -4 6 0" />
        <path d="M24 21 q3 -4 6 0" />
      </g>
    );
  }
  if (state === "failed") {
    // X eyes.
    return (
      <g className="medha-face-shape" stroke={ink} strokeWidth="2" strokeLinecap="round">
        <path d="M14.5 18.5 l5 5 m0 -5 l-5 5" />
        <path d="M25.5 18.5 l5 5 m0 -5 l-5 5" />
      </g>
    );
  }
  const height = state === "idle" ? 3.4 : state === "inspecting" ? 2 : 4.6;
  const width = state === "verifying" ? 3 : 4.6;
  return (
    <g className="medha-face-shape" fill={ink}>
      <rect x={17 - width / 2} y={21 - height / 2} width={width} height={height} rx={height / 2} />
      <rect x={27 - width / 2} y={21 - height / 2} width={width} height={height} rx={height / 2} />
    </g>
  );
}

function Mouth({ state }: { state: MedhaFaceState }) {
  const ink = INK[state];
  switch (state) {
    case "verified":
      return (
        <path className="medha-face-shape" d="M17 28 q5 5 10 0" stroke={ink} strokeWidth="2" strokeLinecap="round" fill="none" />
      );
    case "failed":
      return (
        <path className="medha-face-shape" d="M17 30 q5 -5 10 0" stroke={ink} strokeWidth="2" strokeLinecap="round" fill="none" />
      );
    case "recovering":
      return (
        <path className="medha-face-shape" d="M15 29 q2.5 -2.5 5 0 t5 0 t5 0" stroke={ink} strokeWidth="2" strokeLinecap="round" fill="none" />
      );
    case "verifying":
      return <circle className="medha-face-shape" cx="22" cy="29" r="2.4" stroke={ink} strokeWidth="2" fill="none" />;
    case "inspecting":
      return <circle className="medha-face-shape" cx="22" cy="29" r="1.6" fill={ink} />;
    default:
      return (
        <path className="medha-face-shape" d="M17 29 h10" stroke={ink} strokeWidth="2" strokeLinecap="round" />
      );
  }
}

export function MedhaFace({
  state,
  size = 40,
  className,
}: {
  state: MedhaFaceState;
  size?: number;
  className?: string;
}) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 44 44"
      role="img"
      aria-label={LABEL[state]}
      className={cn("shrink-0", className)}
    >
      <circle cx="22" cy="22" r="19" fill="var(--medha-surface)" stroke={RING[state]} strokeWidth="2.5" className="medha-face-shape" />
      {/* Antenna: present in every state, part of the mark — not activity. */}
      <g stroke={INK[state]} strokeWidth="2" strokeLinecap="round" className="medha-face-shape">
        <path d="M22 3 v4" />
      </g>
      <circle cx="22" cy="3.5" r="1.8" fill={INK[state]} className="medha-face-shape" />
      <Eyes state={state} />
      <Mouth state={state} />
    </svg>
  );
}
