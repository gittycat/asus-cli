#!/usr/bin/env python3
"""Pack this directory into `asuswrt.mcpb`, the Claude Desktop extension.

A .mcpb file is a zip with `manifest.json` at its root, so this needs nothing
but the standard library — `npx @anthropic-ai/mcpb pack extension` produces the
same thing if you would rather use the official CLI.

Run it from anywhere:

    python3 extension/build.py

The bundle deliberately does not contain the server. `asuswrt-mcp` needs Python
3.13 and Claude Desktop supplies no Python runtime, so the bundle ships a
launcher that finds the copy `uv tool install` already put in ~/.local/bin.
"""

from __future__ import annotations

import json
import pathlib
import tomllib
import zipfile

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
OUT = HERE / "asuswrt.mcpb"

# (path relative to extension/, unix mode)
CONTENTS = [
    ("manifest.json", 0o644),
    ("icon.png", 0o644),
    ("server/launch.sh", 0o755),
    ("server/launch.cmd", 0o644),
]


def main() -> None:
    manifest = json.loads((HERE / "manifest.json").read_text())
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    if manifest["version"] != project:
        raise SystemExit(
            f"version mismatch: manifest.json {manifest['version']} != pyproject {project}"
        )

    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for name, mode in CONTENTS:
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.external_attr = (mode << 16) | (0o100000 << 16)
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, (HERE / name).read_bytes())

    print(f"{OUT.relative_to(ROOT)}  {OUT.stat().st_size} bytes  v{manifest['version']}")


if __name__ == "__main__":
    main()
