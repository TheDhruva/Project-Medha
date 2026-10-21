"""Repository analysis subsystem (Phase: comprehensive first-run inventory).

Separates repository-wide analysis (always attempted) from deployment target
selection / planning (may be blocked). Analysis tasks are isolated: one
recoverable failure never cancels an independent task, and every task settles
into an explicit, honest status.
"""
