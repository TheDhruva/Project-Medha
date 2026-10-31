import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AuthChoiceDialog } from "./AuthChoiceDialog";
import { createGuestSession } from "@/lib/guest/session";

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

describe("AuthChoiceDialog", () => {
  const onClose = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("is a labelled modal dialog with the required copy", () => {
    render(<AuthChoiceDialog onClose={onClose} />);
    const dialog = screen.getByRole("dialog");
    expect(dialog).toHaveAttribute("aria-modal", "true");
    expect(screen.getByRole("heading", { name: "Welcome to MEDHA" })).toBeInTheDocument();
    expect(screen.getByText("Choose how you want to continue.")).toBeInTheDocument();
    expect(
      screen.getByText("Access your saved projects and deployment history."),
    ).toBeInTheDocument();
    expect(
      screen.getByText(
        "Use MEDHA with its available functionality. Your data will be temporary.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByText("Your data is deleted when you leave MEDHA.")).toBeInTheDocument();
  });

  it("offers exactly two options, Sign in and Continue as guest", () => {
    render(<AuthChoiceDialog onClose={onClose} />);
    expect(screen.getByRole("link", { name: /Continue with sign in/ })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    expect(screen.getByRole("button", { name: /Continue as guest/ })).toBeInTheDocument();
    // No third option and no fake auth: Sign in stays a plain link.
    expect(screen.getAllByRole("button").filter((b) => !b.hasAttribute("aria-label"))).toHaveLength(1);
  });

  it("moves focus into the dialog on open and restores it on close", () => {
    const trigger = document.createElement("button");
    trigger.textContent = "Start";
    document.body.appendChild(trigger);
    trigger.focus();

    const { unmount } = render(<AuthChoiceDialog onClose={onClose} />);
    expect(document.activeElement).toBe(
      screen.getByRole("link", { name: /Continue with sign in/ }),
    );

    unmount();
    expect(document.activeElement).toBe(trigger);
    trigger.remove();
  });

  it("closes on Escape and on backdrop click", () => {
    render(<AuthChoiceDialog onClose={onClose} />);
    fireEvent.keyDown(document, { key: "Escape" });
    expect(onClose).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("creates a guest session on the backend before navigating", async () => {
    vi.mocked(createGuestSession).mockResolvedValue({
      token: "medha_guest_x",
      session_id: "gs_1",
      subject: "guest:gs_1",
      expires_at: "2030-01-01T00:00:00Z",
      mode: "guest",
    });
    render(<AuthChoiceDialog onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /Continue as guest/ }));

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/projects"));
    expect(createGuestSession).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
  });

  it("surfaces a backend failure and does not navigate", async () => {
    vi.mocked(createGuestSession).mockRejectedValue(
      new Error("Too many guest sessions; retry later."),
    );
    render(<AuthChoiceDialog onClose={onClose} />);

    fireEvent.click(screen.getByRole("button", { name: /Continue as guest/ }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Too many guest sessions; retry later.",
      ),
    );
    expect(pushMock).not.toHaveBeenCalled();
    // The option becomes usable again after a failure.
    expect(screen.getByRole("button", { name: /Continue as guest/ })).toBeEnabled();
  });

  it("ignores duplicate submits while a session is being created", async () => {
    let resolve!: (value: Awaited<ReturnType<typeof createGuestSession>>) => void;
    vi.mocked(createGuestSession).mockReturnValue(
      new Promise((r) => {
        resolve = r;
      }),
    );
    render(<AuthChoiceDialog onClose={onClose} />);

    const button = screen.getByRole("button", { name: /Continue as guest/ });
    fireEvent.click(button);
    fireEvent.click(button);
    fireEvent.click(button);
    expect(createGuestSession).toHaveBeenCalledTimes(1);
    expect(button).toHaveAttribute("aria-busy", "true");
    expect(button).toBeDisabled();

    resolve({
      token: "medha_guest_x",
      session_id: "gs_1",
      subject: "guest:gs_1",
      expires_at: "2030-01-01T00:00:00Z",
      mode: "guest",
    });
    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/projects"));
  });

  it("traps Tab inside the dialog", () => {
    render(<AuthChoiceDialog onClose={onClose} />);
    const focusables = screen
      .getByRole("dialog")
      .querySelectorAll<HTMLElement>('a[href], button:not([disabled])');
    const first = focusables[0];
    const last = focusables[focusables.length - 1];
    expect(focusables.length).toBeGreaterThan(2);

    last.focus();
    expect(document.activeElement).toBe(last);
    fireEvent.keyDown(document, { key: "Tab" });
    expect(document.activeElement).toBe(first);

    first.focus();
    expect(document.activeElement).toBe(first);
    fireEvent.keyDown(document, { key: "Tab", shiftKey: true });
    expect(document.activeElement).toBe(last);
  });
});
