"use client";
import { use } from "react";
import { ProjectRuns } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ProjectRuns projectId={id} />;
}
