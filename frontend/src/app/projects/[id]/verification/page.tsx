"use client";
import { use } from "react";
import { VerificationView } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <VerificationView projectId={id} />;
}
