"""Deterministic merge-readiness policy (advisory, never auto-merging)."""

from app.mergepolicy.engine import (  # noqa: F401
    DEFAULT_POLICY,
    OUTCOMES,
    POLICY_VERSION,
    build_context,
    evaluate,
    evaluate_merge_readiness,
    load_policy,
)
