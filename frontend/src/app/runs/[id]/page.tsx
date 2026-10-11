import { RunDetailView } from "@/components/run/RunDetailNew";

export default async function RunDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  return <RunDetailView deploymentId={id} />;
}