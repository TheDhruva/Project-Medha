"use client";
import { use } from "react";
import { ProjectEvaluations } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ProjectEvaluations projectId={id} />;
}
