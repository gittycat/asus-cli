"""The one test that catches stdout contamination for real.

Everything else in this suite calls the tool functions directly in-process.
That proves the payloads are right, but it cannot prove stdout stayed clean —
a stray `print` anywhere on the import path would only show up once the
process actually talks JSON-RPC over stdio. So this starts the real
`asuswrt-mcp` entry point as a subprocess, with no router configured, and
checks that every line on stdout parses as JSON-RPC. No tool is invoked —
that needs a router.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

BIN = shutil.which("asuswrt-mcp") or str(Path(sys.executable).parent / "asuswrt-mcp")


def _clean_env(tmp_path: Path) -> dict[str, str]:
    """No router configured: strip anything that could point at a real .env."""
    env = dict(os.environ)
    env.pop("ROUTER_PASS", None)
    env.pop("ASUSWRT_ENV_FILE", None)
    env["ASUSWRT_MCP_ALLOW_WRITES"] = ""
    env["ASUSWRT_MCP_ALLOW_DANGEROUS"] = ""
    # A cwd with no .env of its own, so config_paths() finds nothing there.
    env["HOME"] = str(tmp_path)
    return env


@pytest.fixture
def server(tmp_path):
    proc = subprocess.Popen(
        [BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        cwd=tmp_path,
        env=_clean_env(tmp_path),
    )
    try:
        yield proc
    finally:
        proc.stdin.close()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _send(proc: subprocess.Popen, message: dict) -> None:
    proc.stdin.write(json.dumps(message) + "\n")
    proc.stdin.flush()


def test_initialize_and_tools_list_are_clean_jsonrpc_and_match_the_default_gate(server):
    _send(
        server,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0.0"},
            },
        },
    )
    init_line = server.stdout.readline()
    init_response = json.loads(init_line)  # every stdout line must parse as JSON-RPC
    assert init_response["jsonrpc"] == "2.0"
    assert "result" in init_response

    _send(server, {"jsonrpc": "2.0", "method": "notifications/initialized"})
    _send(server, {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})

    tools_line = server.stdout.readline()
    tools_response = json.loads(tools_line)
    assert tools_response["jsonrpc"] == "2.0"
    assert "error" not in tools_response

    names = {tool["name"] for tool in tools_response["result"]["tools"]}

    # No gates set: only the 15 read tools are registered.
    assert names == {
        "get_overview",
        "get_system",
        "get_health",
        "get_wan",
        "get_dns",
        "get_led",
        "get_upnp",
        "list_clients",
        "get_firewall_and_filters",
        "get_parental_control",
        "list_port_forwards",
        "list_guest_networks",
        "get_wireless",
        "check_firmware_update",
        "get_nvram",
    }

    for tool in tools_response["result"]["tools"]:
        assert tool["annotations"]["readOnlyHint"] is True
