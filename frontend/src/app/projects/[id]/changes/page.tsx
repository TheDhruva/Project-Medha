"use client";
import { use } from "react";
import { ChangesList } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  return <ChangesList projectId={id} />;
}
