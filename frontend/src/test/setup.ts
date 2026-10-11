import "@testing-library/jest-dom/vitest";
import React from "react";
import { vi } from "vitest";

/**
 * Clerk is an external identity provider: unit tests must not depend on it.
 * Mock @clerk/nextjs so components render deterministically in the
 * signed-out state (Sign in / Sign up buttons visible, UserButton hidden).
 * Note: plain .ts (no JSX) — use React.createElement.
 */
vi.mock("@clerk/nextjs", () => ({
  ClerkProvider: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
  Show: ({ when, children }: { when: string; children: React.ReactNode }) =>
    when === "signed-out" ? React.createElement(React.Fragment, null, children) : null,
  SignInButton: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
  SignUpButton: ({ children }: { children: React.ReactNode }) =>
    React.createElement(React.Fragment, null, children),
  UserButton: () => React.createElement("span", { "data-testid": "clerk-user-button" }),
  SignIn: () => null,
  SignUp: () => null,
}));
