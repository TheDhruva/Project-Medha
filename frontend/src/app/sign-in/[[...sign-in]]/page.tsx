import { SignIn } from "@clerk/nextjs";

export default function SignInPage() {
  // Rendered during `next build` prerender, which may run without Clerk keys
  // (dashboard secrets are runtime-only). Show an honest fallback instead of
  // throwing Missing publishableKey at build time.
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
      <SignIn />
    </div>
  );
}
