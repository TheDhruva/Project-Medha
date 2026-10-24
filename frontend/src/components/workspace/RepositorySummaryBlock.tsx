import { Sparkles } from "lucide-react";
import type { RepositorySummary } from "@/lib/api/client";

function shortSha(value: string | null): string | null {
  if (!value) return null;
  return value.length > 12 ? value.slice(0, 7) : value;
}

/* Repository context for the project header: a light, subordinate block
   (no card chrome) so the scorecards and panels stay the primary layer. */
export function RepositorySummaryBlock({
  summary,
  revision,
  stale,
  loading,
  analyzing,
}: {
  summary: RepositorySummary | null;
  revision: string | null;
  stale: boolean;
  loading: boolean;
  analyzing: boolean;
}) {
  const text = summary?.text?.trim() ? summary.text.trim() : null;
  const technologies = summary?.technologies?.filter((t) => typeof t === "string" && t.trim()) ?? [];
  const sha = shortSha(revision);

  return (
    <div
      className="mt-2 max-w-3xl"
      data-testid="repository-summary"
    >
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        <span className="medha-label">
          Repository summary
        </span>
        {text && summary?.source === "ai" ? (
          <span className="inline-flex items-center gap-1 text-[12px] font-medium text-medha-tertiary">
            <Sparkles className="h-3 w-3" aria-hidden />
            AI-assisted
          </span>
        ) : null}
        {text && stale ? (
          <span
            className="text-[12px] font-medium text-medha-warning"
            title="A newer analysis exists or this summary belongs to another revision."
          >
            Earlier revision{sha ? ` ${sha}` : ""}
          </span>
        ) : null}
      </div>
      {text ? (
        <p title={text} className="mt-0.5 line-clamp-2 text-[13px] leading-5 text-medha-secondary">{text}</p>
      ) : loading || analyzing ? (
        <p role="status" className="mt-0.5 text-[13px] text-medha-tertiary">
          Reading repository summary…
        </p>
      ) : (
        <p className="mt-0.5 text-[13px] text-medha-tertiary">Summary unavailable for this revision.</p>
      )}
      {text && technologies.length > 0 ? (
        <p className="mt-0.5 text-[12px] leading-4 text-medha-tertiary">
          {technologies.slice(0, 4).join(" · ")}
        </p>
      ) : null}
    </div>
  );
}
