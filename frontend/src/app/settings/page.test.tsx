import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import SettingsPage from "./page";
import * as apiClient from "@/lib/api/client";

vi.mock("next/navigation", () => ({
  usePathname: () => "/settings",
  useParams: () => ({}),
  useRouter: () => ({ push: vi.fn() }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof apiClient>();
  return {
    ...actual,
    checkBackendHealth: vi.fn(),
    fetchAiStatus: vi.fn(),
    fetchConfigStatus: vi.fn(),
    getApiBaseUrl: vi.fn(() => "http://localhost:8000"),
  };
});

describe("SettingsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    window.localStorage.clear();

    vi.mocked(apiClient.checkBackendHealth).mockResolvedValue(true);
    vi.mocked(apiClient.fetchAiStatus).mockResolvedValue({
      enabled: true,
      primary_provider: "groq",
      fallback_provider: "gemini",
      primary_model: "llama-3.3-70b-versatile",
      fallback_model: "gemini-2.0-flash",
      max_calls_per_run: 5,
      request_timeout_seconds: 30,
      max_output_tokens: 1500,
      health: {
        enabled: true,
        primary: "groq",
        fallback: "gemini",
        providers: {
          groq: { configured: true, reachable: true, error: null },
          gemini: { configured: true, reachable: true, error: null },
        },
      },
    });
    vi.mocked(apiClient.fetchConfigStatus).mockResolvedValue({
      env: "development",
      auth_mode: "off",
      executor_mode: "docker",
      docker_execute: true,
      demo_enabled: false,
      configured: {},
      github_app_configured: false,
      docker_cli: true,
      docker_daemon: true,
      database_mode: "sqlite",
      execution: "ready",
      execution_reason: "docker_available",
      execution_readiness: {
        status: "ready",
        mode: "docker",
        reason_code: "READY",
        message: "Docker daemon is running and execution is ready.",
        simulated: false,
        requires_operator: false,
        restart_required: false,
        next_actions: [],
      },
      production_ready: true,
    });
  });

  it("renders page title 'Settings' and the 5 clear sections without architecture clutter", async () => {
    render(<SettingsPage />);

    expect(screen.getByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();

    // The 5 sections
    expect(screen.getByRole("heading", { level: 2, name: "General" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Connections" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "AI Providers" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Execution" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { level: 2, name: "Appearance & Accessibility" })).toBeInTheDocument();

    // Clutter must be removed
    expect(screen.queryByText(/Architecture principles/i)).toBeNull();
    expect(screen.queryByText(/DEMO \/ MOCK \(removed\)/i)).toBeNull();
    expect(screen.queryByText(/CIG \(change impact\) and CEG/i)).toBeNull();
  });

  it("displays actionable diagnostics and handles connection checking", async () => {
    render(<SettingsPage />);

    await waitFor(() => {
      expect(screen.getByText("Connected")).toBeInTheDocument();
      expect(screen.getByText("Docker Execution")).toBeInTheDocument();
      expect(screen.getByText("Ready")).toBeInTheDocument();
    });

    const checkBtn = screen.getByRole("button", { name: "Check connection" });
    fireEvent.click(checkBtn);

    expect(apiClient.checkBackendHealth).toHaveBeenCalled();
  });

  it("toggles reduce motion and saves preference to localStorage", async () => {
    render(<SettingsPage />);

    const switchBtn = screen.getByRole("switch", { name: "Reduce motion" });
    expect(switchBtn).toHaveAttribute("aria-checked", "false");

    fireEvent.click(switchBtn);
    expect(switchBtn).toHaveAttribute("aria-checked", "true");
    expect(window.localStorage.getItem("medha.prefs.reduceMotion.v1")).toBe("1");

    fireEvent.click(switchBtn);
    expect(switchBtn).toHaveAttribute("aria-checked", "false");
    expect(window.localStorage.getItem("medha.prefs.reduceMotion.v1")).toBe("0");
  });
});

