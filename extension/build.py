#!/usr/bin/env python3
"""Pack this directory into `asuswrt.mcpb`, the Claude Desktop extension.

A .mcpb file is a zip with `manifest.json` at its root, so this needs nothing
but the standard library — `npx @anthropic-ai/mcpb pack extension` produces the
same thing if you would rather use the official CLI.

Run it from anywhere:

    python3 extension/build.py

The bundle carries the server as source, not as a binary. `server.type` is
`"uv"` (MCPB manifest 0.4), which means the host resolves Python and the
dependencies itself from the `pyproject.toml` and `uv.lock` shipped alongside
`src/`. That is why nothing here is compiled, no virtualenv is vendored, and
the spec forbids `server/lib` and `server/venv` in the archive.

Everything is written with a fixed timestamp so that rebuilding unchanged
sources produces a byte-identical archive.
"""

from __future__ import annotations

import json
import pathlib
import tomllib
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "asuswrt.mcpb"

# Files taken from extension/, at the archive root. The manifest must be first:
# a reader is entitled to find it without scanning the whole central directory.
FROM_EXTENSION = ["manifest.json", "icon.png"]

# Files taken from the repository root. `pyproject.toml` and `uv.lock` are what
# the host's uv resolves against; `README.md` is there because pyproject names
# it as the project readme, and the build backend fails without it.
FROM_ROOT = ["pyproject.toml", "uv.lock", "README.md"]

# Whole trees taken from the repository root.
TREES = ["src"]

# Never shipped: caches, virtualenvs and build leftovers. A uv bundle resolves
# its own dependencies, so anything pre-resolved here is at best dead weight
# and at worst a stale import shadowing what uv installs.
EXCLUDE_DIRS = {"__pycache__", ".venv", "venv", ".pytest_cache", ".ruff_cache", ".mypy_cache"}
EXCLUDE_SUFFIXES = {".pyc", ".pyo"}
EXCLUDE_NAMES = {".DS_Store"}

EPOCH = (1980, 1, 1, 0, 0, 0)


def wanted(path: pathlib.Path) -> bool:
    """True unless some part of the path is excluded outright."""
    if path.name in EXCLUDE_NAMES or path.suffix in EXCLUDE_SUFFIXES:
        return False
    return not any(part in EXCLUDE_DIRS for part in path.parts)


def collect() -> list[tuple[str, pathlib.Path, int]]:
    """(archive name, source path, unix mode), in a stable order."""
    entries: list[tuple[str, pathlib.Path, int]] = []
    for name in FROM_EXTENSION:
        entries.append((name, HERE / name, 0o644))
    for name in FROM_ROOT:
        entries.append((name, ROOT / name, 0o644))
    for tree in TREES:
        base = ROOT / tree
        for path in sorted(base.rglob("*")):
            if path.is_file() and wanted(path):
                entries.append((str(path.relative_to(ROOT)), path, 0o644))
    return entries


def check_versions() -> str:
    """The three places a version is declared have to agree.

    A bundle whose manifest disagrees with the code it carries is the kind of
    thing nobody notices until a user reports a version that never shipped.
    """
    manifest = json.loads((HERE / "manifest.json").read_text())["version"]
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())["version"]
    if not manifest == project == plugin:
        raise SystemExit(
            "version mismatch: "
            f"manifest.json {manifest}, pyproject {project}, plugin.json {plugin}"
        )
    return manifest


def main() -> None:
    version = check_versions()
    entries = collect()

    missing = [name for name, path, _ in entries if not path.is_file()]
    if missing:
        raise SystemExit(f"missing from the bundle: {', '.join(missing)}")

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, path, mode in entries:
            info = zipfile.ZipInfo(name, date_time=EPOCH)
            info.external_attr = (mode << 16) | (0o100000 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, path.read_bytes())

    print(
        f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size} bytes  "
        f"{len(entries)} files  v{version}"
    )


if __name__ == "__main__":
    main()
