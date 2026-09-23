"""Phase 2 — Change Intelligence domain models.

Deterministic, evidence-based change-impact analysis. The Change Impact Graph
(CIG) is deliberately distinct from the Causal Execution Graph (CEG): the CEG
describes runtime execution causality between deployed services, while the CIG
describes repository dependency impact between source artifacts.

Every CIG edge carries concrete repository evidence (file:line references) and
a confidence level (HIGH / MEDIUM / HEURISTIC). No LLM is used; unresolved
dependencies are reported as such rather than invented.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from app.models.domain import _utc_now


class ChangeType(str, Enum):
    MODIFIED = "modified"
    ADDED = "added"
    DELETED = "deleted"
    RENAMED = "renamed"


class Confidence(str, Enum):
    HIGH = "high"  # structurally verified (e.g. Python AST resolved to a repo file)
    MEDIUM = "medium"  # resolved via a heuristic, still traceable to concrete evidence
    HEURISTIC = "heuristic"  # best-effort inference; treat as advisory


class SymbolKind(str, Enum):
    MODULE = "module"
    CLASS = "class"
    FUNCTION = "function"
    METHOD = "method"
    VARIABLE = "variable"


class Language(str, Enum):
    PYTHON = "python"
    TYPESCRIPT = "typescript"
    JAVASCRIPT = "javascript"
    JSON = "json"
    YAML = "yaml"
    UNSUPPORTED = "unsupported"


class RelationshipType(str, Enum):
    IMPORT = "import"
    CALL = "call"
    REFERENCE = "reference"
    EXTENDS = "extends"
    IMPLEMENTS = "implements"
    INHERITS = "inherits"
    API_CONSUMER = "api-consumer"
    SCHEMA_CONSUMER = "schema-consumer"
    CONFIGURATION_DEPENDENCY = "configuration-dependency"
    TEST_COVERS = "test-covers"
    UNKNOWN = "unknown"


class NodeType(str, Enum):
    """Role of a CIG node relative to the change set."""

    CHANGED = "changed"  # file/symbol directly touched by the change set
    AFFECTED = "affected"  # depends on a changed artifact (direct or transitive)
    CONTEXT = "context"  # depends on an affected artifact but is not itself affected (informational)
    TEST = "test"  # test file that covers changed/affected artifacts
    CONFIG = "config"  # config/manifest file whose meaning depends on changed artifacts


class Hunk(BaseModel):
    new_start: int
    new_end: int
    old_start: int
    old_end: int


class FileChange(BaseModel):
    path: str
    change_type: ChangeType
    old_path: str | None = None
    added_lines: int = 0
    deleted_lines: int = 0
    hunks: list[Hunk] = Field(default_factory=list)

    def to_ui(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "old_path": self.old_path,
            "change_type": self.change_type.value,
            "added_lines": self.added_lines,
            "deleted_lines": self.deleted_lines,
            "hunks": [
                {
                    "new_start": h.new_start,
                    "new_end": h.new_end,
                    "old_start": h.old_start,
                    "old_end": h.old_end,
                }
                for h in self.hunks
            ],
        }


class ChangeSet(BaseModel):
    base_revision: str
    target_revision: str
    base_sha: str
    target_sha: str
    source_method: str  # local_copy | local_path | shallow_clone
    is_git: bool = True
    files: list[FileChange] = Field(default_factory=list)
    unsupported_files: list[str] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {"modified": 0, "added": 0, "deleted": 0, "renamed": 0}
        for f in self.files:
            counts[f.change_type.value] += 1
        return counts

    def to_ui(self) -> dict[str, Any]:
        return {
            "base_revision": self.base_revision,
            "target_revision": self.target_revision,
            "base_sha": self.base_sha,
            "target_sha": self.target_sha,
            "source_method": self.source_method,
            "is_git": self.is_git,
            "counts": self.counts,
            "files": [f.to_ui() for f in self.files],
            "unsupported": self.unsupported_files,
        }


class ImportRef(BaseModel):
    """A dependency a file declares (import / require statement)."""

    module: str  # dotted module / package path as written
    names: list[str] = Field(default_factory=list)  # imported names (e.g. from x import y)
    line: int
    native: bool = True


class Symbol(BaseModel):
    symbol_id: str
    name: str
    fqn: str
    kind: SymbolKind
    path: str
    line: int
    end_line: int
    language: Language = Language.PYTHON

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.symbol_id,
            "name": self.name,
            "fqn": self.fqn,
            "kind": self.kind.value,
            "path": self.path,
            "line": self.line,
            "end_line": self.end_line,
            "language": self.language.value,
        }


class FileSymbols(BaseModel):
    path: str
    language: Language = Language.UNSUPPORTED
    symbols: list[Symbol] = Field(default_factory=list)
    imports: list[ImportRef] = Field(default_factory=list)
    unresolved_imports: list[ImportRef] = Field(default_factory=list)
    parse_error: str | None = None


class ChangedSymbol(BaseModel):
    symbol: Symbol
    change_type: ChangeType
    lines_changed: int = 0


class ImpactNode(BaseModel):
    id: str
    path: str
    node_type: NodeType
    change_type: ChangeType | None = None
    symbol: str | None = None
    symbol_id: str | None = None
    kind: SymbolKind | None = None
    language: Language = Language.UNSUPPORTED
    direct: bool = False  # True for directly affected (or changed) nodes
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "path": self.path,
            "node_type": self.node_type.value,
            "change_type": self.change_type.value if self.change_type else None,
            "symbol": self.symbol,
            "symbol_id": self.symbol_id,
            "kind": self.kind.value if self.kind else None,
            "language": self.language.value,
            "direct": self.direct,
        }


class ImpactEdge(BaseModel):
    id: str
    source: str  # source artifact id (path or symbol_id)
    target: str  # target artifact id
    relationship: RelationshipType
    confidence: Confidence
    evidence: str  # concrete repo reference, e.g. "app.py:3 import mod"
    direct: bool = True
    note: str | None = None

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "target": self.target,
            "relationship": self.relationship.value,
            "confidence": self.confidence.value,
            "evidence": self.evidence,
            "direct": self.direct,
            "note": self.note,
        }


class CigGraph(BaseModel):
    nodes: list[ImpactNode] = Field(default_factory=list)
    edges: list[ImpactEdge] = Field(default_factory=list)

    def to_ui(self) -> dict[str, Any]:
        return {"nodes": [n.to_ui() for n in self.nodes], "edges": [e.to_ui() for e in self.edges]}


class UnresolvedDependency(BaseModel):
    path: str
    line: int
    target: str
    kind: str  # import | require | dynamic | config
    reason: str

    def to_ui(self) -> dict[str, Any]:
        return self.model_dump()


class ImpactTraversal(BaseModel):
    max_depth: int = 3
    direct_targets: list[str] = Field(default_factory=list)
    transitive_targets: list[str] = Field(default_factory=list)
    cycles_detected: list[tuple[str, str]] = Field(default_factory=list)
    depth_used: int = 0

    def to_ui(self) -> dict[str, Any]:
        return {
            "max_depth": self.max_depth,
            "depth_used": self.depth_used,
            "direct_targets": self.direct_targets,
            "transitive_targets": self.transitive_targets,
            "cycles_detected": [list(c) for c in self.cycles_detected],
        }


class RiskLevel(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class RiskFactor(BaseModel):
    code: str
    level: RiskLevel
    reason: str

    def to_ui(self) -> dict[str, Any]:
        return {"code": self.code, "level": self.level.value, "reason": self.reason}


class ImpactRisk(BaseModel):
    level: RiskLevel = RiskLevel.NONE
    factors: list[RiskFactor] = Field(default_factory=list)

    def to_ui(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "factors": [f.to_ui() for f in self.factors],
        }


class VerificationRequirement(BaseModel):
    id: str
    target_path: str
    target_symbol: str | None = None
    requirement: str
    reason: str
    check_category: str  # maps to an existing verifier check category
    executable: bool  # can the existing verifier execute this check today
    status: str = "identified"  # identified | executable | not_executable

    def to_ui(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "target_path": self.target_path,
            "target_symbol": self.target_symbol,
            "requirement": self.requirement,
            "reason": self.reason,
            "check_category": self.check_category,
            "executable": self.executable,
            "status": self.status,
        }


class ChangeImpactAnalysis(BaseModel):
    """Top-level Phase 2 artifact (persisted in deployments.change_intel_json)."""

    deployment_id: str | None = None
    repository_url: str
    changeset: ChangeSet
    changed_symbols: list[ChangedSymbol] = Field(default_factory=list)
    graph: CigGraph = Field(default_factory=CigGraph)
    traversal: ImpactTraversal = Field(default_factory=ImpactTraversal)
    unresolved: list[UnresolvedDependency] = Field(default_factory=list)
    risk: ImpactRisk = Field(default_factory=ImpactRisk)
    requirements: list[VerificationRequirement] = Field(default_factory=list)
    generated_at: str = Field(default_factory=_utc_now)
    is_demo: bool = False

    def to_ui(self) -> dict[str, Any]:
        return {
            "deployment_id": self.deployment_id,
            "repository_url": self.repository_url,
            "is_demo": self.is_demo,
            "label": "DEMO/MOCK" if self.is_demo else None,
            "generated_at": self.generated_at,
            "changeset": self.changeset.to_ui(),
            "changed_symbols": [cs.symbol.to_ui() | {"change_type": cs.change_type.value, "lines_changed": cs.lines_changed} for cs in self.changed_symbols],
            "graph": self.graph.to_ui(),
            "traversal": self.traversal.to_ui(),
            "unresolved": [u.to_ui() for u in self.unresolved],
            "risk": self.risk.to_ui(),
            "requirements": [r.to_ui() for r in self.requirements],
        }


def new_edge(prefix: str = "e") -> str:
    return f"{prefix}_{uuid4().hex[:10]}"