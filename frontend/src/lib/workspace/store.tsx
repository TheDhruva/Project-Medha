"use client";

import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import type { BoardLayout, ChangeProposal, Project, RunRecord } from "./types";
import { DEFAULT_BOARD_LAYOUT } from "./types";
import { SEED_PROJECTS, SEED_PROPOSALS, SEED_RUNS } from "./seed";

const PROJECTS_KEY = "medha.workspace.projects.v1";
const PROPOSALS_KEY = "medha.workspace.proposals.v1";
const BOARD_KEY = "medha.workspace.board.v1";
const ACTIVE_KEY = "medha.workspace.active.v1";
const RECENT_KEY = "medha.workspace.recent.v1";

function load<T>(key: string, fallback: T): T {
  try {
    if (typeof window === "undefined") return fallback;
    const raw = window.localStorage.getItem(key);
    if (!raw) return fallback;
    return JSON.parse(raw) as T;
  } catch {
    return fallback;
  }
}

function save(key: string, value: unknown) {
  try {
    window.localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* storage full/blocked — demo state stays in memory */
  }
}

export function isProposalApprovable(p: ChangeProposal): { ok: boolean; reason: string | null } {
  if (p.stale || p.state === "outdated") return { ok: false, reason: `Superseded${p.supersededBy ? ` by ${p.supersededBy}` : ""} — approval of revision ${p.sourceRevision} is invalid. Re-analysis of the newer revision is required.` };
  if (p.state === "blocked") return { ok: false, reason: "Blocked: unresolved constraints or a failed verification gate. Approval is disabled until CNP resolves and the gate passes." };
  if (p.state === "rejected") return { ok: false, reason: "Rejected proposals cannot be approved. Request re-analysis to create a new revision." };
  if (p.state === "approved") return { ok: false, reason: "Already approved for this exact revision. A newer revision needs a new approval." };
  return { ok: true, reason: null };
}

interface WorkspaceValue {
  projects: Project[];
  proposals: ChangeProposal[];
  runs: RunRecord[];
  activeProjectId: string | null;
  recentIds: string[];
  boards: Record<string, BoardLayout>;
  setActiveProject: (id: string | null) => void;
  createProject: (input: { name: string; objective: string; repoUrl: string; branch: string }) => Project;
  deleteProject: (id: string) => void;
  updateProject: (id: string, patch: Partial<Project>) => void;
  proposalsFor: (projectId: string) => ChangeProposal[];
  runsFor: (projectId: string) => RunRecord[];
  reviewProposal: (proposalId: string, action: "approve" | "reject" | "request_changes", note?: string) => { ok: boolean; message: string };
  boardFor: (projectId: string) => BoardLayout;
  setBoard: (projectId: string, layout: BoardLayout) => void;
  resetDemo: () => void;
}

const WorkspaceContext = createContext<WorkspaceValue | null>(null);

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [projects, setProjects] = useState<Project[]>(SEED_PROJECTS);
  const [proposals, setProposals] = useState<ChangeProposal[]>(SEED_PROPOSALS);
  const [runs] = useState<RunRecord[]>(SEED_RUNS);
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [recentIds, setRecentIds] = useState<string[]>([]);
  const [boards, setBoards] = useState<Record<string, BoardLayout>>({});
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    setProjects(load(PROJECTS_KEY, SEED_PROJECTS));
    setProposals(load(PROPOSALS_KEY, SEED_PROPOSALS));
    setBoards(load(BOARD_KEY, {}));
    setActiveProjectId(load(ACTIVE_KEY, null));
    setRecentIds(load(RECENT_KEY, []));
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    save(PROJECTS_KEY, projects);
  }, [projects, hydrated]);
  useEffect(() => {
    if (!hydrated) return;
    save(PROPOSALS_KEY, proposals);
  }, [proposals, hydrated]);
  useEffect(() => {
    if (!hydrated) return;
    save(BOARD_KEY, boards);
  }, [boards, hydrated]);
  useEffect(() => {
    if (!hydrated) return;
    save(ACTIVE_KEY, activeProjectId);
  }, [activeProjectId, hydrated]);
  useEffect(() => {
    if (!hydrated) return;
    save(RECENT_KEY, recentIds);
  }, [recentIds, hydrated]);

  const setActiveProject = useCallback((id: string | null) => {
    setActiveProjectId(id);
    if (id) {
      setRecentIds((prev) => [id, ...prev.filter((x) => x !== id)].slice(0, 5));
    }
  }, []);

  const createProject = useCallback((input: { name: string; objective: string; repoUrl: string; branch: string }) => {
    const project: Project = {
      id: `proj-${Date.now().toString(36)}`,
      name: input.name.trim(),
      objective: input.objective.trim() || "Stage a constraint-aware deployment.",
      repo: input.repoUrl.trim()
        ? { url: input.repoUrl.trim(), branch: input.branch.trim() || "main", autoDetected: false }
        : null,
      scenarioKey: "empty-workspace",
      status: "never_run",
      lastActivity: new Date().toISOString().slice(0, 16).replace("T", " "),
      latestRunId: null,
      executionMode: "simulator",
      createdAt: new Date().toISOString().slice(0, 16).replace("T", " "),
    };
    setProjects((prev) => [project, ...prev]);
    setActiveProjectId(project.id);
    setRecentIds((prev) => [project.id, ...prev].slice(0, 5));
    return project;
  }, []);

  const deleteProject = useCallback((id: string) => {
    setProjects((prev) => prev.filter((p) => p.id !== id));
    setProposals((prev) => prev.filter((p) => p.projectId !== id));
    setActiveProjectId((prev) => (prev === id ? null : prev));
  }, []);

  const updateProject = useCallback((id: string, patch: Partial<Project>) => {
    setProjects((prev) => prev.map((p) => (p.id === id ? { ...p, ...patch } : p)));
  }, []);

  const proposalsFor = useCallback((projectId: string) => proposals.filter((p) => p.projectId === projectId), [proposals]);
  const runsFor = useCallback((projectId: string) => runs.filter((r) => r.projectId === projectId), [runs]);

  const reviewProposal = useCallback((proposalId: string, action: "approve" | "reject" | "request_changes", note?: string) => {
    let result: { ok: boolean; message: string } = { ok: false, message: "Proposal not found." };
    setProposals((prev) =>
      prev.map((p) => {
        if (p.id !== proposalId) return p;
        if (action === "approve") {
          const gate = isProposalApprovable(p);
          if (!gate.ok) {
            result = { ok: false, message: gate.reason ?? "Approval blocked." };
            return p;
          }
          result = { ok: true, message: `Approved revision ${p.sourceRevision}. Demo approval only — no real deployment was triggered.` };
          return {
            ...p, state: "approved" as const,
            history: [...p.history, { at: new Date().toISOString().slice(0, 16).replace("T", " "), actor: "reviewer (demo)", action: `Approved revision ${p.sourceRevision}${note ? ` — ${note}` : ""}` }],
          };
        }
        if (action === "reject") {
          if (p.stale) {
            result = { ok: false, message: "Already superseded — nothing to reject." };
            return p;
          }
          result = { ok: true, message: `Rejected revision ${p.sourceRevision}. The proposal stays inspectable.` };
          return {
            ...p, state: "rejected" as const,
            history: [...p.history, { at: new Date().toISOString().slice(0, 16).replace("T", " "), actor: "reviewer (demo)", action: `Rejected${note ? ` — ${note}` : ""}` }],
          };
        }
        result = { ok: true, message: "Changes requested. The proposal is marked needs-analysis; re-analysis is required before approval." };
        return {
          ...p, state: "changes_requested" as const,
          history: [...p.history, { at: new Date().toISOString().slice(0, 16).replace("T", " "), actor: "reviewer (demo)", action: `Requested changes${note ? ` — ${note}` : ""}` }],
        };
      }),
    );
    return result;
  }, []);

  const boardFor = useCallback((projectId: string) => boards[projectId] ?? DEFAULT_BOARD_LAYOUT, [boards]);
  const setBoard = useCallback((projectId: string, layout: BoardLayout) => {
    setBoards((prev) => ({ ...prev, [projectId]: layout }));
  }, []);

  const resetDemo = useCallback(() => {
    setProjects(SEED_PROJECTS);
    setProposals(SEED_PROPOSALS);
    setBoards({});
    setActiveProjectId(null);
    setRecentIds([]);
    try {
      window.localStorage.removeItem(PROJECTS_KEY);
      window.localStorage.removeItem(PROPOSALS_KEY);
      window.localStorage.removeItem(BOARD_KEY);
      window.localStorage.removeItem(ACTIVE_KEY);
      window.localStorage.removeItem(RECENT_KEY);
    } catch { /* noop */ }
  }, []);

  const value = useMemo<WorkspaceValue>(() => ({
    projects, proposals, runs, activeProjectId, recentIds, boards,
    setActiveProject, createProject, deleteProject, updateProject,
    proposalsFor, runsFor, reviewProposal, boardFor, setBoard, resetDemo,
  }), [projects, proposals, runs, activeProjectId, recentIds, boards, setActiveProject, createProject, deleteProject, updateProject, proposalsFor, runsFor, reviewProposal, boardFor, setBoard, resetDemo]);

  return <WorkspaceContext.Provider value={value}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  const ctx = useContext(WorkspaceContext);
  if (!ctx) throw new Error("useWorkspace must be used within WorkspaceProvider");
  return ctx;
}
