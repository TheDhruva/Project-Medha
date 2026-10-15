"""Targeted unit tests: node port wiring + readiness failure diagnosis.

No daemon required: profile detection and failure classification are pure,
and deploy wiring is verified with the docker_ops layer monkeypatched.
"""

from __future__ import annotations

import asyncio
import json

from app.execution import docker_ops
from app.execution.profiles import _port_from_scripts, detect_profile
from app.execution.real_executor import _classify_readiness_failure


def _pkg(scripts: dict) -> dict:
    return {"scripts": scripts}


def test_port_from_scripts_parses_explicit_ports():
    assert _port_from_scripts(_pkg({"start": "next start -p 3000"})) == 3000
    assert _port_from_scripts(_pkg({"start": "next start --port 4000"})) == 4000
    assert _port_from_scripts(_pkg({"start": "next start --port=5001"})) == 5001
    assert _port_from_scripts(_pkg({"start": "PORT=5002 next start"})) == 5002


def test_port_from_scripts_ignores_unpinned_and_invalid():
    assert _port_from_scripts(_pkg({"start": "next start"})) is None
    assert _port_from_scripts(_pkg({"start": "node server.js"})) is None
    assert _port_from_scripts(_pkg({"start": "next start -p 99999"})) is None
    assert _port_from_scripts({}) is None
    assert _port_from_scripts({"scripts": None}) is None


def test_node_profile_prefers_script_port_with_port_env(tmp_path):
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "next start -p 3000"}}), encoding="utf-8"
    )
    profile = detect_profile(tmp_path, target_port=8080)
    assert profile.name == "node"
    assert profile.port == 3000
    assert profile.env == {"PORT": "3000", "HOSTNAME": "0.0.0.0"}


def test_node_profile_defaults_to_target_port_with_port_env(tmp_path):
    # The Next.js failure case: `next start` defaults to 3000 while MEDHA
    # publishes target_port — PORT env must bind the app to the mapping.
    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "next start"}}), encoding="utf-8"
    )
    profile = detect_profile(tmp_path, target_port=8080)
    assert profile.port == 8080
    assert profile.env == {"PORT": "8080", "HOSTNAME": "0.0.0.0"}


def test_classify_connection_refused_names_mapping():
    msg = _classify_readiness_failure(
        {"status": "timed_out",
         "reason": "<urlopen error [WinError 10061] No connection could be made>"},
        host_port=8080, container_port=8080, path="/",
    )
    assert "refused" in msg
    assert "127.0.0.1:8080" in msg
    assert "container:8080" in msg
    assert "different container port" in msg


def test_classify_timeout_http_and_generic_stay_distinct():
    timeout_msg = _classify_readiness_failure(
        {"status": "timed_out", "reason": "timed out"}, host_port=8080,
        container_port=8080, path="/",
    )
    assert "timed out" in timeout_msg
    http_msg = _classify_readiness_failure(
        {"status": "timed_out", "reason": "http_500"}, host_port=8080,
        container_port=8080, path="/",
    )
    assert "unhealthy HTTP" in http_msg
    generic_msg = _classify_readiness_failure(
        {"status": "failed", "reason": "non_loopback_target"}, host_port=8080,
        container_port=8080, path="/",
    )
    assert "non_loopback_target" in generic_msg


def test_deploy_wires_port_env_and_probes_published_port(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.execution.real_executor import RealExecutor

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "next start"}}), encoding="utf-8"
    )
    captured: dict = {}

    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(docker_ops, "build_image", lambda **k: "sha256:abc")
    monkeypatch.setattr(docker_ops, "create_network", lambda deployment_id: "medha_net")

    def fake_start(**kwargs):
        captured["start"] = kwargs
        return "medha_c1_app"

    def fake_ready(port, **kwargs):
        captured["ready_port"] = port
        captured["ready_path"] = kwargs.get("path")
        return {"status": "ready", "http_status": 200, "attempts": 1}

    monkeypatch.setattr(docker_ops, "start_container", fake_start)
    monkeypatch.setattr(docker_ops, "container_running", lambda name: True)
    monkeypatch.setattr(
        docker_ops, "container_state",
        lambda name, **k: {
            "available": True, "running": True, "exit_code": 0,
            "oom_killed": False,
            "ports": {"18082/tcp": [{"host_ip": "127.0.0.1",
                                     "host_port": "18082"}]},
        },
    )
    monkeypatch.setattr(docker_ops, "wait_http_readiness", fake_ready)
    monkeypatch.setattr(
        docker_ops, "container_logs",
        lambda name, **k: {"available": True, "stdout": "", "stderr": ""},
    )

    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_nodeport1", checkout=tmp_path, target_port=18082,
            readiness_timeout=5, build_timeout=60,
        )
    )
    assert outcome.ok, outcome.message
    assert outcome.port == 18082
    # App is told to listen on the published container port (was: Next.js
    # default 3000 vs published 8080 → WinError 10061 on the host probe).
    assert captured["start"]["env"] == {"PORT": "18082", "HOSTNAME": "0.0.0.0"}
    assert captured["start"]["publish_port"] == 18082
    assert captured["start"]["container_port"] == 18082
    assert captured["ready_port"] == 18082
    assert captured["ready_path"] == "/"
    # Persisted evidence names the actual probe target and port mapping.
    assert outcome.readiness["stage"] == "ready"
    assert outcome.readiness["probe_url"] == "http://127.0.0.1:18082/"
    assert outcome.readiness["host_port"] == 18082
    assert outcome.readiness["container_port"] == 18082
    assert "container:18082" in outcome.readiness["mapping"]


def test_deploy_operator_env_wins_over_profile_defaults(tmp_path, monkeypatch):
    from app.core.config import get_settings
    from app.execution.real_executor import RealExecutor

    monkeypatch.setenv("MEDHA_EXECUTOR_MODE", "real")
    monkeypatch.setenv("MEDHA_DOCKER_EXECUTE", "true")
    get_settings.cache_clear()

    (tmp_path / "package.json").write_text(
        json.dumps({"scripts": {"start": "next start"}}), encoding="utf-8"
    )
    captured: dict = {}

    monkeypatch.setattr(docker_ops, "docker_cli_available", lambda: True)
    monkeypatch.setattr(docker_ops, "docker_daemon_running", lambda: True)
    monkeypatch.setattr(docker_ops, "build_image", lambda **k: "sha256:abc")
    monkeypatch.setattr(docker_ops, "create_network", lambda deployment_id: "medha_net")

    def fake_start(**kwargs):
        captured["env"] = kwargs.get("env")
        return "medha_c1_app"

    monkeypatch.setattr(docker_ops, "start_container", fake_start)
    monkeypatch.setattr(docker_ops, "container_running", lambda name: True)
    monkeypatch.setattr(
        docker_ops, "container_state",
        lambda name, **k: {
            "available": True, "running": True, "exit_code": 0,
            "oom_killed": False,
            "ports": {"18083/tcp": [{"host_ip": "127.0.0.1",
                                     "host_port": "18083"}]},
        },
    )
    monkeypatch.setattr(
        docker_ops, "wait_http_readiness",
        lambda port, **k: {"status": "ready", "http_status": 200, "attempts": 1},
    )
    monkeypatch.setattr(
        docker_ops, "container_logs",
        lambda name, **k: {"available": True, "stdout": "", "stderr": ""},
    )

    outcome = asyncio.run(
        RealExecutor().deploy(
            deployment_id="dep_nodeport2", checkout=tmp_path, target_port=18083,
            readiness_timeout=5, build_timeout=60,
            authorized_env={"PORT": "3000"},
        )
    )
    assert outcome.ok, outcome.message
    assert captured["env"] == {"PORT": "3000", "HOSTNAME": "0.0.0.0"}
