import { ClerkProvider } from "@clerk/nextjs";
import type { Metadata } from "next";
import "./globals.css";
import { WorkspaceProvider } from "@/lib/workspace/store";
import { ClerkTokenSync } from "@/components/auth/ClerkTokenSync";
import { PerfInit } from "@/lib/perf/PerfInit";

export const metadata: Metadata = {
  title: "MEDHA — Constraint-Negotiating DevOps Orchestration",
  description:
    "Constraint-Negotiating Multi-Agent Architecture for Verifiable DevOps Automation",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  // No Clerk keys in this environment (e.g. Render build without dashboard
  // secrets): render without auth so `next build` and guest demo still work.
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return (
      <html lang="en">
        <body className="font-sans antialiased">
          <PerfInit />
          <WorkspaceProvider>{children}</WorkspaceProvider>
        </body>
      </html>
    );
  }
  return (
    <html lang="en">
      <body className="font-sans antialiased">
        <ClerkProvider>
          <ClerkTokenSync />
          <PerfInit />
          <WorkspaceProvider>{children}</WorkspaceProvider>
        </ClerkProvider>
      </body>
    </html>
  );
}