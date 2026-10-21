"""Evidence-backed repository summaries.

The summary is advisory: it is generated from the README excerpt and the
inventory already produced for the analyzed revision. AI output is optional;
a deterministic fallback keeps the feature working with AI disabled. Claims
about deployment health, security, production readiness, or quality are
rejected rather than displayed.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from app.core.events import utc_now_iso
from app.models.domain import RepositorySummary, RepositorySummaryView

_MAX_TEXT = 320
_MAX_README_BYTES = 65536
_MAX_AI_CHARS = 400
_MAX_AI_WORDS = 45
_README_NAMES = {"readme.md", "readme.rst", "readme.txt", "readme"}

_CLAIM_RE = re.compile(
    r"\b(?:production[- ]ready|production[- ]grade|battle[- ]tested|"
    r"enterprise[- ]grade|fully secure|secure by default|zero[- ]downtime|"
    r"guaranteed uptime|deployment (?:is )?healthy|"
    r"100% (?:secure|reliable|uptime)|security[- ]verified|"
    r"passes? all (?:security|checks)|compliant)\b",
    re.IGNORECASE,
)
_BADGE_RE = re.compile(r"\[!\[[^\]]*\]\([^)]*\)\]\([^)]*\)|!\[[^\]]*\]\([^)]*\)")
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]*\)")
_SKIP_LINE_RE = re.compile(r"^(?:#{1,6}\s|>|\||<|!\[|[-*+]\s|\d+[.)]\s|={3,}|-{3,})")
_URL_RE = re.compile(r"https?://|www\.|github\.com", re.IGNORECASE)


def read_readme_excerpt(workspace_path: str | Path) -> str:
    """Return the first usable README prose paragraph (bounded, never raises)."""
    root = Path(workspace_path)
    try:
        candidates = [p for p in root.iterdir() if p.is_file() and p.name.lower() in _README_NAMES]
    except OSError:
        return ""
    for path in sorted(candidates, key=lambda p: p.name.lower() != "readme.md"):
        try:
            raw = path.read_text(encoding="utf-8", errors="replace")[:_MAX_README_BYTES]
        except OSError:
            continue
        prose = _first_prose_paragraph(raw)
        if prose:
            return prose[:1500]
    return ""


def build_repository_summary(
    workspace_path: str | Path,
    repository_analysis: dict[str, Any] | None,
    *,
    ai_summary: str | None = None,
    ai_meta: dict[str, Any] | None = None,
    readme_excerpt: str | None = None,
    generated_at: str | None = None,
) -> dict[str, Any]:
    """Build a validated summary dict bound to the analyzed revision."""
    analysis = repository_analysis if isinstance(repository_analysis, dict) else {}
    technologies = _technologies(analysis)
    ai_text = _valid_ai_summary(ai_summary)
    if ai_text:
        text = ai_text
        source = "ai"
        meta = _compact_ai(ai_meta)
    else:
        if readme_excerpt is None:
            readme_excerpt = read_readme_excerpt(workspace_path)
        text = _fallback_text(readme_excerpt, analysis, technologies)
        source = "deterministic"
        meta = None

    revision = analysis.get("revision") if isinstance(analysis.get("revision"), dict) else {}
    commit_sha = analysis.get("commit_sha") or revision.get("sha")
    record = RepositorySummary(
        text=text,
        source=source,
        commit_sha=commit_sha if isinstance(commit_sha, str) and commit_sha else None,
        generated_at=generated_at or utc_now_iso(),
        technologies=technologies,
        ai=meta,
    )
    return record.model_dump(by_alias=True)


def present_repository_summary(
    result: dict[str, Any] | None, target_revision: str | None
) -> dict[str, Any]:
    """Validate a stored summary for API display, marking revision mismatches."""
    analysis = result.get("repository_analysis") if isinstance(result, dict) else None
    raw = analysis.get("summary") if isinstance(analysis, dict) else None
    if not isinstance(raw, dict):
        return RepositorySummaryView().model_dump()
    try:
        summary = RepositorySummary.model_validate(raw)
    except Exception:  # noqa: BLE001 - malformed stored data is unavailable
        return RepositorySummaryView().model_dump()

    wanted = (target_revision or "").strip().lower()
    actual = (summary.commit_sha or "").strip().lower()
    stale = bool(wanted and actual and wanted != actual)
    return RepositorySummaryView(
        status="stale" if stale else "available",
        text=summary.text,
        source=summary.source,
        commit_sha=summary.commit_sha,
        generated_at=summary.generated_at,
        technologies=summary.technologies,
        ai=summary.ai,
    ).model_dump()


def _first_prose_paragraph(raw: str) -> str:
    text = re.sub(r"<!--.*?-->", " ", raw, flags=re.DOTALL)
    text = re.sub(r"```.*?```", " ", text, flags=re.DOTALL)
    text = _BADGE_RE.sub(" ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        lines = [line for line in lines if not _SKIP_LINE_RE.match(line)]
        if not lines:
            continue
        paragraph = " ".join(lines)
        paragraph = _BADGE_RE.sub(" ", paragraph)
        paragraph = _MD_LINK_RE.sub(r"\1", paragraph)
        paragraph = re.sub(r"[*_`~]+", "", paragraph)
        paragraph = re.sub(r"\s+", " ", paragraph).strip()
        if len(paragraph) < 40:
            continue
        if _CLAIM_RE.search(paragraph) or _URL_RE.search(paragraph):
            continue
        return paragraph
    return ""


def _first_sentences(text: str, limit: int = 200) -> str:
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    out = ""
    for sentence in sentences[:2]:
        candidate = f"{out} {sentence}".strip()
        if out and len(candidate) > limit:
            break
        out = candidate
    return _truncate(out or text, limit)


def _fallback_text(
    readme_excerpt: str | None,
    analysis: dict[str, Any],
    technologies: list[str],
) -> str:
    excerpt = _first_prose_paragraph(readme_excerpt or "")
    if excerpt:
        text = _first_sentences(excerpt)
        if text and text[-1] not in ".!?":
            text += "."
        if technologies:
            lowered = text.lower().replace("-", " ")
            missing = [t for t in technologies[:2] if t.lower().replace("-", " ") not in lowered]
            if missing:
                text += f" Detected stack: {', '.join(missing)}."
        return _truncate(text, _MAX_TEXT)

    languages = _languages(analysis)
    apps = _app_paths(analysis)
    lang_label = ", ".join(languages[:2]) if languages else "Undocumented"
    lang_label = lang_label[:1].upper() + lang_label[1:]
    if apps:
        paths = ", ".join(apps[:3])
        suffix = "s" if len(apps) != 1 else ""
        return _truncate(
            f"{lang_label} repository with {len(apps)} detected application{suffix} "
            f"({paths}) based on repository manifests; no README description was available.",
            _MAX_TEXT,
        )
    return _truncate(
        f"{lang_label} repository; no application manifests or README description were available.",
        _MAX_TEXT,
    )


def _valid_ai_summary(value: str | None) -> str:
    if not isinstance(value, str):
        return ""
    text = re.sub(r"\s+", " ", value).strip()
    if not text or len(text) > _MAX_AI_CHARS or len(text.split()) > _MAX_AI_WORDS:
        return ""
    if _CLAIM_RE.search(text) or _URL_RE.search(text):
        return ""
    return text


def _compact_ai(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(meta, dict):
        return None
    keys = ("outcome", "provider", "model", "fallback_used", "failure_category", "cached")
    compact = {key: meta.get(key) for key in keys if meta.get(key) is not None}
    return compact or None


def _technologies(analysis: dict[str, Any]) -> list[str]:
    labels: list[str] = []
    apps = analysis.get("applications")
    if isinstance(apps, list):
        for app in apps:
            values = app.get("technologies") if isinstance(app, dict) else None
            if not isinstance(values, list):
                continue
            for value in values:
                if isinstance(value, str) and value.strip() and value not in labels:
                    labels.append(value.strip())
    if not labels:
        labels = _languages(analysis)
    return labels[:6]


def _languages(analysis: dict[str, Any]) -> list[str]:
    languages = analysis.get("languages")
    if not isinstance(languages, list):
        return []
    values: list[str] = []
    for item in languages:
        name = item.get("language") if isinstance(item, dict) else None
        if isinstance(name, str) and name and name not in values:
            values.append(name)
    return values[:3]


def _app_paths(analysis: dict[str, Any]) -> list[str]:
    apps = analysis.get("applications")
    if not isinstance(apps, list):
        return []
    paths: list[str] = []
    for app in apps:
        path = app.get("path") if isinstance(app, dict) else None
        if isinstance(path, str) and path and path not in paths:
            paths.append(path[:60])
    return paths


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"
