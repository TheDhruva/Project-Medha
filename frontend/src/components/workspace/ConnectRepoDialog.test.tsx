import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { ConnectRepoDialog } from "./ConnectRepoDialog";
import * as apiClient from "@/lib/api/client";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: pushMock,
  }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    createProject: vi.fn(),
    createProjectRun: vi.fn(),
    verifyProject: vi.fn(),
    deleteProject: vi.fn(),
    fetchProjects: vi.fn(),
    validateRepository: vi.fn(),
  };
});

describe("ConnectRepoDialog", () => {
  const onClose = vi.fn();
  const onDone = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders with title 'Connect repository' and single repository input without unnecessary fields", () => {
    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    expect(screen.getByRole("heading", { name: "Connect repository" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Connect repository" })).toBeInTheDocument();
    expect(screen.getByLabelText(/GitHub repository/)).toBeInTheDocument();
    // Display name field must not be present
    expect(screen.queryByLabelText(/Display name/)).toBeNull();
    // No obsolete disclaimers
    expect(screen.queryByText(/Public repositories only in V1/)).toBeNull();
  });

  it("validates input and displays a useful error for invalid repo format", async () => {
    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    const input = screen.getByLabelText(/GitHub repository/);
    fireEvent.change(input, { target: { value: "invalid-name" } });

    const submitBtn = screen.getByRole("button", { name: "Connect repository" });
    fireEvent.click(submitBtn);

    expect(
      await screen.findByText("Enter a GitHub repository as 'owner/name' or a github.com URL."),
    ).toBeInTheDocument();
    expect(apiClient.createProject).not.toHaveBeenCalled();
  });

  it("retrieves branches and allows selecting a branch before connecting", async () => {
    vi.mocked(apiClient.validateRepository).mockResolvedValue({
      repository: "org/demo",
      owner: "org",
      name: "demo",
      canonical_url: "https://github.com/org/demo",
      accessible: true,
      default_branch: "main",
      branches: ["main", "develop", "feature/auth"],
    });

    const mockProj: apiClient.Project = {
      project_id: "prj_new_123",
      name: "demo",
      provider: "github",
      canonical_url: "https://github.com/org/demo",
      repo_owner: "org",
      repo_name: "demo",
      repository: "org/demo",
      branch: "develop",
      visibility: "public",
      connection_status: "connected",
      created_at: "2026-10-29T00:00:00Z",
      updated_at: "2026-10-29T00:00:00Z",
    };
    vi.mocked(apiClient.createProject).mockResolvedValue(mockProj);
    vi.mocked(apiClient.verifyProject).mockResolvedValue({
      project: mockProj,
      reachable: true,
      reason: undefined,
    });
    vi.mocked(apiClient.createProjectRun).mockResolvedValue({
      deployment_id: "dep_run_1",
      status: "running",
      mode: "real",
      is_demo: false,
      project_id: "prj_new_123",
    });

    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    const input = screen.getByLabelText(/GitHub repository/);
    fireEvent.change(input, { target: { value: "org/demo" } });

    // Wait for branch data to appear
    await waitFor(() => {
      expect(screen.getByLabelText(/Branch/)).toBeInTheDocument();
    });

    // Default branch is preselected
    const branchSelect = screen.getByLabelText(/Branch/) as HTMLSelectElement;
    expect(branchSelect.value).toBe("main");

    // Select another branch
    fireEvent.change(branchSelect, { target: { value: "develop" } });
    expect(branchSelect.value).toBe("develop");

    const submitBtn = screen.getByRole("button", { name: "Connect repository" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(apiClient.createProject).toHaveBeenCalledWith({
        repository: "org/demo",
        branch: "develop",
      });
      expect(apiClient.verifyProject).toHaveBeenCalledWith("prj_new_123");
      expect(apiClient.createProjectRun).toHaveBeenCalledWith("prj_new_123", {});
      expect(pushMock).toHaveBeenCalledWith("/projects/prj_new_123/runs/dep_run_1");
      expect(onDone).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });

  it("handles branch retrieval / validation failure with concise error", async () => {
    const errorWithCode = new Error("Repository not found");
    (errorWithCode as any).code = "REPO_NOT_FOUND";
    vi.mocked(apiClient.validateRepository).mockRejectedValue(errorWithCode);

    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    const input = screen.getByLabelText(/GitHub repository/);
    fireEvent.change(input, { target: { value: "org/nonexistent" } });

    await waitFor(() => {
      expect(
        screen.getByText(/Repository not found or private/),
      ).toBeInTheDocument();
    });

    expect(screen.queryByLabelText(/Branch/)).toBeNull();
  });

  it("prevents double submission while connecting", async () => {
    vi.mocked(apiClient.validateRepository).mockResolvedValue({
      repository: "org/demo",
      owner: "org",
      name: "demo",
      canonical_url: "https://github.com/org/demo",
      accessible: true,
      default_branch: "main",
      branches: ["main"],
    });

    let resolveCreate: (value: any) => void = () => {};
    const createPromise = new Promise((resolve) => {
      resolveCreate = resolve;
    });
    vi.mocked(apiClient.createProject).mockReturnValue(createPromise as any);

    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    const input = screen.getByLabelText(/GitHub repository/);
    fireEvent.change(input, { target: { value: "org/demo" } });

    await waitFor(() => {
      expect(screen.getByLabelText(/Branch/)).toBeInTheDocument();
    });

    const submitBtn = screen.getByRole("button", { name: "Connect repository" });
    fireEvent.click(submitBtn);
    fireEvent.click(submitBtn); // double click

    expect(apiClient.createProject).toHaveBeenCalledTimes(1);

    resolveCreate({
      project_id: "prj_new_123",
      name: "demo",
      canonical_url: "https://github.com/org/demo",
      repo_owner: "org",
      repo_name: "demo",
      branch: "main",
      status: "connected",
      created_at: "2026-10-29T00:00:00Z",
    });
  });

  it("handles existing repository (PROJECT_EXISTS) by navigating to the existing project without creating duplicates", async () => {
    vi.mocked(apiClient.validateRepository).mockResolvedValue({
      repository: "org/demo",
      owner: "org",
      name: "demo",
      canonical_url: "https://github.com/org/demo",
      accessible: true,
      default_branch: "main",
      branches: ["main"],
    });

    const errorWithCode = new Error("Repository already connected");
    (errorWithCode as any).code = "PROJECT_EXISTS";
    vi.mocked(apiClient.createProject).mockRejectedValue(errorWithCode);

    vi.mocked(apiClient.fetchProjects).mockResolvedValue({
      projects: [
        {
          project_id: "prj_existing_999",
          name: "demo",
          provider: "github",
          canonical_url: "https://github.com/org/demo",
          repo_owner: "org",
          repo_name: "demo",
          repository: "org/demo",
          branch: "main",
          visibility: "public",
          connection_status: "connected",
          created_at: "2026-10-20T00:00:00Z",
          updated_at: "2026-10-20T00:00:00Z",
        },
      ],
      total: 1,
    });

    render(<ConnectRepoDialog onClose={onClose} onDone={onDone} />);

    const input = screen.getByLabelText(/GitHub repository/);
    fireEvent.change(input, { target: { value: "org/demo" } });

    await waitFor(() => {
      expect(screen.getByLabelText(/Branch/)).toBeInTheDocument();
    });

    const submitBtn = screen.getByRole("button", { name: "Connect repository" });
    fireEvent.click(submitBtn);

    await waitFor(() => {
      expect(pushMock).toHaveBeenCalledWith("/projects/prj_existing_999");
      expect(onDone).toHaveBeenCalled();
      expect(onClose).toHaveBeenCalled();
    });
  });
});
