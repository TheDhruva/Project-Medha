"""Focused tests: staged real-execution failure classification (mocked Docker).

Each stage — immediate exit, unmapped port, connection refused, mid-probe
exit, HTTP error, timeout, success — yields a distinct code/stage plus
probe-target, port-mapping, container-state, and log-tail evidence.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from app.execution import docker_ops
from app.execution.real_executor import RealExecutor

PORT = 18091


def _checkout(tmp_path, port=PORT):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "node server.js"}}), encoding="utf-8"
    )
    return tmp_path


def _base_mocks(monkeypatch, *, states, wait_result):
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(docker_ops, "build_image", lambda **k: "sha256:abc")
    monkeypatch.setattr(docker_ops, "create_network", lambda deployment_id: "medha_net")
    monkeypatch.setattr(docker_ops, "start_container", lambda **k: "medha_c1_app")
    state_iter = iter(states)
    monkeypatch.setattr(docker_ops, "container_state", lambda name, **k: next(state_iter))
    monkeypatch.setattr(docker_ops, "container_running", lambda name: True)
    monkeypatch.setattr(docker_ops, "wait_http_readiness", lambda port, **k: wait_result)
    monkeypatch.setattr(
        docker_ops, "container_logs",
        lambda name, **k: {"available": True, "stdout": "line1\nline2", "stderr": "boom"},
    )


def _running_state(port=PORT):
    return {
        "available": True, "running": True, "exit_code": 0, "oom_killed": False,
        "ports": {f"{port}/tcp": [{"host_ip": "127.0.0.1", "host_port": str(port)}]},
    }


def _run(checkout, **kw):
    return asyncio.run(RealExecutor().deploy(deployment_id="dep_stage1", checkout=checkout,
                                             target_port=PORT, readiness_timeout=5,
                                             build_timeout=60, **kw))


def test_immediate_exit_reports_start_failed_with_exit_code(tmp_path, monkeypatch):
    _base_mocks(monkeypatch,
                states=[{"available": True, "running": False, "exit_code": 1,
                         "oom_killed": False, "ports": {}}],
                wait_result={"status": "ready"})
    outcome = _run(_checkout(tmp_path))
    assert outcome.ok is False
    assert outcome.code == "START_FAILED"
    assert "exit_code=1" in outcome.message
    assert outcome.readiness["stage"] == "container_exited"
    assert outcome.readiness["container"]["exit_code"] == 1
    assert "boom" in outcome.readiness["log_tail"]


def test_unmapped_port_refuses_to_probe(tmp_path, monkeypatch):
    state = _running_state()
    state["ports"] = {}
    _base_mocks(monkeypatch, states=[state], wait_result={"status": "ready"})
    outcome = _run(_checkout(tmp_path))
    assert outcome.ok is False
    assert outcome.code == "PORT_MAPPING_FAILED"
    assert outcome.readiness["stage"] == "port_unmapped"
    assert outcome.readiness["probe_url"] == f"http://127.0.0.1:{PORT}/"


def test_connection_refused_stage(tmp_path, monkeypatch):
    _base_mocks(
        monkeypatch, states=[_running_state(), _running_state()],
        wait_result={"status": "timed_out",
                     "reason": "<urlopen error [WinError 10061] refused>",
                     "attempts": 3, "probe_url": f"http://127.0.0.1:{PORT}/"},
    )
    outcome = _run(_checkout(tmp_path))
    assert outcome.code == "READINESS_FAILED"
    assert outcome.readiness["stage"] == "connection_refused"
    assert outcome.readiness["attempts"] == 3
    assert outcome.readiness["host_port"] == PORT
    assert outcome.readiness["container_port"] == PORT
    assert f"127.0.0.1:{PORT}" in outcome.message


def test_mid_probe_exit_stage(tmp_path, monkeypatch):
    exited = {"available": True, "running": False, "exit_code": 137,
              "oom_killed": True, "ports": {}}
    _base_mocks(
        monkeypatch, states=[_running_state(), exited],
        wait_result={"status": "timed_out", "reason": "timed out", "attempts": 2},
    )
    outcome = _run(_checkout(tmp_path))
    assert outcome.code == "READINESS_FAILED"
    assert outcome.readiness["stage"] == "container_exited"
    assert outcome.readiness["container"]["exit_code"] == 137
    assert "exited during readiness probing" in outcome.message


def test_http_error_and_timeout_stages(tmp_path, monkeypatch):
    _base_mocks(
        monkeypatch, states=[_running_state(), _running_state()],
        wait_result={"status": "timed_out", "reason": "http_500", "attempts": 2},
    )
    outcome = _run(_checkout(tmp_path))
    assert outcome.readiness["stage"] == "http_error"

    _base_mocks(
        monkeypatch, states=[_running_state(), _running_state()],
        wait_result={"status": "timed_out", "reason": "timed out", "attempts": 2},
    )
    outcome = _run(_checkout(tmp_path))
    assert outcome.readiness["stage"] == "timeout"


def test_success_records_probe_target_and_mapping(tmp_path, monkeypatch):
    captured = {}
    _base_mocks(
        monkeypatch, states=[_running_state(), _running_state()],
        wait_result={"status": "ready", "http_status": 200, "attempts": 4,
                     "probe_url": f"http://127.0.0.1:{PORT}/"},
    )
    orig_start = docker_ops.start_container
    monkeypatch.setattr(
        docker_ops, "start_container",
        lambda **k: (captured.update(k) or "medha_c1_app"),
    )
    outcome = _run(_checkout(tmp_path))
    assert outcome.ok, outcome.message
    assert captured["publish_port"] == PORT
    assert captured["container_port"] == PORT
    assert outcome.readiness["stage"] == "ready"
    assert outcome.readiness["probe_url"] == f"http://127.0.0.1:{PORT}/"
    assert outcome.readiness["observed_ports"]
    assert outcome.runtime_spec["profile"] == "node"


def test_unsupported_checkout_fails_closed_without_docker(tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()
    (tmp_path / "README.md").write_text("nothing", encoding="utf-8")
    outcome = asyncio.run(
        RealExecutor().deploy(deployment_id="dep_stage2", checkout=tmp_path)
    )
    assert outcome.ok is False
    assert outcome.code == "UNSUPPORTED_STACK"
    assert outcome.container is None
