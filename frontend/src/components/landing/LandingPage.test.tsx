import { render, screen, fireEvent, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { LandingPage } from "./LandingPage";

const pushMock = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: pushMock }),
}));

vi.mock("@/lib/guest/session", () => ({
  createGuestSession: vi.fn(),
  getGuestToken: vi.fn(() => null),
  setGuestToken: vi.fn(),
  clearGuestToken: vi.fn(),
  verifyGuestSession: vi.fn(async () => false),
  endGuestSession: vi.fn(async () => true),
}));

describe("LandingPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("shows a quiet header with the wordmark and the existing Sign in flow", () => {
    render(<LandingPage signedIn={false} />);
    const banner = screen.getByRole("banner");
    expect(within(banner).getByText("MEDHA")).toBeInTheDocument();
    expect(within(banner).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(screen.queryByRole("link", { name: "Project Hub" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Run History" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Settings" })).toBeNull();
  });

  it("renders the exact headline and a single Start action", () => {
    render(<LandingPage signedIn={false} />);
    expect(
      screen.getByRole("heading", { level: 1, name: /Your code\.\s*Ready to deploy\./ }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: /Start/ })).toHaveLength(1);
  });

  it("keeps one short supporting sentence", () => {
    render(<LandingPage signedIn={false} />);
    expect(screen.getByText("MEDHA plans, checks, and deploys your code.")).toBeInTheDocument();
  });

  it("drops the old hero eyebrow, paragraphs and badges", () => {
    render(<LandingPage signedIn={false} />);
    expect(screen.queryByText(/Infrastructure that reasons before it deploys/)).toBeNull();
    expect(screen.queryByText(/Constraint-aware DevOps automation/)).toBeNull();
    expect(screen.queryByText(/local-first · evidence-traced/)).toBeNull();
    expect(screen.queryByText(/MEDHA coordinates specialized agents/)).toBeNull();
    expect(screen.queryByText("Illustrative")).toBeNull();
    expect(screen.queryByText(/No registration needed to explore/)).toBeNull();
  });

  it("renders one cohesive repository-to-deployment board", () => {
    render(<LandingPage signedIn={false} />);
    const canvas = screen.getByLabelText("Repository to deployment (conceptual)");
    const diagram = within(canvas);

    // Repository surface.
    for (const label of ["src/", "index.ts", "server.ts", "package.json", "Dockerfile", "main", "4 files"]) {
      expect(diagram.getByText(label)).toBeInTheDocument();
    }
    // Orchestration: one MEDHA node coordinating three concerns.
    expect(diagram.getByText("MEDHA")).toBeInTheDocument();
    expect(diagram.getByText("Orchestrator")).toBeInTheDocument();
    for (const label of ["Build", "Network"]) {
      expect(diagram.getByText(label)).toBeInTheDocument();
    }
    expect(diagram.getAllByText("Security")).toHaveLength(2);
    // Verification follows orchestration, then the deployment destination.
    for (const label of ["Checks", "Configuration", "Services", "Deployment plan"]) {
      expect(diagram.getByText(label)).toBeInTheDocument();
    }
    expect(diagram.getByText("Deploy")).toBeInTheDocument();
    expect(diagram.getByText("Local Docker host")).toBeInTheDocument();
    // The deployment destination is not presented as localhost.
    expect(screen.queryByText(/localhost/i)).toBeNull();

    // The four separate pipeline cards and the old five-node diagram are gone.
    for (const title of [
      "Understand your code",
      "Make a plan",
      "Check before launch",
      "Deploy & recover",
      "Repository & Constraints",
      "MEDHA Orchestrator",
      "Verification",
      "Execution & Recovery",
    ]) {
      expect(screen.queryByText(title)).toBeNull();
    }
    // The illustration is a tinted composition surface, not one large white card.
    expect(canvas.querySelector(".lp-panel")).toBeNull();
    // The diagram must not claim real checks have passed.
    expect(screen.queryByText(/passed|success/i)).toBeNull();
  });

  it("has no footer and no decorative workflow copy", () => {
    render(<LandingPage signedIn={false} />);
    expect(screen.queryByRole("contentinfo")).toBeNull();
    expect(screen.queryByText(/local-first/i)).toBeNull();
    expect(screen.queryByText(/evidence-traced/i)).toBeNull();
    expect(screen.queryByText(/Analyze.*Plan.*Verify.*Deploy/)).toBeNull();
    // Header is the wordmark plus Sign in only.
    const banner = screen.getByRole("banner");
    expect(within(banner).queryByRole("link", { name: /Project Hub/i })).toBeNull();
  });

  it("opens the authentication dialog from Start when signed out", () => {
    render(<LandingPage signedIn={false} />);
    expect(screen.queryByRole("dialog")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Start MEDHA" }));
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(pushMock).not.toHaveBeenCalled();
  });

  it("goes straight to the project hub when signed in", () => {
    render(<LandingPage signedIn={true} />);
    fireEvent.click(screen.getByRole("button", { name: "Start MEDHA" }));
    expect(pushMock).toHaveBeenCalledWith("/projects");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
