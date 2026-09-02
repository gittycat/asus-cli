"""Layering rules enforced by walking the AST, not by convention.

The dependency direction is one way only: router <- ops <- cli and
router <- ops <- mcp_server. Never mcp_server -> cli, never cli -> mcp_server.
stdout is the JSON-RPC channel for the MCP server, so ops.py and router.py
(shared by both surfaces) must never print to it either.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parent.parent / "src" / "asuswrt"


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(), filename=str(path))


def _imported_names(tree: ast.Module) -> set[str]:
    """Every module name this file imports, dotted paths included."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


def test_mcp_server_does_not_import_the_cli():
    imported = _imported_names(_tree(SRC / "mcp_server.py"))
    assert not any(name == "asuswrt.cli" or name.startswith("asuswrt.cli.") for name in imported)


def test_ops_does_not_import_argparse_or_the_cli():
    imported = _imported_names(_tree(SRC / "ops.py"))
    assert "argparse" not in imported
    assert not any(name == "asuswrt.cli" or name.startswith("asuswrt.cli.") for name in imported)


def _calls_print_or_touches_stdout(tree: ast.Module) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "print":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "stdout":
            return True
    return False


def test_ops_never_prints_or_touches_stdout():
    assert not _calls_print_or_touches_stdout(_tree(SRC / "ops.py"))


def test_router_never_prints_or_touches_stdout():
    assert not _calls_print_or_touches_stdout(_tree(SRC / "router.py"))
