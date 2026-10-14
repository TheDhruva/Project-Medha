"""Postgres connection pooling (fake connections — no server needed).

Locks in: per-thread reuse (one handshake, many queries), reconnect on
closed/stale connections, idle validation, and nesting fallback to a
dedicated connection so nested blocks keep separate transactions.
"""

from __future__ import annotations

import pytest
from psycopg import OperationalError

import app.database.connection as conn_mod
from app.database.connection import get_connection


class FakeCursor:
    def __init__(self, conn: FakeConn) -> None:
        self._conn = conn

    def execute(self, sql: str, params=None):
        self._conn.statements.append(sql)
        if self._conn.fail_on_execute:
            raise OperationalError("connection lost")
        return self

    def __enter__(self) -> FakeCursor:
        return self

    def __exit__(self, *args) -> None:
        return None


class FakeConn:
    def __init__(self) -> None:
        self.closed = 0
        self.statements: list[str] = []
        self.commits = 0
        self.fail_on_execute = False

    def cursor(self, row_factory=None) -> FakeCursor:
        return FakeCursor(self)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def close(self) -> None:
        self.closed = 1


@pytest.fixture()
def pooled(monkeypatch):
    created: list[FakeConn] = []

    def _factory():
        fake = FakeConn()
        created.append(fake)
        return fake

    monkeypatch.setattr(conn_mod, "_pg_connect_raw", _factory)
    monkeypatch.setattr(conn_mod, "resolve_backend", lambda db_path=None: "postgres")
    # Isolate thread-local slot state between tests.
    for attr in ("conn", "last_use", "depth"):
        if hasattr(conn_mod._pg_local, attr):
            delattr(conn_mod._pg_local, attr)
    return created


def test_sequential_checkouts_reuse_one_connection(pooled):
    with get_connection() as first:
        first.execute("SELECT 1")
    with get_connection() as second:
        second.execute("SELECT 1")
    assert len(pooled) == 1
    assert pooled[0].closed == 0  # still alive for the next request


def test_closed_connection_reconnects(pooled):
    with get_connection():
        pass
    pooled[0].closed = 1
    with get_connection():
        pass
    assert len(pooled) == 2


def test_connection_failure_discards_slot_and_raises(pooled):
    with get_connection():
        pass
    pooled[0].fail_on_execute = True
    with pytest.raises(OperationalError):
        with get_connection() as conn:
            conn.execute("SELECT 1")
    # Slot discarded: the next checkout reconnects fresh.
    with get_connection():
        pass
    assert len(pooled) == 2
    assert pooled[1].closed == 0


def test_nested_checkout_gets_dedicated_connection(pooled):
    with get_connection() as outer:
        with get_connection() as inner:
            assert inner._conn is not outer._conn
        # Inner block closed its own connection on exit (old lifecycle).
        assert inner._conn.closed == 1
    assert len(pooled) == 2
    assert outer._conn.closed == 0
