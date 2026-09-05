#!/usr/bin/env python3
"""Build the macOS 27 ARM GitHub Release archive.

The caller downloads the official OpenAI tunnel-client archive and its
SHA256SUMS.txt. This script verifies that upstream checksum, builds this
project's wheel, and emits a self-contained connector archive plus checksum.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import re
import shutil
import struct
import subprocess
import tarfile
import tempfile
import tomllib
import zipfile
from pathlib import Path


ASSET_TEMPLATE = "tunnel-client-v{version}-darwin-arm64.zip"
EXPECTED_FILES = ("tunnel-client", "LICENSE", "NOTICE")
PINNED_SHA256 = {
    "0.0.14": "b540493c5bdbcdbb755700c8e2e16597e28b1569e425007e0f73111047bd6a64",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def expected_checksum(checksums: Path, asset_name: str) -> str:
    pattern = re.compile(rf"^([0-9a-f]{{64}})\s+{re.escape(asset_name)}$")
    matches = [
        match.group(1)
        for line in checksums.read_text().splitlines()
        if (match := pattern.fullmatch(line.strip()))
    ]
    if len(matches) != 1:
        raise SystemExit(f"expected exactly one checksum for {asset_name}")
    return matches[0]


def validate_macho_arm64(path: Path) -> None:
    with path.open("rb") as handle:
        header = handle.read(8)
    if len(header) != 8:
        raise SystemExit("tunnel-client is not a Mach-O executable")
    magic, cpu_type = struct.unpack("<II", header)
    if magic != 0xFEEDFACF or cpu_type != 0x0100000C:
        raise SystemExit("tunnel-client is not a 64-bit ARM Mach-O executable")


def project_version(root: Path) -> str:
    with (root / "pyproject.toml").open("rb") as handle:
        return tomllib.load(handle)["project"]["version"]


def build_wheel(root: Path, destination: Path) -> Path:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(destination)],
        cwd=root,
        check=True,
    )
    wheels = list(destination.glob("asuswrt-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("uv build did not produce exactly one asuswrt wheel")
    return wheels[0]


def add_tree(archive: tarfile.TarFile, root: Path, arc_root: str) -> None:
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root)
        info = archive.gettarinfo(str(path), f"{arc_root}/{relative}")
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        if path.is_file():
            with path.open("rb") as handle:
                archive.addfile(info, handle)
        else:
            archive.addfile(info)


def deterministic_targz(source: Path, destination: Path, arc_root: str) -> None:
    with destination.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w") as archive:
                add_tree(archive, source, arc_root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tunnel-version", required=True)
    parser.add_argument("--tunnel-archive", type=Path, required=True)
    parser.add_argument("--tunnel-checksums", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[2]
    version = project_version(root)
    expected_asset = ASSET_TEMPLATE.format(version=args.tunnel_version)
    pinned = PINNED_SHA256.get(args.tunnel_version)
    if pinned is None:
        raise SystemExit(
            f"tunnel-client {args.tunnel_version} is not pinned; review and add its SHA-256"
        )
    if args.tunnel_archive.name != expected_asset:
        raise SystemExit(f"expected tunnel archive named {expected_asset}")
    actual = sha256(args.tunnel_archive)
    expected = expected_checksum(args.tunnel_checksums, expected_asset)
    if expected != pinned:
        raise SystemExit("upstream checksum does not match the repository's pinned SHA-256")
    if actual != pinned:
        raise SystemExit(
            f"tunnel-client checksum mismatch: expected {pinned}, got {actual}"
        )

    args.output_dir.mkdir(parents=True, exist_ok=True)
    release_name = f"asuswrt-chatgpt-connector-v{version}-macos27-arm64"
    archive_path = args.output_dir / f"{release_name}.tar.gz"

    with tempfile.TemporaryDirectory(prefix="asuswrt-chatgpt-connector-") as temp:
        temp_root = Path(temp)
        wheels = temp_root / "wheels"
        stage = temp_root / release_name
        wheels.mkdir()
        stage.mkdir()
        wheel = build_wheel(root, wheels)
        shutil.copy2(wheel, stage / wheel.name)
        shutil.copy2(root / "packaging" / "chatgpt_connector" / "install.sh", stage / "install.sh")

        with zipfile.ZipFile(args.tunnel_archive) as upstream:
            names = set(upstream.namelist())
            for required in EXPECTED_FILES:
                if required not in names:
                    raise SystemExit(f"upstream tunnel archive is missing {required}")
            for name in names:
                if (
                    name in EXPECTED_FILES
                    or name.endswith("-licenses.txt")
                    or name.endswith(".spdx.json")
                ):
                    target_name = {
                        "LICENSE": "OPENAI-TUNNEL-CLIENT-LICENSE",
                        "NOTICE": "OPENAI-TUNNEL-CLIENT-NOTICE",
                    }.get(name, name)
                    target = stage / target_name
                    with upstream.open(name) as source, target.open("wb") as destination:
                        shutil.copyfileobj(source, destination)

        validate_macho_arm64(stage / "tunnel-client")
        (stage / "install.sh").chmod(0o755)
        (stage / "tunnel-client").chmod(0o755)
        deterministic_targz(stage, archive_path, release_name)

    digest = sha256(archive_path)
    checksum_path = archive_path.with_suffix(archive_path.suffix + ".sha256")
    checksum_path.write_text(f"{digest}  {archive_path.name}\n")
    print(archive_path)
    print(checksum_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
