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