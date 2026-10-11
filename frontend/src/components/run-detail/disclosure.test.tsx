import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { CollapsibleShell } from "@/components/run-detail/Cards";
import { ViewModeToggle } from "@/components/explainability/ViewModeToggle";

vi.mock("@/context/DeploymentContext", () => ({
  useDeployment: () => ({ viewMode: "simple", setViewMode: vi.fn() }),
  useOptionalDeployment: () => null,
}));

describe("progressive disclosure", () => {
  it("collapses technical content until expanded", () => {
    render(
      <CollapsibleShell
        eyebrow="Safety verification"
        title="8 / 8 checks passed"
        preview="No blocking issues detected."
        actionLabel="View checks"
      >
        <p>Schema check detail</p>
      </CollapsibleShell>,
    );
    expect(screen.queryByText("Schema check detail")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: /8 \/ 8 checks passed/ }));
    expect(screen.getByText("Schema check detail")).toBeInTheDocument();
  });

  it("renders the Simple / Technical toggle", () => {
    render(<ViewModeToggle />);
    expect(screen.getByRole("group", { name: "Explanation detail" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "simple" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "technical" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });
});
