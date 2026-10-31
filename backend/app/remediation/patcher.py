"""Deterministic AST and pattern-based patch generation for detected findings."""

from __future__ import annotations

import ast
import difflib
import re
from pathlib import Path
from typing import Any

from app.remediation.models import RepairPlan


def _generate_unified_diff(original: str, patched: str, file_path: str) -> str:
    """Generate standard unified diff."""
    orig_lines = original.splitlines(keepends=True)
    patch_lines = patched.splitlines(keepends=True)
    diff = difflib.unified_diff(
        orig_lines,
        patch_lines,
        fromfile=f"a/{file_path}",
        tofile=f"b/{file_path}",
    )
    return "".join(diff)


def _extract_snippet(text: str, line_no: int | None, window: int = 3) -> str:
    """Extract snippet around a line number."""
    if line_no is None or line_no <= 0:
        lines = text.splitlines()
        return "\n".join(lines[:10])
    lines = text.splitlines()
    start = max(0, line_no - window - 1)
    end = min(len(lines), line_no + window)
    return "\n".join(lines[start:end])


def _patch_sec_101(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-101: Shell command execution enabled (shell=True -> shell=False)."""
    pattern = re.compile(r"(\bshell\s*=\s*)True\b")
    if pattern.search(content):
        patched = pattern.sub(r"\g<1>False", content)
        return patched, True
    return content, False


def _patch_sec_102(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-102: Potentially unsafe YAML deserialization.
    
    If Loader= is already explicitly specified (e.g. Loader=yaml.Loader),
    replace with Loader=yaml.SafeLoader since safe_load() rejects the Loader kwarg.
    Otherwise, replace yaml.load( with yaml.safe_load(.
    """
    if re.search(r"\byaml\.load\s*\([^)]*Loader\s*=\s*", content):
        patched = re.sub(
            r"(\byaml\.load\s*\([^)]*Loader\s*=\s*)[a-zA-Z0-9_\.]+",
            r"\g<1>yaml.SafeLoader",
            content,
        )
        if patched != content:
            return patched, True

    pattern = re.compile(r"\byaml\.load\s*\(")
    if pattern.search(content):
        patched = pattern.sub("yaml.safe_load(", content)
        return patched, True
    return content, False


def _patch_sec_105(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-105: Weak hash algorithm (hashlib.md5/sha1 -> sha256, createHash('md5'/'sha1') -> 'sha256')."""
    changed = False
    patched = content

    pattern_py = re.compile(r"\bhashlib\.(md5|sha1)\s*\(")
    if pattern_py.search(patched):
        patched = pattern_py.sub("hashlib.sha256(", patched)
        changed = True

    pattern_js = re.compile(r"""(\bcreateHash\s*\(\s*["'])(?:md5|sha1)(["']\s*\))""")
    if pattern_js.search(patched):
        patched = pattern_js.sub(r"\g<1>sha256\g<2>", patched)
        changed = True

    return patched, changed


def _patch_sec_106(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-106 / CFG-003: Debug flag enabled (debug=True -> debug=False)."""
    pattern = re.compile(r"(\bdebug(?:_?mode)?\s*=\s*)True\b", re.IGNORECASE)
    if pattern.search(content):
        patched = pattern.sub(r"\g<1>False", content)
        return patched, True
    return content, False


def _patch_sec_107(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-107 / CFG-002: Overly permissive CORS with credentials."""
    # Replace allow_origins=["*"] or allow_origins=['*'] with allow_origins=["http://localhost:3000"]
    pattern = re.compile(r"""(allow_origins\s*=\s*)\[\s*["']\*["']\s*\]""")
    if pattern.search(content):
        patched = pattern.sub(r'\g<1>["http://localhost:3000"]', content)
        return patched, True
    return content, False


def _patch_cfg_004(content: str, line_no: int | None) -> tuple[str, bool]:
    """CFG-004: TLS certificate verification disabled (verify=False -> verify=True)."""
    changed = False
    patched = content

    pattern_py = re.compile(r"(\bverify\s*=\s*)False\b")
    if pattern_py.search(patched):
        patched = pattern_py.sub(r"\g<1>True", patched)
        changed = True

    pattern_js = re.compile(r"(\brejectUnauthorized\s*:\s*)false\b", re.IGNORECASE)
    if pattern_js.search(patched):
        patched = pattern_js.sub(r"\g<1>true", patched)
        changed = True

    return patched, changed


def _patch_sec_108(content: str, line_no: int | None) -> tuple[str, bool]:
    """SEC-108: Hardcoded secret (e.g. secret_key = "secret")."""
    pattern = re.compile(
        r"""((?:secret|secret_key|jwt_secret|api_key|password)\s*=\s*)["'](?:secret|changeme|test|admin|123456)["']""",
        re.IGNORECASE,
    )
    if pattern.search(content):
        patched = pattern.sub(
            r'\g<1>__import__("os").getenv("SECRET_KEY", "dev-secret-only")',
            content,
        )
        return patched, True
    return content, False


DETERMINISTIC_PATCHERS = {
    # Canonical Policy Rule IDs
    "SEC-101": (_patch_sec_101, "Disable shell=True in subprocess to prevent command injection"),
    "SEC-102": (_patch_sec_102, "Use yaml.safe_load() or SafeLoader instead of unsafe yaml.load()"),
    "SEC-105": (_patch_sec_105, "Upgrade weak cryptographic hash to SHA-256"),
    "CFG-002": (_patch_sec_107, "Restrict wildcard CORS origin"),
    "CFG-003": (_patch_sec_106, "Disable debug mode (debug=False) for security"),
    "CFG-004": (_patch_cfg_004, "Enable TLS certificate verification"),
    # Aliases
    "SEC-106": (_patch_sec_106, "Disable debug mode (debug=False) for security"),
    "SEC-107": (_patch_sec_107, "Restrict wildcard CORS origin"),
    "SEC-108": (_patch_sec_108, "Replace hardcoded secret with environment variable lookup"),
}


def create_deterministic_repair_plan(
    finding: dict[str, Any],
    file_content: str,
) -> RepairPlan:
    """Generate a deterministic repair plan for a supported finding."""
    rule_id = str(finding.get("rule_id") or "").strip().upper()
    file_path = str(finding.get("path") or "")
    line_no = finding.get("line")
    finding_id = str(finding.get("finding_id") or "")

    patcher_info = DETERMINISTIC_PATCHERS.get(rule_id)
    if not patcher_info or not file_content:
        # Fallback manual / unautomated
        explanation = finding.get("explanation") or finding.get("message") or "Manual resolution required."
        return RepairPlan(
            finding_id=finding_id,
            rule_id=rule_id,
            file_path=file_path,
            line=line_no,
            title=f"Manual fix required for {rule_id}",
            explanation=explanation,
            remediation_strategy="manual_required",
            can_auto_fix=False,
            risk_level="medium",
            original_snippet=_extract_snippet(file_content, line_no),
            patched_snippet="",
            diff_unified="",
            message="This issue requires manual architecture or configuration adjustments.",
        )

    patcher_fn, patch_title = patcher_info
    patched_content, changed = patcher_fn(file_content, line_no)

    if not changed or patched_content == file_content:
        return RepairPlan(
            finding_id=finding_id,
            rule_id=rule_id,
            file_path=file_path,
            line=line_no,
            title=f"Automated pattern could not resolve {rule_id}",
            explanation=finding.get("explanation") or "Pattern match did not identify a safe automated substitution.",
            remediation_strategy="manual_required",
            can_auto_fix=False,
            risk_level="medium",
            original_snippet=_extract_snippet(file_content, line_no),
            patched_snippet="",
            diff_unified="",
            message="No safe automated transformation could be matched to the code location.",
        )

    # Validate syntax according to file type
    syntax_error_msg: str | None = None
    lower_path = file_path.lower()
    if lower_path.endswith((".py", ".pyi")):
        try:
            ast.parse(patched_content)
        except SyntaxError as exc:
            syntax_error_msg = f"Python syntax error: {exc}"
    elif lower_path.endswith(".json"):
        import json
        try:
            json.loads(patched_content)
        except Exception as exc:
            syntax_error_msg = f"JSON syntax error: {exc}"
    elif lower_path.endswith((".yaml", ".yml")):
        try:
            import yaml
            yaml.safe_load(patched_content)
        except Exception as exc:
            syntax_error_msg = f"YAML syntax error: {exc}"

    if syntax_error_msg:
        return RepairPlan(
            finding_id=finding_id,
            rule_id=rule_id,
            file_path=file_path,
            line=line_no,
            title=f"Syntax validation failed for {rule_id} fix",
            explanation=f"Proposed patch introduced a syntax error: {syntax_error_msg}",
            remediation_strategy="deterministic_ast",
            can_auto_fix=False,
            risk_level="high",
            original_snippet=_extract_snippet(file_content, line_no),
            patched_snippet="",
            diff_unified="",
            message=f"Syntax check rejected the patch: {syntax_error_msg}",
        )

    diff = _generate_unified_diff(file_content, patched_content, file_path)
    orig_snippet = _extract_snippet(file_content, line_no)
    patched_snippet = _extract_snippet(patched_content, line_no)
    import hashlib
    diff_hash = hashlib.sha256(diff.encode("utf-8")).hexdigest() if diff else ""

    return RepairPlan(
        finding_id=finding_id,
        rule_id=rule_id,
        file_path=file_path,
        line=line_no,
        title=patch_title,
        explanation=finding.get("explanation") or patch_title,
        remediation_strategy="deterministic_ast",
        can_auto_fix=True,
        risk_level="low",
        original_snippet=orig_snippet,
        patched_snippet=patched_snippet,
        diff_unified=diff,
        diff_hash=diff_hash,
        message=f"Clean, deterministic patch generated for {rule_id}.",
    )
