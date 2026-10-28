"""Deterministic, bounded configuration and code-policy checks.

These run whenever security scanning is requested, regardless of which
optional external tools are installed, so a repository always gets *some*
real coverage. They are static pattern checks only:

- Every result is a POTENTIAL issue with an explicit confidence and
  ``verification_status="unverified"`` — a pattern match is evidence to
  investigate, never a confirmed exploit (requirement 2D/2E).
- External scanners (semgrep/gitleaks/trivy) remain the proven detectors;
  this module never claims to replace them and never reports on tool output.
- Bounded and read-only: no repository code is executed, files/bytes are
  capped, and a failure surfaces as a failed task — never as "clean".
- Secret VALUES are never read into output: committed environment files are
  reported by path only.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from app.analysis.tasks import (
    COMPLETED_WITH_FINDINGS,
    PARTIAL,
    SUCCEEDED,
    TaskResult,
)

_EMPTY_DIRS = frozenset(
    {".git", "node_modules", ".venv", "venv", "__pycache__", ".next", "dist",
     "build", "coverage", ".cache", "vendor", "target", ".idea", ".vscode"}
)
_MAX_FILES = 800
_MAX_READ = 256 * 1024
_MAX_DEPTH = 5
_MAX_HITS_PER_RULE = 20

_SOURCE = "builtin"


@dataclass(frozen=True)
class _Rule:
    rule_id: str
    category: str  # security | configuration
    severity: str
    confidence: str
    title: str
    pattern: re.Pattern[str]
    suffixes: tuple[str, ...]
    explanation: str
    remediation: str


# Curated, high-signal rules only. Deliberately small: proven external tools
# own broad SAST coverage; these guarantee baseline checks even offline.
_RULES: tuple[_Rule, ...] = (
    _Rule(
        "SEC-101", "security", "high", "medium",
        "Shell command execution enabled",
        re.compile(r"\bshell\s*=\s*True\b"),
        (".py",),
        "A process is started with shell=True, which can allow command "
        "injection when any argument is attacker-controlled.",
        "Pass argument lists without shell=True, or validate/escape every "
        "value that reaches the command line.",
    ),
    _Rule(
        "SEC-102", "security", "medium", "medium",
        "Potentially unsafe YAML deserialization",
        re.compile(r"\byaml\.load\s*\("),
        (".py",),
        "yaml.load without an explicit SafeLoader can construct arbitrary "
        "objects when parsing untrusted input.",
        "Use yaml.safe_load(), or pass Loader=yaml.SafeLoader explicitly.",
    ),
    _Rule(
        "SEC-103", "security", "high", "medium",
        "Unsafe deserialization (pickle)",
        re.compile(r"\bpickle\.(loads?|Unpickler)\b"),
        (".py",),
        "Unpickling data can execute arbitrary code; unsafe when the input "
        "is not fully trusted.",
        "Use a non-executable format (JSON) for untrusted data, or verify "
        "the source and integrity of the payload.",
    ),
    _Rule(
        "SEC-104", "security", "high", "high",
        "SQL built from an f-string",
        re.compile(r"\.execute\s*\(\s*f[\"']"),
        (".py",),
        "An f-string interpolated directly into a SQL execute() call is a "
        "strong SQL-injection signal.",
        "Use parameterized queries (placeholder arguments) instead of "
        "string interpolation.",
    ),
    _Rule(
        "SEC-105", "security", "low", "high",
        "Weak hash algorithm",
        re.compile(r"\bhashlib\.(md5|sha1)\s*\(|\bcreateHash\s*\(\s*[\"'](?:md5|sha1)[\"']"),
        (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
        "MD5/SHA-1 are collision-broken and unsuitable for security "
        "decisions (passwords, signatures, integrity).",
        "Use SHA-256 or better, and a password KDF (argon2/bcrypt/scrypt) "
        "for passwords.",
    ),
    _Rule(
        "CFG-003", "configuration", "medium", "medium",
        "Debug mode enabled in source",
        # Covers debug=, debug_mode=, DEBUG_MODE= (still requires an explicit
        # True so a disabled flag never matches).
        re.compile(r"(?i)\bdebug(?:_?mode)?\s*=\s*True\b"),
        (".py",),
        "Debug mode can expose stack traces, the interactive debugger, and "
        "verbose internals in deployed environments.",
        "Disable debug in production builds and read the flag from the "
        "environment instead.",
    ),
    _Rule(
        "CFG-004", "security", "medium", "medium",
        "TLS certificate verification disabled",
        re.compile(r"\bverify\s*=\s*False\b|\brejectUnauthorized\s*:\s*false\b"),
        (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs"),
        "Disabling certificate verification allows man-in-the-middle "
        "interception of encrypted traffic.",
        "Enable certificate verification; for local testing use a "
        "dedicated test setting, never a production default.",
    ),
    _Rule(
        "CFG-002", "configuration", "medium", "medium",
        "CORS wildcard origin",
        re.compile(
            r"allow_origins\s*=\s*\[[^\]]*[\"']\*[\"']"
            r"|Access-Control-Allow-Origin[\"']?\s*[:=]\s*[\"']\*"
            r"|add_header\s+Access-Control-Allow-Origin\s+[\"']\*"
        ),
        (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
         ".conf", ".yml", ".yaml", ".json"),
        "Allowing any origin to read responses exposes authenticated data "
        "to arbitrary third-party sites when credentials are enabled.",
        "Restrict allow_origins to the exact trusted origins, and never "
        "combine wildcard origins with credentialed requests.",
    ),
)

_ENDPOINT_PATTERNS = (
    re.compile(
        r"@(?:app|router|api|bp|blueprint)\s*\.\s*"
        r"(?:get|post|put|delete|patch|route|add_url_rule)\s*\("
    ),
    re.compile(
        r"\b(?:app|router|server|api)\s*\.\s*"
        r"(?:get|post|put|delete|patch|all)\s*\(\s*[`'\"]"
    ),
)

_AUTH_CONTENT = re.compile(
    r"require_auth|requireRole|require_role|login_required|require_login"
    r"|Depends\s*\([^)]*(?:auth|security|token)"
    r"|@login_required|withAuth|useAuth|verifyToken|checkAuth|isAuthenticated"
    r"|jwt\.|jsonwebtoken|passport\.|get_current_user|current_user"
    r"|Authorization\s*[:=]|Bearer\s+[\"'`]|is_authenticated|has_perm\b",
    re.IGNORECASE,
)

_AUTH_NAME_HINTS = ("auth", "login", "session", "oauth", "jwt", "identity",
                    "permission", "permissions", "rbac", "guard", "acl")

_CODE_SUFFIXES = (".py", ".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs",
                  ".rb", ".php", ".go", ".java")


def _read(path: Path) -> str:
    try:
        if path.stat().st_size > _MAX_READ:
            return ""
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return path.name


def run_policy_checks(root: Path) -> TaskResult:
    """Run bounded read-only policy checks over the repository tree."""
    findings: list[dict] = []
    files_scanned = 0
    truncated = False
    endpoint_files: list[str] = []
    auth_evidence: bool = False
    hits: dict[str, int] = {rule.rule_id: 0 for rule in _RULES}

    # Committed environment file (path only — values are never read out).
    for env_name in (".env",):
        env_path = root / env_name
        if env_path.is_file():
            text = _read(env_path)
            assignments = [
                line for line in text.splitlines()
                if line.strip() and not line.strip().startswith("#")
                and "=" in line
            ]
            if assignments:
                findings.append({
                    "source": _SOURCE, "scanner": "builtin",
                    "rule_id": "CFG-001", "category": "configuration",
                    "severity": "high", "confidence": "high",
                    "path": env_name, "line": 1,
                    "message": "Environment file committed to the repository",
                    "explanation": (
                        "A populated .env file is tracked in the repository; "
                        "environment files normally hold credentials and "
                        "belong in local-only, ignored configuration."
                    ),
                    "remediation": (
                        "Remove the file from version control, rotate any "
                        "credentials it contained, commit a redacted "
                        ".env.example instead, and add .env to .gitignore."
                    ),
                    "verification_status": "unverified",
                })

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in _EMPTY_DIRS]
        try:
            depth = len(Path(dirpath).relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= _MAX_DEPTH:
            dirnames[:] = []
        if files_scanned >= _MAX_FILES:
            truncated = True
            break
        for fn in sorted(filenames):
            if files_scanned >= _MAX_FILES:
                truncated = True
                break
            path = Path(dirpath) / fn
            rel = _rel(path, root)
            low = rel.lower()
            if any(hint in low for hint in _AUTH_NAME_HINTS):
                auth_evidence = True
            applicable = [r for r in _RULES if low.endswith(r.suffixes)]
            code_file = low.endswith(_CODE_SUFFIXES)
            if not applicable and not code_file:
                continue
            text = _read(path)
            if not text:
                continue
            files_scanned += 1
            if code_file and not auth_evidence and _AUTH_CONTENT.search(text):
                auth_evidence = True
            if code_file and any(p.search(text) for p in _ENDPOINT_PATTERNS):
                endpoint_files.append(rel)
            for lineno, line in enumerate(text.splitlines(), start=1):
                if len(line) > 400:
                    continue
                for rule in applicable:
                    if hits[rule.rule_id] >= _MAX_HITS_PER_RULE:
                        continue
                    if rule.pattern.search(line):
                        hits[rule.rule_id] += 1
                        findings.append({
                            "source": _SOURCE, "scanner": "builtin",
                            "rule_id": rule.rule_id, "category": rule.category,
                            "severity": rule.severity,
                            "confidence": rule.confidence,
                            "path": rel, "line": lineno,
                            "message": rule.title,
                            "explanation": rule.explanation,
                            "remediation": rule.remediation,
                            "verification_status": "unverified",
                        })

    # Aggregate authentication-boundary observation. Reports the absence of
    # any auth boundary as a POTENTIAL issue (never a confirmed defect). A
    # truncated walk has not seen the whole tree, so silence is not evidence
    # of a missing boundary and no AUTH-001 is claimed.
    if endpoint_files and not auth_evidence and not truncated:
        findings.append({
            "source": _SOURCE, "scanner": "builtin",
            "rule_id": "AUTH-001", "category": "authentication",
            "severity": "high", "confidence": "medium",
            "path": endpoint_files[0], "line": None,
            "message": (
                f"{len(endpoint_files)} endpoint file(s) detected with no "
                "authentication boundary found in the repository"
            ),
            "explanation": (
                "Endpoints were discovered but no authentication middleware, "
                "guard, login route, or token verification was detected "
                "anywhere in the scanned scope. Server-side authentication "
                "or resource-level authorization may be missing; this is an "
                "unverified indication based on static file inspection only, "
                "not a confirmed bypass."
            ),
            "remediation": (
                "Add server-side authentication middleware and per-resource "
                "authorization checks (verify ownership/tenant on every "
                "endpoint), then re-run a scan to verify the boundary."
            ),
            "verification_status": "unverified",
        })

    # A truncated walk is incomplete coverage: report PARTIAL so the
    # aggregate analysis_status and the merge policy treat this assessment
    # as not fully covered rather than as a clean, complete result.
    if truncated:
        status = PARTIAL
    else:
        status = COMPLETED_WITH_FINDINGS if findings else SUCCEEDED
    return TaskResult(
        task="security:builtin",
        status=status,
        findings=findings,
        evidence={
            "checks": [r.rule_id for r in _RULES] + ["CFG-001", "AUTH-001"],
            "files_scanned": files_scanned,
            "truncated": truncated,
            "endpoint_files": endpoint_files[:20],
            "auth_boundary_detected": auth_evidence or not endpoint_files,
            "note": (
                "Static pattern checks; every finding is unverified and "
                "requires confirmation. External scanners provide the "
                "authoritative SAST/secret/dependency results."
            ),
        },
        coverage=(
            f"policy checks over {files_scanned} file(s)"
            + (" (truncated at safety cap)" if truncated else "")
        ),
    )
