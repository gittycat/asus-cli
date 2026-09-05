#!/bin/sh
# Launcher for the ASUS Router Control MCP Bundle.
#
# The bundle does not carry the server. `asuswrt-mcp` is installed separately
# with uv, which writes a self-contained script — its shebang is an absolute
# path into its own virtualenv — into ~/.local/bin. Claude Desktop starts its
# child processes without a login shell, so PATH here is close to empty and
# the candidates below have to be spelled out.
#
# ASUSWRT_MCP_BIN comes from the extension's "Path to asuswrt-mcp" setting.

set -eu

for candidate in \
    "${ASUSWRT_MCP_BIN:-}" \
    "$HOME/.local/bin/asuswrt-mcp" \
    "/opt/homebrew/bin/asuswrt-mcp" \
    "/usr/local/bin/asuswrt-mcp"
do
    if [ -n "$candidate" ] && [ -x "$candidate" ]; then
        exec "$candidate" "$@"
    fi
done

# stdout is the JSON-RPC channel, so this has to go to stderr, where Claude
# Desktop files it under ~/Library/Logs/Claude/mcp-server-asuswrt.log.
cat >&2 <<'MSG'
asuswrt-mcp was not found.

Install it, then reopen Claude Desktop:

  uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-ai-tools"

If it is installed somewhere else, put the full path in the extension's
"Path to asuswrt-mcp" setting (Settings -> Extensions -> ASUS Router Control).
MSG
exit 1
