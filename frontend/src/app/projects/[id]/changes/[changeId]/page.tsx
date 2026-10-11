"use client";
import { use } from "react";
import { ChangeReview } from "@/components/workspace/ProjectSections";

export default function Page({ params }: { params: Promise<{ id: string; changeId: string }> }) {
  const { id, changeId } = use(params);
  return <ChangeReview projectId={id} proposalId={changeId} />;
}
