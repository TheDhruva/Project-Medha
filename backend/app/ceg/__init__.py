"""CEG package — causal execution graph + scoped rollback."""

from app.ceg.rollback import apply_scope_to_graph, compute_rollback_scope
from app.execution.plan_builder import build_ceg_from_plan

__all__ = ["apply_scope_to_graph", "build_ceg_from_plan", "compute_rollback_scope"]
