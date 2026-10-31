"""Unit tests for Docker CLI guards — no daemon required (pure validation)."""

from __future__ import annotations

import pytest

from app.execution import docker_ops
from app.execution.docker_ops import (
    ALLOWED_VERBS,
    DockerOpsError,
    host_port_of,
    probe_http_readiness,
)


def test_safe_image_accepts_pinned_busybox():
    assert docker_ops._safe_image("busybox:1.36") is True


def test_safe_image_rejects_malicious_and_malformed():
    assert docker_ops._safe_image("") is False
    assert docker_ops._safe_image("x" * 201) is False
    assert docker_ops._safe_image("alpine; rm -rf /") is False
    assert docker_ops._safe_image("img$(whoami)") is False
    assert docker_ops._safe_image("a`id`b") is False
    assert docker_ops._safe_image(" busybox:1.36") is False  # spaces rejected
    assert docker_ops._safe_image("ubuntu:latest --privileged") is False


def test_safe_port_mapping_accepts_valid_rejects_dangerous():
    assert docker_ops._safe_port_mapping("8080:80") is True
    assert docker_ops._safe_port_mapping("80") is True
    assert docker_ops._safe_port_mapping("0:80") is False
    assert docker_ops._safe_port_mapping("99999:80") is False
    assert docker_ops._safe_port_mapping("abc:80") is False
    assert docker_ops._safe_port_mapping("8080:80:90") is False
    assert docker_ops._safe_port_mapping("") is False


def test_safe_env_key_rejects_injection():
    assert docker_ops._safe_env_key("DATABASE_URL") is True
    assert docker_ops._safe_env_key("") is False
    assert docker_ops._safe_env_key("A" * 65) is False
    assert docker_ops._safe_env_key("EVIL;CMD") is False
    assert docker_ops._safe_env_key("a-b") is False


def test_command_allowlist_rejects_build_exec_privileged_paths():
    for verb in ("build", "exec", "runx", "", "cp", "volume"):
        assert verb not in ALLOWED_VERBS
    for verb in ("run", "stop", "rm", "ps", "inspect", "network", "version"):
        assert verb in ALLOWED_VERBS
    with pytest.raises(DockerOpsError) as exc:
        docker_ops._run(["build", "."], check=False)
    assert exc.value.code == "VERB_REJECTED"


def test_start_container_rejects_unsafe_image_and_env(tmp_path, monkeypatch):
    # Mock the subprocess layer so pure validation is exercised (no daemon).
    class Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    monkeypatch.setattr(docker_ops, "_run", lambda *a, **k: Proc())
    with pytest.raises(DockerOpsError) as exc:
        docker_ops.start_container(
            deployment_id="dep_test123456",
            service="backend",
            image="evil; rm -rf /",
            network="medha_net",
        )
    assert exc.value.code == "IMAGE_REJECTED"
    with pytest.raises(DockerOpsError) as exc:
        docker_ops.start_container(
            deployment_id="dep_test123456",
            service="backend",
            image="busybox:1.36",
            network="medha_net",
            ports=["notaport:80"],
        )
    assert exc.value.code == "PORT_REJECTED"
    with pytest.raises(DockerOpsError) as exc:
        docker_ops.start_container(
            deployment_id="dep_test123456",
            service="backend",
            image="busybox:1.36",
            network="medha_net",
            env={"BAD-KEY": "x"},
        )
    assert exc.value.code == "ENV_REJECTED"


def test_ownership_refuses_foreign_container(monkeypatch):
    # Simulate `docker inspect` returning foreign labels.
    class Proc:
        returncode = 0
        stdout = '{"com.medha.deployment_id": "dep_other", "com.medha.managed": "true"}'

    monkeypatch.setattr(docker_ops, "_run", lambda *a, **k: Proc())
    assert docker_ops._is_medha_owned("some_container", "dep_mine") is False
    assert (
        docker_ops.stop_and_remove_container("some_container", deployment_id="dep_mine")
        is False
    )


def test_ownership_accepts_own_labels(monkeypatch):
    class Proc:
        returncode = 0
        stdout = '{"com.medha.deployment_id": "dep_mine", "com.medha.managed": "true"}'

    monkeypatch.setattr(docker_ops, "_run", lambda *a, **k: Proc())
    assert docker_ops._is_medha_owned("medha_x_backend", "dep_mine") is True


def test_host_port_of_parses_mappings():
    assert host_port_of("8080:80") == 8080
    assert host_port_of("80") == 80
    assert host_port_of("nope:80") is None


def test_probe_http_readiness_never_raises():
    # No server on this high port: must report unreachable, not raise.
    result = probe_http_readiness(48151, timeout=1.0)
    assert result["status"] == "unreachable"
    assert probe_http_readiness(0)["status"] == "skipped"
    assert probe_http_readiness(99999)["status"] == "skipped"
    assert probe_http_readiness(80, host="203.0.113.1")["status"] == "skipped"


def test_probe_http_readiness_passes_against_local_server():
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        result = probe_http_readiness(port, timeout=3.0)
    finally:
        server.shutdown()
        thread.join(timeout=5)
    assert result["status"] == "passed"
    assert result["http_status"] == 200


# --- HTTP status regression coverage (readiness contract: below 500 = ready) ---


def _serve(status: int):
    """Local HTTP server answering every GET with *status*; returns (server, port)."""
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(status)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, server.server_address[1]


def test_probe_http_readiness_passes_on_404_missing_root_route():
    # A service that answers 404 on / is responding, not unreachable.
    server, port = _serve(404)
    try:
        result = probe_http_readiness(port, timeout=3.0)
    finally:
        server.shutdown()
    assert result["status"] == "passed"
    assert result["http_status"] == 404


def test_wait_http_readiness_ready_immediately_on_404():
    from app.execution.docker_ops import wait_http_readiness

    server, port = _serve(404)
    try:
        result = wait_http_readiness(
            port, path="/", timeout=5.0, grace=0.0, interval=0.5
        )
    finally:
        server.shutdown()
    # Must not burn the full readiness budget against a responding service.
    assert result["status"] == "ready"
    assert result["http_status"] == 404


def test_wait_http_readiness_keeps_polling_on_5xx_then_times_out():
    from app.execution.docker_ops import wait_http_readiness

    server, port = _serve(503)
    try:
        result = wait_http_readiness(
            port, path="/", timeout=2.0, grace=0.0, interval=0.5
        )
    finally:
        server.shutdown()
    # 5xx is not ready yet (may still be starting) but is classified as HTTP.
    assert result["status"] == "timed_out"
    assert result["reason"] == "http_503"


def test_probe_http_readiness_reports_5xx_as_unreachable():
    server, port = _serve(503)
    try:
        result = probe_http_readiness(port, timeout=3.0)
    finally:
        server.shutdown()
    assert result["status"] == "unreachable"
    assert result["http_status"] == 503


def test_probe_and_wait_report_connection_refusal_distinctly():
    import socket

    from app.execution.docker_ops import wait_http_readiness

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()  # nothing is listening now
    probe = probe_http_readiness(port, timeout=1.0)
    assert probe["status"] == "unreachable"
    waited = wait_http_readiness(
        port, path="/", timeout=1.5, grace=0.0, interval=0.5
    )
    assert waited["status"] == "timed_out"
    assert "refused" in waited["reason"].lower() or "10061" in waited["reason"]


def test_wait_http_readiness_times_out_when_server_never_responds():
    import socket
    import threading

    from app.execution.docker_ops import wait_http_readiness

    # Accepts connections but never replies: probe must hit its own timeouts.
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(5)
    port = listener.getsockname()[1]
    held: list[socket.socket] = []

    def accept_forever():
        while True:
            try:
                held.append(listener.accept()[0])
            except OSError:
                return

    threading.Thread(target=accept_forever, daemon=True).start()
    try:
        waited = wait_http_readiness(
            port, path="/", timeout=3.0, grace=0.0, interval=0.5
        )
    finally:
        listener.close()
    assert waited["status"] == "timed_out"
    assert waited["reason"]  # a diagnostic, not a silent timeout
