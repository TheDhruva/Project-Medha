"use client";
import { use } from "react";
import { ProjectRunDetail } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string; runId: string }> }) {
  const { id, runId } = use(params);
  return <ProjectRunDetail projectId={id} runId={runId} />;
}
