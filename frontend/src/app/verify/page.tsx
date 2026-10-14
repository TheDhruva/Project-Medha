import { Suspense } from "react";
import { StartVerificationFlow } from "@/components/verify/StartVerificationFlow";

export default function VerifyPage() {
  // useSearchParams (project-locked mode) requires a Suspense boundary.
  return (
    <Suspense fallback={null}>
      <StartVerificationFlow />
    </Suspense>
  );
}
