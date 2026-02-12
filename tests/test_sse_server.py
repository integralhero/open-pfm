"""Tests for HTTP (Streamable HTTP) server startup and connectivity."""

import os
import signal
import socket
import subprocess
import sys
import time

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


class TestHTTPServer:
    """Integration tests for the Streamable HTTP transport mode."""

    def test_server_starts_and_listens(self):
        port = 18765
        env = os.environ.copy()
        env["MCP_TRANSPORT"] = "http"
        env["MCP_PORT"] = str(port)
        env["MCP_HOST"] = "127.0.0.1"
        # No credentials — server should still start (auth is lazy)
        env["GOOGLE_SERVICE_ACCOUNT_JSON_B64"] = ""

        proc = subprocess.Popen(
            [sys.executable, "server.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"

            # Verify the /mcp endpoint responds (POST required for Streamable HTTP)
            import urllib.request
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/mcp/",
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                data=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}',
            )
            resp = urllib.request.urlopen(req, timeout=5)
            assert resp.status == 200
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)

    def test_legacy_sse_env_resolves_to_http(self):
        """Setting MCP_TRANSPORT=sse should still start the server on HTTP."""
        port = 18767
        env = os.environ.copy()
        env["MCP_TRANSPORT"] = "sse"
        env["MCP_PORT"] = str(port)
        env["MCP_HOST"] = "127.0.0.1"
        env["GOOGLE_SERVICE_ACCOUNT_JSON_B64"] = ""

        proc = subprocess.Popen(
            [sys.executable, "server.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)

    def test_server_uses_configured_port(self):
        port = 18766
        env = os.environ.copy()
        env["MCP_TRANSPORT"] = "http"
        env["MCP_PORT"] = str(port)
        env["MCP_HOST"] = "127.0.0.1"
        env["GOOGLE_SERVICE_ACCOUNT_JSON_B64"] = ""

        proc = subprocess.Popen(
            [sys.executable, "server.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

        try:
            assert _wait_for_port(port), f"Server did not start on port {port}"

            # Wrong port should not be listening
            with pytest.raises(OSError):
                with socket.create_connection(("127.0.0.1", port + 100), timeout=1):
                    pass
        finally:
            proc.send_signal(signal.SIGTERM)
            proc.wait(timeout=5)
