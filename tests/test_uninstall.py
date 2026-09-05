import json
import os
from pathlib import Path
import subprocess
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "uninstall.sh"


def run_uninstall(tmp_path: Path, state: dict, *args: str, project_mcp: dict | None = None):
    home = tmp_path / "home"
    home.mkdir(exist_ok=True)
    (home / ".claude.json").write_text(json.dumps(state))
    if project_mcp is not None:
        (tmp_path / ".mcp.json").write_text(json.dumps(project_mcp))

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "python3").symlink_to(sys.executable)
    env = os.environ.copy()
    env.update(HOME=str(home), PATH=f"{bin_dir}:/usr/bin:/bin")

    return subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=tmp_path,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def test_uninstall_ignores_non_mcp_asuswrt_metadata(tmp_path):
    result = run_uninstall(
        tmp_path,
        {
            "skillUsage": {"asuswrt": {"usageCount": 5}},
            "projects": {"/example": {"exampleFiles": ["asuswrt.mcpb"]}},
        },
    )

    assert "claude mcp remove asuswrt" not in result.stdout
    assert "Nothing found. This Mac is already clean." in result.stdout


@pytest.mark.parametrize(
    ("state", "project_mcp"),
    [
        ({"mcpServers": {"asuswrt": {}}}, None),
        ({"projects": {"/example": {"mcpServers": {"asuswrt": {}}}}}, None),
        ({}, {"mcpServers": {"asuswrt": {}}}),
    ],
)
def test_uninstall_detects_only_real_mcp_entries(tmp_path, state, project_mcp):
    result = run_uninstall(tmp_path, state, project_mcp=project_mcp)

    assert "asuswrt MCP server is registered" in result.stdout
    assert "1 items would be removed" in result.stdout


@pytest.mark.parametrize(
    ("args", "expected"),
    [
        (("--yes",), "only the retained .claude/ may appear"),
        (("--yes", "--repo-all"), "should print nothing"),
    ],
)
def test_uninstall_verification_accounts_for_retained_claude_dir(tmp_path, args, expected):
    executable = tmp_path / "home" / ".local" / "bin" / "asuswrt"
    executable.parent.mkdir(parents=True)
    executable.touch()

    result = run_uninstall(tmp_path, {}, *args)

    assert expected in result.stdout
