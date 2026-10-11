"use client";
import { use } from "react";
import { ProjectBoard } from "@/components/workspace/ProjectBoard";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ProjectBoard projectId={id} />;
}
