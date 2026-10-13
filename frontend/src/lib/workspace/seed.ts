import type {
  AgentRecord, CnpConflict, ChangeProposal, EvalSuite, Project, RunRecord,
} from "./types";

// Product workspace starts empty. No seeded projects, runs, or evaluations
// are injected. These exports exist only so isolated unit tests have stable
// shapes to import; they contain no fabricated operational data.
export const SEED_PROJECTS: Project[] = [];
export const SEED_PROPOSALS: ChangeProposal[] = [];
export const SEED_AGENTS: Record<string, AgentRecord[]> = {};
export function agentsFor(_projectId: string): AgentRecord[] {
  void _projectId;
  return [];
}
export const SEED_CONFLICTS: Record<string, CnpConflict[]> = {};
export function conflictsFor(_projectId: string): CnpConflict[] {
  void _projectId;
  return [];
}
export const SEED_RUNS: RunRecord[] = [];
export const SEED_EVALS: Record<string, EvalSuite> = {};
export function evalFor(_projectId: string): EvalSuite {
  void _projectId;
  return { status: "empty", results: [], note: "No evaluation has been run." } as unknown as EvalSuite;
}
