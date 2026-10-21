"""Security scanning helpers (Phase D).

Local, offline-capable wrappers around external scanner CLIs. Results are
reported honestly: a scanner that is missing, times out, or returns output we
cannot parse is never reported as "clean".
"""
