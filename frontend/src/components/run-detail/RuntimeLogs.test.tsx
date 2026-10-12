import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RuntimeLogsPanel } from "@/components/run-detail/RuntimeLogs";
import { ExecutionModeBadge } from "@/components/ui/Section";

describe("RuntimeLogsPanel", () => {
  it("renders real stdout and stderr verbatim", () => {
    render(
      <RuntimeLogsPanel
        executionMode="real"
        runtimeLogs={{
          available: true,
          container: "medha_abc_app-python",
          stdout: "Uvicorn running on :8080",
          stderr: "WARNING: no access log",
        }}
      />,
    );
    expect(screen.getByRole("heading", { name: "Application container output" }))
      .toBeInTheDocument();
    expect(screen.getByText("Uvicorn running on :8080")).toBeInTheDocument();
    expect(screen.getByText("WARNING: no access log")).toBeInTheDocument();
    expect(screen.getByText(/medha_abc_app-python/)).toBeInTheDocument();
  });

  it("reports unavailable logs honestly with the backend code", () => {
    render(
      <RuntimeLogsPanel
        executionMode="real"
        runtimeLogs={{ available: false, container: "medha_abc_app", code: "LOGS_UNAVAILABLE" }}
      />,
    );
    expect(screen.getByText("Container logs are unavailable.")).toBeInTheDocument();
    expect(screen.getByText(/LOGS_UNAVAILABLE/)).toBeInTheDocument();
    // SSE replay is never presented as container output.
    expect(screen.getByText(/not container output/)).toBeInTheDocument();
  });

  it("distinguishes an empty container from a missing one", () => {
    render(
      <RuntimeLogsPanel
        executionMode="real"
        runtimeLogs={{ available: true, container: "medha_abc_app", stdout: "", stderr: "" }}
      />,
    );
    expect(screen.getByText(/produced no output yet/)).toBeInTheDocument();
  });

  it("stays hidden for demo runs without runtime logs", () => {
    const { container } = render(
      <RuntimeLogsPanel executionMode="demo" runtimeLogs={null} />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the pending state for real runs before logs arrive", () => {
    render(<RuntimeLogsPanel executionMode="real" runtimeLogs={null} />);
    expect(screen.getByText(/not available for this run yet/)).toBeInTheDocument();
  });
});

describe("ExecutionModeBadge", () => {
  it.each([
    ["demo", "DEMO"],
    ["simulator", "SIMULATED"],
    ["controlled_test", "CONTROLLED TEST"],
    ["real", "REAL"],
  ])("labels %s as %s", (mode, label) => {
    render(<ExecutionModeBadge mode={mode} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  it("renders nothing when the mode is unknown", () => {
    const { container } = render(<ExecutionModeBadge mode={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
