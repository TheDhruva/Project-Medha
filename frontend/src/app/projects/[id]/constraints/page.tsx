"use client";
import { use } from "react";
import { ConstraintsView } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ConstraintsView projectId={id} />;
}
