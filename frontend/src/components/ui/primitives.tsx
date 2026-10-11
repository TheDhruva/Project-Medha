"use client";

import Link from "next/link";
import { useEffect, useRef, type ReactNode } from "react";
import { Loader2 } from "lucide-react";
import { cn } from "@/lib/ui/cn";

/* ---------- Buttons ---------- */

type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "danger" | "ghost";
  loading?: boolean;
};

export function Button({ variant = "secondary", loading, className, children, disabled, ...rest }: ButtonProps) {
  const cls =
    variant === "primary"
      ? "bg-medha-accent text-white hover:bg-medha-accent-hover"
      : variant === "danger"
        ? "bg-medha-danger text-white hover:brightness-95"
        : variant === "ghost"
          ? "bg-transparent text-medha-secondary hover:bg-medha-muted hover:text-medha-text"
          : "border border-medha-border bg-white text-medha-text hover:bg-medha-muted/60";
  return (
    <button
      type="button"
      disabled={disabled || loading}
      aria-busy={loading || undefined}
      className={cn(
        "inline-flex items-center justify-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent disabled:cursor-not-allowed disabled:opacity-60",
        cls,
        className,
      )}
      {...rest}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
      {children}
    </button>
  );
}

export function ActionLink({ href, primary, children }: { href: string; primary?: boolean; children: ReactNode }) {
  return (
    <Link
      href={href}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-lg px-4 py-2 text-sm font-semibold transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-medha-accent",
        primary
          ? "bg-medha-accent text-white hover:bg-medha-accent-hover"
          : "border border-medha-border bg-white text-medha-text hover:bg-medha-muted/60",
      )}
    >
      {children}
    </Link>
  );
}

/* ---------- Panels & headers ---------- */

export function Panel({ title, eyebrow, description, action, children, className, id }: {
  title: string;
  eyebrow?: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} aria-label={title} className={cn("medha-panel p-4 sm:p-5", className)}>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          {eyebrow ? <p className="medha-label">{eyebrow}</p> : null}
          <h2 className="mt-1 text-[16px] font-semibold tracking-tight text-medha-text">{title}</h2>
          {description ? <p className="mt-1 max-w-2xl text-sm leading-relaxed text-medha-secondary">{description}</p> : null}
        </div>
        {action ? <div className="flex shrink-0 flex-wrap items-center gap-2">{action}</div> : null}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions, breadcrumbs }: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  breadcrumbs?: ReactNode;
}) {
  return (
    <div className="space-y-2">
      {breadcrumbs}
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[28px] font-bold leading-tight tracking-tight text-medha-text">{title}</h1>
          {subtitle ? <p className="mt-1 max-w-3xl text-[15px] leading-relaxed text-medha-secondary">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div> : null}
      </div>
    </div>
  );
}

export function Breadcrumbs({ items }: { items: { label: string; href?: string }[] }) {
  return (
    <nav aria-label="Breadcrumb">
      <ol className="flex flex-wrap items-center gap-1.5 text-[13px] text-medha-secondary">
        {items.map((item, i) => (
          <li key={`${item.label}-${i}`} className="flex items-center gap-1.5">
            {i > 0 ? <span aria-hidden className="text-medha-border-strong">/</span> : null}
            {item.href ? (
              <Link href={item.href} className="rounded hover:text-medha-text hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent">
                {item.label}
              </Link>
            ) : (
              <span aria-current="page" className="font-medium text-medha-text">{item.label}</span>
            )}
          </li>
        ))}
      </ol>
    </nav>
  );
}

/* ---------- Badges / status ---------- */

export function Badge({ tone = "neutral", children }: { tone?: "success" | "warning" | "error" | "info" | "neutral"; children: ReactNode }) {
  const cls =
    tone === "success" ? "border-medha-success/30 bg-medha-success-soft text-medha-success"
    : tone === "warning" ? "border-medha-warning/30 bg-medha-warning-soft text-medha-warning"
    : tone === "error" ? "border-medha-danger/30 bg-medha-danger-soft text-medha-danger"
    : tone === "info" ? "border-medha-run/25 bg-medha-run-soft text-medha-run-ink"
    : "border-medha-border bg-medha-muted text-medha-secondary";
  return (
    <span className={cn("inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[12px] font-semibold", cls)}>
      {children}
    </span>
  );
}

export function DemoBadge({ isDemo = true }: { isDemo?: boolean }) {
  return <Badge tone={isDemo ? "neutral" : "info"}>{isDemo ? "DEMO · SIMULATED" : "LIVE · LOCAL"}</Badge>;
}

/* ---------- Tabs ---------- */

export function Tabs<T extends string>({ tabs, active, onChange, label }: {
  tabs: { id: T; label: string }[];
  active: T;
  onChange: (id: T) => void;
  label: string;
}) {
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 rounded-xl border border-medha-border bg-white p-1">
      {tabs.map((t) => (
        <button
          key={t.id}
          role="tab"
          aria-selected={active === t.id}
          type="button"
          onClick={() => onChange(t.id)}
          className={cn(
            "rounded-lg px-3 py-1.5 text-[13px] font-medium transition focus-visible:outline focus-visible:outline-2 focus-visible:outline-medha-accent",
            active === t.id ? "bg-medha-text text-white" : "text-medha-secondary hover:bg-medha-muted hover:text-medha-text",
          )}
        >
          {t.label}
        </button>
      ))}
    </div>
  );
}

/* ---------- Empty / loading / error ---------- */

export function EmptyState({ title, body, action }: { title: string; body: string; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-medha-border bg-white px-6 py-10 text-center">
      <p className="text-[15px] font-semibold text-medha-text">{title}</p>
      <p className="mt-1 max-w-md text-sm leading-relaxed text-medha-secondary">{body}</p>
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("animate-pulse rounded-lg bg-medha-muted", className ?? "h-16 w-full")} />;
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div role="alert" className="rounded-xl border border-medha-danger/30 bg-medha-danger-soft p-4 text-sm text-medha-danger">
      <p className="font-semibold">Something went wrong.</p>
      <p className="mt-1">{message}</p>
      {onRetry ? (
        <button type="button" onClick={onRetry} className="mt-3 rounded-lg border border-medha-danger/30 bg-white px-3 py-1.5 text-xs font-semibold hover:bg-white/70">
          Retry
        </button>
      ) : null}
    </div>
  );
}

/* ---------- Stat ---------- */

export function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-medha-border bg-white px-4 py-3">
      <p className="medha-label">{label}</p>
      <p className="mt-1 text-[28px] font-bold leading-none tracking-tight text-medha-text">{value}</p>
      {hint ? <p className="mt-1 text-[13px] text-medha-secondary">{hint}</p> : null}
    </div>
  );
}

/* ---------- Dialog ---------- */

export function Dialog({ title, body, confirmLabel, cancelLabel = "Cancel", onConfirm, onCancel, danger }: {
  title: string;
  body: ReactNode;
  confirmLabel: string;
  cancelLabel?: string;
  onConfirm: () => void;
  onCancel: () => void;
  danger?: boolean;
}) {
  const confirmRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    confirmRef.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onCancel();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onCancel]);
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" role="dialog" aria-modal="true" aria-label={title}>
      <div className="absolute inset-0 bg-medha-text/30" onClick={onCancel} aria-hidden />
      <div className="relative w-full max-w-md rounded-xl border border-medha-border bg-white p-5 shadow-medha">
        <h2 className="text-[16px] font-semibold text-medha-text">{title}</h2>
        <div className="mt-2 text-sm leading-relaxed text-medha-secondary">{body}</div>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel}>{cancelLabel}</Button>
          <button
            ref={confirmRef}
            type="button"
            onClick={onConfirm}
            className={cn(
              "rounded-lg px-4 py-2 text-sm font-semibold text-white",
              danger ? "bg-medha-danger" : "bg-medha-accent hover:bg-medha-accent-hover",
            )}
          >
            {confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ---------- Accessible graph fallback list ---------- */

export function GraphListFallback({ title, items }: { title: string; items: { id: string; label: string; detail?: string }[] }) {
  return (
    <details className="mt-3 rounded-lg border border-medha-border bg-white">
      <summary className="cursor-pointer px-3 py-2 text-[13px] font-medium text-medha-secondary hover:text-medha-text">
        {title} — list view ({items.length})
      </summary>
      <ul className="divide-y divide-medha-border border-t border-medha-border">
        {items.map((item) => (
          <li key={item.id} className="px-3 py-2">
            <p className="medha-mono text-[12px] font-medium text-medha-text">{item.label}</p>
            {item.detail ? <p className="mt-0.5 text-[12px] text-medha-secondary">{item.detail}</p> : null}
          </li>
        ))}
      </ul>
    </details>
  );
}
