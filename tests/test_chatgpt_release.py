from __future__ import annotations

import importlib.util
import struct
from pathlib import Path

import pytest


SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "packaging"
    / "chatgpt_connector"
    / "build_release.py"
)
SPEC = importlib.util.spec_from_file_location("chatgpt_release_builder", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
release_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_builder)


def test_expected_checksum_requires_one_exact_asset(tmp_path: Path) -> None:
    checksums = tmp_path / "SHA256SUMS.txt"
    digest = "a" * 64
    checksums.write_text(
        f"{digest}  tunnel-client-v1.2.3-darwin-arm64.zip\n"
        f"{'b' * 64}  tunnel-client-v1.2.3-linux-arm64.tar.gz\n"
    )

    assert (
        release_builder.expected_checksum(
            checksums, "tunnel-client-v1.2.3-darwin-arm64.zip"
        )
        == digest
    )
    with pytest.raises(SystemExit, match="exactly one checksum"):
        release_builder.expected_checksum(checksums, "missing.zip")


def test_validate_macho_arm64_rejects_other_architectures(tmp_path: Path) -> None:
    executable = tmp_path / "tunnel-client"
    executable.write_bytes(struct.pack("<II", 0xFEEDFACF, 0x0100000C))
    release_builder.validate_macho_arm64(executable)

    executable.write_bytes(struct.pack("<II", 0xFEEDFACF, 0x01000007))
    with pytest.raises(SystemExit, match="64-bit ARM"):
        release_builder.validate_macho_arm64(executable)


def test_release_archive_is_reproducible(tmp_path: Path) -> None:
    source = tmp_path / "source"
    source.mkdir()
    executable = source / "tunnel-client"
    executable.write_bytes(b"binary")
    executable.chmod(0o755)
    first = tmp_path / "first.tar.gz"
    second = tmp_path / "second.tar.gz"

    release_builder.deterministic_targz(source, first, "release")
    release_builder.deterministic_targz(source, second, "release")

    assert release_builder.sha256(first) == release_builder.sha256(second)
