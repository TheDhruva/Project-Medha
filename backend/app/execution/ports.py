"""Authoritative port contract between CNP negotiation and real execution.

One contract per run: the final validated execution plan determines the
effective container-internal application port and the host-published port.

- ``internal_port``: the application's real listen port (repository
  evidence: an explicit script pin wins, otherwise the requested target).
  It exists only inside the container network namespace and is never
  availability-checked from the host.
- ``host_port``: the loopback-published port (the CNP PORT_CLAIM outcome
  for the application service, or a negotiated alternative when the
  requested host port is occupied). This is the ONLY port ever
  availability-checked and readiness-probed.

A busy host port never invalidates the internal port: the remedy is a
bounded CNP alternative negotiation for the host side (existing
``apply_decision`` flow + verifier/critic revalidation), never silent
remapping. The V1 real path executes exactly one application service, so
the Docker-agent application claim is authoritative; the Nginx edge
listener claim is aspirational proxy config and never decides the
application's publish mapping.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from app.models.domain import Constraint, ConstraintStatus, ConstraintType

# Bounded host-side renegotiation: declared alternatives first, then a
# short incremental scan. Never an unbounded loop (V1 CNP rounds cap is 3).
MAX_ALTERNATIVE_CANDIDATES = 20
MAX_PORT = 65535

_ACTIVE_PORT_STATUSES = frozenset(
    {
        ConstraintStatus.PROPOSED,
        ConstraintStatus.ACCEPTED,
        ConstraintStatus.SUPERSEDED,
    }
)


@dataclass(frozen=True)
class PortContract:
    """Effective mapping derived from the validated plan (JSON-safe)."""

    internal_port: int
    host_port: int
    app_service: str | None
    # Where the host port came from: negotiated app claim, requested target, etc.
    source: str
    renegotiated: bool = False

    @property
    def probe_url(self) -> str:
        return f"http://127.0.0.1:{self.host_port}/"

    @property
    def mapping(self) -> str:
        return f"host 127.0.0.1:{self.host_port} → container:{self.internal_port}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "internal_port": self.internal_port,
            "host_port": self.host_port,
            "container_port": self.internal_port,
            "app_service": self.app_service,
            "source": self.source,
            "renegotiated": self.renegotiated,
            "probe_url": self.probe_url,
            "mapping": self.mapping,
        }


def _valid_port(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        port = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return port if 1 <= port <= MAX_PORT else None


def app_port_claim(constraints: list[Constraint]) -> Constraint | None:
    """Authoritative application PORT_CLAIM (Docker agent's, not the edge proxy's)."""
    claims = [
        c
        for c in constraints
        if c.type == ConstraintType.PORT_CLAIM and c.status in _ACTIVE_PORT_STATUSES
    ]
    if not claims:
        return None
    for claim in claims:
        if claim.source_agent == "Docker Agent" and _valid_port(
            claim.payload.get("port")
        ) is not None:
            return claim
    for claim in claims:
        if (claim.service or "") != "nginx" and _valid_port(
            claim.payload.get("port")
        ) is not None:
            return claim
    return None


def resolve_port_contract(
    profile: Any,
    constraints: list[Constraint],
    *,
    internal_port: int,
) -> PortContract:
    """Derive the effective mapping: internal from repo evidence, host from CNP."""
    requested = _valid_port(getattr(profile, "target_port", None)) or internal_port
    internal = _valid_port(internal_port) or requested
    claim = app_port_claim(constraints)
    if claim is not None:
        host = _valid_port(claim.payload.get("port")) or requested
        return PortContract(
            internal_port=internal,
            host_port=host,
            app_service=claim.service,
            source=f"negotiated:{claim.constraint_id}",
        )
    return PortContract(
        internal_port=internal,
        host_port=requested,
        app_service=None,
        source="requested-target",
    )


def collect_used_host_ports(constraints: list[Constraint]) -> set[int]:
    """Host ports held by active (non-rejected) PORT_CLAIMs."""
    used: set[int] = set()
    for claim in constraints:
        if claim.type != ConstraintType.PORT_CLAIM:
            continue
        if claim.status == ConstraintStatus.REJECTED:
            continue
        port = _valid_port(claim.payload.get("port"))
        if port is not None:
            used.add(port)
    return used


def negotiate_host_alternative(
    constraints: list[Constraint],
    blocked_port: int,
    *,
    is_available: Callable[[int], bool],
    max_candidates: int = MAX_ALTERNATIVE_CANDIDATES,
) -> Any | None:
    """Pick a free host port through the existing CNP alternative flow.

    Returns a ``DecisionRecord`` (method="alternative") remapping the
    application claim, or None when no supported alternative exists. The
    caller applies it with ``apply_decision`` and re-runs the
    verifier/critic gate — the plan is never mutated silently.
    """
    from app.cnp.engine import DecisionRecord  # local: engine owns the record shape

    claim = app_port_claim(constraints)
    if claim is None:
        return None
    used = collect_used_host_ports(constraints)
    rejected = {
        _valid_port(c.payload.get("port"))
        for c in constraints
        if c.type == ConstraintType.PORT_CLAIM
        and c.status == ConstraintStatus.REJECTED
    }
    rejected.discard(None)

    candidates: list[int] = []
    for alt in claim.alternatives or []:
        port = _valid_port((alt or {}).get("port"))
        if port is not None and port not in candidates:
            candidates.append(port)
    probe = blocked_port + 1
    while len(candidates) < max_candidates and probe <= MAX_PORT:
        if probe not in candidates:
            candidates.append(probe)
        probe += 1

    chosen: int | None = None
    for port in candidates[:max_candidates]:
        if port == blocked_port or port in used or port in rejected:
            continue
        try:
            if is_available(port):
                chosen = port
                break
        except Exception:  # noqa: BLE001 - a failed probe is not a free port
            continue
    if chosen is None:
        return None
    return DecisionRecord(
        conflict_id=f"host:{blocked_port}",
        method="alternative",
        winner_ids=[claim.constraint_id],
        loser_ids=[claim.constraint_id],
        rationale=(
            f"Host port {blocked_port} is occupied; remapped the application "
            f"publish mapping to supported alternative {chosen} "
            f"(container port unchanged). Revalidation required before execution."
        ),
        updates=[
            {
                "constraint_id": claim.constraint_id,
                "old_value": blocked_port,
                "new_value": chosen,
                "field": "port",
            }
        ],
    )
