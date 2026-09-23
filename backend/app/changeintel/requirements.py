"""Verification requirement generation mapped to the existing verifier (Phase 2).

Requirements are advisory and recorded honestly:
  check_category  -> the existing verifier check category most relevant
                     (schema | config | compose | security | constraints | preflight)
  executable      -> True only when the V1 verifier can actually execute this
                     dimension today (config/compose validation during the
                     pre-execution gate). Source-level static checks (import
                     safety, deleted symbols) are NOT in the V1 verifier's check
                     list, so they are recorded as not_executable with a clear
                     reason — never claimed as checked.
"""

from __future__ import annotations

from uuid import uuid4

from app.changeintel.models import (
    ChangeSet,
    ChangeType,
    CigGraph,
    NodeType,
    RelationshipType,
    UnresolvedDependency,
    VerificationRequirement,
)

MAX_REQUIREMENTS = 20

# Existing verifier check categories (see app/agents/verifier.py).
_VERIFIER_CATEGORIES = ("schema", "config", "compose", "security", "constraints", "preflight")


def generate_requirements(
    changeset: ChangeSet,
    graph: CigGraph,
    unresolved: list[UnresolvedDependency],
    traversal,
) -> list[VerificationRequirement]:
    requirements: list[VerificationRequirement] = []
    edges = graph.edges
    nodes = graph.nodes
    changed_files = {fc.path: fc for fc in changeset.files}
    changed_ids = {n.id for n in nodes if n.node_type == NodeType.CHANGED}

    # --- config/compose files changed --- (existing verifier CAN validate these)
    for fc in changeset.files:
        if _is_config_path(fc.path):
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=fc.path,
                    requirement=(
                        "Re-validate the modified configuration against its referenced "
                        "services before deployment."
                    ),
                    reason=f"config file '{fc.path}' changed ({fc.change_type.value})",
                    check_category="config",
                    executable=True,
                    status="executable",
                )
            )

    # --- deleted symbols / broken imports --- (static; verifier cannot run this)
    for u in unresolved:
        if u.kind == "deleted-import":
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=u.path,
                    requirement=(
                        f"Restore or update the import of '{u.target}' referenced at "
                        f"{u.path}:{u.line} — the module was deleted by this change set."
                    ),
                    reason=u.reason,
                    check_category="constraints",
                    executable=False,
                    status="not_executable",
                )
            )

    for cs_path, cs_change in sorted(changed_files.items()):
        if cs_change.change_type == ChangeType.DELETED:
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=cs_path,
                    requirement=(
                        f"Confirm no remaining dependents reference deleted artifact "
                        f"'{cs_path}' before shipping this change."
                    ),
                    reason="deleted artifact present in change set",
                    check_category="constraints",
                    executable=False,
                    status="not_executable",
                )
            )

    # --- renames may leave obsolete references ---
    for fc in changeset.files:
        if fc.change_type == ChangeType.RENAMED and fc.old_path:
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=fc.path,
                    requirement=(
                        f"Update references from former path '{fc.old_path}' to "
                        f"'{fc.path}' and remove any stale imports."
                    ),
                    reason=f"path renamed {fc.old_path} -> {fc.path}",
                    check_category="preflight",
                    executable=False,
                    status="not_executable",
                )
            )

    # --- schema / model consumers ---
    for e in edges:
        if e.relationship == RelationshipType.SCHEMA_CONSUMER and e.target in changed_ids:
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=e.source,
                    requirement=(
                        f"Verify schema compatibility of '{e.source}' against changed "
                        f"schema artifact '{e.target}'."
                    ),
                    reason=e.evidence,
                    check_category="schema",
                    executable=False,
                    status="not_executable",
                )
            )

    # --- API consumers of changed endpoints ---
    for e in edges:
        if e.relationship == RelationshipType.API_CONSUMER and e.target in changed_ids:
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=e.source,
                    requirement=(
                        f"Verify the API contract between consumer '{e.source}' and "
                        f"changed endpoint '{e.target}'."
                    ),
                    reason=e.evidence,
                    check_category="constraints",
                    executable=False,
                    status="not_executable",
                )
            )

    # --- affected dependents (regression) ---
    all_affected = list(traversal.direct_targets) + list(traversal.transitive_targets)
    for path in sorted(all_affected)[:12]:
        requirements.append(
            VerificationRequirement(
                id=_new_req_id(),
                target_path=path,
                requirement=f"Re-verify '{path}' against its changed dependencies (regression).",
                reason=f"{path} is {_dist_label(path, traversal)}",
                check_category="preflight",
                executable=False,
                status="not_executable",
            )
        )

    # --- test coverage gap ---
    test_targets = {e.target for e in edges if e.relationship == RelationshipType.TEST_COVERS}
    for fc in sorted(changed_files.values(), key=lambda f: f.path):
        if fc.path not in test_targets and not _is_config_path(fc.path):
            requirements.append(
                VerificationRequirement(
                    id=_new_req_id(),
                    target_path=fc.path,
                    requirement=(
                        f"No test in the repository covers changed artifact '{fc.path}'. "
                        "Add or run a covering test before merge."
                    ),
                    reason="missing TEST_COVERS edge",
                    check_category="preflight",
                    executable=False,
                    status="not_executable",
                )
            )

    requirements.sort(key=lambda r: (r.check_category, r.target_path))
    return requirements[:MAX_REQUIREMENTS]


def _dist_label(path: str, traversal) -> str:
    if path in traversal.direct_targets:
        return "directly affected"
    return "transitively affected"


def _is_config_path(path: str) -> bool:
    return path.endswith((".json", ".yml", ".yaml"))


def _new_req_id() -> str:
    return f"req_{uuid4().hex[:10]}"