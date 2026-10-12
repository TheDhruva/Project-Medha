import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  // Same keyless-build guard as the sign-in page: honest fallback instead of
  // a prerender crash when Clerk dashboard secrets are not set.
  if (!process.env.NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-muted-foreground">
          Authentication is not configured in this environment.
        </p>
      </div>
    );
  }
  return (
    <div className="flex min-h-screen items-center justify-center">
      <SignUp />
    </div>
  );
}
