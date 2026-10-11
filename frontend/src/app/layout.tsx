import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "MEDHA — Bright Mode Console",
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
      <body className="font-sans antialiased">{children}</body>
    </html>
  );
}
