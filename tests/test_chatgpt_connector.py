from __future__ import annotations

import plistlib
import stat
from pathlib import Path

import pytest

from asuswrt.chatgpt_connector import (
    ConnectorError,
    _dotenv_quote,
    LABEL,
    Paths,
    install,
    render_mcp_launcher,
    render_plist,
    render_profile,
    uninstall,
    validate_tunnel_id,
)


TUNNEL_ID = "tunnel_0123456789abcdef0123456789abcdef"


def test_validate_tunnel_id() -> None:
    assert validate_tunnel_id(TUNNEL_ID) == TUNNEL_ID
    for invalid in ("", "tunnel_123", "TUNNEL_0123456789abcdef0123456789abcdef"):
        with pytest.raises(ConnectorError):
            validate_tunnel_id(invalid)


def test_dotenv_quote_preserves_special_characters() -> None:
    assert _dotenv_quote('a b#"c\\d\ne') == '"a b#\\"c\\\\d\\ne"'


def test_profile_uses_file_key_and_local_stdio_command(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    profile = render_profile(paths, TUNNEL_ID)
    assert f'api_key: "file:{paths.runtime_key}"' in profile
    assert 'listen_addr: "127.0.0.1:0"' in profile
    assert f'command: "{paths.mcp_launcher}"' in profile
    assert "sk-" not in profile


@pytest.mark.parametrize(
    ("permission", "writes", "dangerous"),
    [("read-only", "0", "0"), ("writes", "1", "0"), ("dangerous", "1", "1")],
)
def test_launcher_permission_gates(
    tmp_path: Path, permission: str, writes: str, dangerous: str
) -> None:
    launcher = render_mcp_launcher(Paths(tmp_path), permission, Path("/venv/bin/python"))
    assert f"ASUSWRT_MCP_ALLOW_WRITES={writes}" in launcher
    assert f"ASUSWRT_MCP_ALLOW_DANGEROUS={dangerous}" in launcher
    assert "exec '/venv/bin/python' -m asuswrt.mcp_server" in launcher


def test_plist_contains_no_secrets(tmp_path: Path) -> None:
    paths = Paths(tmp_path)
    payload = plistlib.loads(render_plist(paths))
    assert payload["Label"] == LABEL
    assert payload["RunAtLoad"] is True
    assert payload["ProgramArguments"] == [
        str(paths.tunnel_client),
        "run",
        "--profile-file",
        str(paths.profile),
    ]
    assert "EnvironmentVariables" not in payload


def test_install_writes_private_files_without_starting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = Paths(tmp_path / "home")
    source = tmp_path / "tunnel-client"
    source.write_text("binary")
    source.chmod(0o700)
    paths.router_env.parent.mkdir(parents=True)
    paths.router_env.write_text("ROUTER_PASS=test\n")
    monkeypatch.setattr("asuswrt.chatgpt_connector.require_supported_platform", lambda: None)

    install(
        paths=paths,
        tunnel_client=source,
        tunnel_id=TUNNEL_ID,
        runtime_key="secret-runtime-key",
        permission="read-only",
        start=False,
        python=Path("/venv/bin/python"),
    )

    assert paths.tunnel_client.read_text() == "binary"
    assert paths.runtime_key.read_text() == "secret-runtime-key\n"
    assert stat.S_IMODE(paths.runtime_key.stat().st_mode) == 0o600
    assert stat.S_IMODE(paths.mcp_launcher.stat().st_mode) == 0o700
    assert paths.plist.is_file()


def test_uninstall_keeps_router_credentials_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths = Paths(tmp_path)
    paths.state.mkdir(parents=True)
    paths.plist.parent.mkdir(parents=True)
    paths.plist.write_text("plist")
    paths.router_env.parent.mkdir(parents=True)
    paths.router_env.write_text("ROUTER_PASS=test\n")
    monkeypatch.setattr("asuswrt.chatgpt_connector.stop_service", lambda **_: None)

    uninstall(paths)

    assert not paths.state.exists()
    assert not paths.plist.exists()
