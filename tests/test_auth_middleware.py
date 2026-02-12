"""Tests for bearer token auth middleware on the HTTP transport."""

import os
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request

import pytest


def _wait_for_port(port, timeout=10):
    """Wait until a port is accepting connections."""
    start = time.time()
    while time.time() - start < timeout:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=1):
                return True
        except OSError:
            time.sleep(0.5)
    return False


MCP_INIT_PAYLOAD = (
    b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":'
    b'{"protocolVersion":"2025-03-26","capabilities":{},'
    b'"clientInfo":{"name":"test","version":"0.1.0"}}}'
)


def _start_server(port, auth_token=None):
    """Start server.py as a subprocess with the given config."""
    env = os.environ.copy()
    env["MCP_TRANSPORT"] = "http"
    env["MCP_PORT"] = str(port)
    env["MCP_HOST"] = "127.0.0.1"
    env["GOOGLE_SERVICE_ACCOUNT_JSON_B64"] = ""
    if auth_token:
        env["MCP_AUTH_TOKEN"] = auth_token
    else:
        env.pop("MCP_AUTH_TOKEN", None)

    return subprocess.Popen(
        [sys.executable, "server.py"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


class TestBearerAuthMiddleware:
    """Integration tests for the bearer token auth middleware."""

    def test_missing_token_returns_401(self):
        """Request without Authorization header is rejected."""
        port = 18780
        proc = _start_server(port, auth_token="test-secret-token")
        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp/",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                data=MCP_INIT_PAYLOAD,
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 401
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)

    def test_wrong_token_returns_401(self):
        """Request with an incorrect Bearer token is rejected."""
        port = 18781
        proc = _start_server(port, auth_token="test-secret-token")
        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp/",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": "Bearer wrong-token",
                },
                data=MCP_INIT_PAYLOAD,
            )
            with pytest.raises(urllib.error.HTTPError) as exc_info:
                urllib.request.urlopen(req, timeout=5)
            assert exc_info.value.code == 401
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)

    def test_correct_token_succeeds(self):
        """Request with the correct Bearer token is allowed through."""
        port = 18782
        token = "test-secret-token"
        proc = _start_server(port, auth_token=token)
        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp/",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {token}",
                },
                data=MCP_INIT_PAYLOAD,
            )
            resp = urllib.request.urlopen(req, timeout=5)
            assert resp.status == 200
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)

    def test_no_auth_env_allows_unauthenticated_access(self):
        """When MCP_AUTH_TOKEN is not set, requests succeed without auth."""
        port = 18783
        proc = _start_server(port, auth_token=None)
        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp/",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                data=MCP_INIT_PAYLOAD,
            )
            resp = urllib.request.urlopen(req, timeout=5)
            assert resp.status == 200
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
