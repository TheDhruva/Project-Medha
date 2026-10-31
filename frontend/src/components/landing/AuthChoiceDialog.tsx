"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { ArrowRight, Loader2 } from "lucide-react";
import { createGuestSession } from "@/lib/guest/session";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]), [tabindex]:not([tabindex="-1"])';

/**
 * Authentication choice shown when a signed-out visitor presses Start.
 *
 * Sign in hands off to the existing Clerk flow untouched. Continue as guest
 * asks the backend for a real session before navigating — the UI never
 * pretends a guest exists until the server has issued one.
 *
 * Accessible: labelled modal dialog, focus moves to the first option on open
 * and back to the trigger on close, Escape and backdrop both close, Tab is
 * trapped inside.
 */
export function AuthChoiceDialog({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dialogRef = useRef<HTMLDivElement>(null);
  const contentRef = useRef<HTMLDivElement>(null);
  const submitting = useRef(false);
  const restoreRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    restoreRef.current = document.activeElement as HTMLElement | null;
    const first = contentRef.current?.querySelector<HTMLElement>(FOCUSABLE);
    first?.focus();
    return () => {
      restoreRef.current?.focus?.();
    };
  }, []);

  useEffect(() => {
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.stopPropagation();
        onClose();
        return;
      }
      if (event.key !== "Tab") return;
      const nodes = dialogRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE);
      if (!nodes || nodes.length === 0) return;
      const list = Array.from(nodes);
      const first = list[0];
      const last = list[list.length - 1];
      const active = document.activeElement;
      if (event.shiftKey && active === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && active === last) {
        event.preventDefault();
        first?.focus();
      }
    }
    document.addEventListener("keydown", onKey, true);
    return () => document.removeEventListener("keydown", onKey, true);
  }, [onClose]);

  async function continueAsGuest() {
    if (busy || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    setError(null);
    try {
      await createGuestSession();
      router.push("/projects");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start a guest session.");
      submitting.current = false;
      setBusy(false);
    }
  }

  return (
    <div
      ref={dialogRef}
      className="fixed inset-0 z-50 flex items-center justify-center p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="medha-auth-choice-title"
      aria-describedby="medha-auth-choice-body"
    >
      <button
        type="button"
        aria-label="Close"
        onClick={onClose}
        className="absolute inset-0 cursor-default"
        style={{ backgroundColor: "rgba(15, 23, 42, 0.35)" }}
      />
      <div ref={contentRef} className="lp-panel relative w-full max-w-xl rounded-[10px] p-5">
        <h2 id="medha-auth-choice-title" className="text-[17px] font-semibold lp-text">
          Welcome to MEDHA
        </h2>
        <p id="medha-auth-choice-body" className="mt-1 text-[13.5px] lp-secondary">
          Choose how you want to continue.
        </p>

        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-2">
          <div className="flex flex-col rounded-[8px] border p-3.5 lp-border">
            <h3 className="text-[13.5px] font-semibold lp-text">Sign in</h3>
            <p className="mt-1 flex-1 text-[12.5px] leading-relaxed lp-secondary">
              Access your saved projects and deployment history.
            </p>
            <Link
              href="/sign-in"
              onClick={onClose}
              className="lp-btn lp-btn-secondary mt-3 justify-center"
            >
              Continue with sign in <ArrowRight className="h-4 w-4" aria-hidden />
            </Link>
          </div>

          <div className="flex flex-col rounded-[8px] border p-3.5 lp-border">
            <h3 className="text-[13.5px] font-semibold lp-text">Continue as guest</h3>
            <p className="mt-1 flex-1 text-[12.5px] leading-relaxed lp-secondary">
              Use MEDHA with its available functionality. Your data will be temporary.
            </p>
            <button
              type="button"
              onClick={continueAsGuest}
              disabled={busy}
              aria-busy={busy}
              className="lp-btn lp-btn-primary mt-3 justify-center disabled:cursor-not-allowed disabled:opacity-60"
            >
              {busy ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> Starting…
                </>
              ) : (
                <>
                  Continue as guest <ArrowRight className="h-4 w-4" aria-hidden />
                </>
              )}
            </button>
          </div>
        </div>

        <p className="mt-3 border-t pt-3 text-[12px] lp-border lp-tertiary">
          Your data is deleted when you leave MEDHA.
        </p>

        {error ? (
          <p role="alert" className="mt-2 text-[12.5px] font-medium" style={{ color: "#B42318" }}>
            {error}
          </p>
        ) : null}
      </div>
    </div>
  );
}
