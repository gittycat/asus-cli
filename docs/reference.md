# Reference

Nothing here is needed to install or use the tool. It is here for edge cases,
and for the agent reading this file. Start with the
[README](../README.md).

## Where the password is read from

First match wins:

1. `$ASUSWRT_ENV_FILE`, if you set it
2. `.env` in the current directory
3. `~/.config/asuswrt/.env`

The CLI and the MCP server look in the same places. If a command reports the
password is missing, it prints every path it searched.

## What `uv tool install` puts where

`asuswrt`, `asuswrt-mcp` and `asuswrt-probe` land in `~/.local/bin`. Run
`uv tool update-shell` once if that directory is not on your `PATH`. GUI apps
never inherit your shell `PATH`, which is why the Claude Desktop config uses an
absolute path.

To install from a local clone instead of GitHub:

```bash
git clone https://github.com/gittycat/asuswrt-ai-tools
uv tool install "./asuswrt-ai-tools[mcp]" --force
```

Update the Claude Code plugin later with
`claude plugin marketplace update asuswrt`.

## Removing it again

`scripts/uninstall.sh` undoes all of it: the three binaries and the uv tool
directory, the MCP registration in Claude Code (all three scopes) and in Codex,
the plugin and marketplace entry, the skill leftovers from before v0.8.0, and
the Claude Desktop extension. It skips whatever is not there.

```bash
./scripts/uninstall.sh          # dry run, lists what it would remove
./scripts/uninstall.sh --yes
```

Run from inside a clone it also runs `git clean -xd`, returning the working
tree to the state `git clone` leaves it in — useful for testing an install from
scratch. It refuses if tracked files have uncommitted changes.

Two things it keeps unless asked: `~/.config/asuswrt` with your password
(`--password`) and the clone's `.claude/` directory (`--repo-all`). ChatGPT
connectors are stored server-side, so remove those under *Settings →
Connectors* yourself.

## When the tools load

The tool names are all prefixed `asuswrt`, so they only come up for a request
about your router. Say **asus** once in the first request; after that the agent
uses them for *who's on my WiFi?* or *what devices are on my home network?* on
its own.

The two settings this project will not turn on
([Trend Micro and DoS](../README.md#two-settings-this-project-will-not-turn-on))
are repeated in the `get_overview`, `get_firewall_and_filters` and `get_nvram`
descriptions, because an agent that reads `fw_dos_x=0` with no other context
reports it as a gap to close. A test pins the wording in all three. The
reasoning and sources are in [settings.md](settings.md).

## The MCP server

It speaks MCP over **stdio**, so the host starts `asuswrt-mcp` as a child
process. There is no URL, no port and no network listener.

### What the agent is allowed to do

The server starts read-only. Writes are opt-in, through environment variables
set where you registered the server — or, in Claude Desktop, the two switches in
the extension's settings, which set the same variables:

| What you set | Tools the agent sees |
| --- | --- |
| *(nothing)* | the 15 read tools |
| `ASUSWRT_MCP_ALLOW_WRITES=1` | + 11 tools that change settings |
| both that and `ASUSWRT_MCP_ALLOW_DANGEROUS=1` | + `reboot_router`, `upgrade_firmware` |

`ASUSWRT_MCP_ALLOW_DANGEROUS` on its own does nothing; it needs the writes
variable too. Both open on `1`, `true`, `yes` or `on`, and on nothing else.
Tools you have not enabled are never advertised — the agent cannot see them,
cannot call them, and they cost no context. The variables are read once at
startup, so after changing one, restart the host.

### The tools

```
reads (always)       get_overview  get_system  get_health  get_wan
                     get_dns  get_led  get_upnp  list_clients
                     get_firewall_and_filters  get_parental_control
                     list_port_forwards  list_guest_networks  get_wireless
                     check_firmware_update  get_nvram

writes (opt-in)      add_port_forward  remove_port_forward
                     set_port_forwarding_enabled  set_parental_control_enabled
                     set_guest_network_enabled  set_wps_enabled
                     set_wifi_security  set_wifi_country
                     set_wan_dns  set_led_enabled  set_upnp_enabled

dangerous (both)     reboot_router  upgrade_firmware
```

`get_overview` is the cheap starting point — a summary (client *counts*, no
firmware check, no raw nvram) for one login. `check_firmware_update` makes the
router contact ASUS and takes about 5 seconds.

### Every write is two calls

Write tools take `confirm: bool = False`. Without it they change nothing:

```jsonc
// confirm omitted → preview only
{"status": "preview", "applied": false,
 "change": "…one sentence…", "warnings": ["…"], "current": {…}}

// confirm: true → applied, with before/after for nvram writes
{"status": "applied", "applied": true, …}
```

This mirrors the CLI's dry-run-then-`--yes` rule, and it lives in the server
because it cannot be delegated to the host: the MCP spec treats tool annotations
as *hints*, and some hosts auto-approve. `upgrade_firmware` additionally
requires `to`, the exact version string from `check_firmware_update`, so nothing
ever flashes whatever happened to turn up.

### The Claude Desktop extension

`extension/asuswrt.mcpb` is an [MCP Bundle](https://github.com/anthropics/mcpb)
— a zip holding a `manifest.json`, an icon and a launcher script. Claude Desktop
reads the manifest, shows the install dialog, and stores the two switches as
`ASUSWRT_MCP_ALLOW_WRITES` and `ASUSWRT_MCP_ALLOW_DANGEROUS` — the same
variables the terminal hosts pass.

**It does not contain the server.** `asuswrt-mcp` needs Python 3.13, Claude
Desktop ships no Python runtime, and the Python that a GUI app finds on macOS is
the system 3.9. So the bundle carries a launcher that runs the copy `uv tool
install` already placed in `~/.local/bin` — a self-contained script whose
shebang points into its own virtualenv, which is why it works with no `PATH` at
all. If the launcher cannot find it, the reason lands in
`~/Library/Logs/Claude/mcp-server-asuswrt.log`.

Rebuild it after editing the manifest — the build refuses to run if its version
has drifted from `pyproject.toml`:

```bash
python3 extension/build.py
# or: npx @anthropic-ai/mcpb pack extension extension/asuswrt.mcpb
```

### Claude Desktop, by hand

**Settings → Developer → Edit Config** opens
`~/Library/Application Support/Claude/claude_desktop_config.json` on macOS,
`%APPDATA%\Claude\claude_desktop_config.json` on Windows, if you would rather
skip the extension and write the entry yourself:

```json
{
  "mcpServers": {
    "asuswrt": {
      "command": "/Users/you/.local/bin/asuswrt-mcp",
      "env": {
        "ASUSWRT_MCP_ALLOW_WRITES": "1"
      }
    }
  }
}
```

Drop the `env` block for a read-only server. The path must be absolute.

Codex's app and IDE extension have a form for this: **Settings → MCP servers →
Add server** (the gear menu in the IDE extension). Choose **STDIO**, name it
`asuswrt`, and give the absolute path to `asuswrt-mcp`. Or edit
`~/.codex/config.toml`:

```toml
[mcp_servers.asuswrt]
command = "asuswrt-mcp"
env = { ASUSWRT_MCP_ALLOW_WRITES = "1" }
```

## Other agents

Any host implementing the MCP spec works unchanged: the server is
`asuswrt-mcp`, over stdio.

## Adding a setting the tool does not cover

Find the variable name by diffing the router's settings around a single change:

```bash
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > before.txt
# change exactly one setting in the web UI, save
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > after.txt
diff before.txt after.txt
```

The diff names the variable and shows how it is encoded. Add it to
`FIREWALL_VARS` in `src/asuswrt/ops.py` to read it — the CLI and the MCP server
both pick it up from there — and record it in the settings reference. SSH is
enabled in the web UI under *Administration → System → Service → Enable SSH*; it
is not exposed in the mobile app.

