# ASUS Router MCP and SKILL for AI Agents

Allows you to control a local Asus WRT home router via AI prompts instead of using the Asus web admin interface or ios app.

Use the SKILL for CLI coding agents like Claude Code, Codex. Use the MCP for AI chat agents like ChatGPT, Gemini app, ...

They both use the included small python program, `asuswrt` that speaks the router's
unpublished HTTP API — the same one the official ASUS mobile app uses. No SSH,
no scraping the web UI. It ships two ways:

Install either one. Installing both is fine, and is what the Claude Code plugin
does — the skill prefers the MCP tools when it finds them.

---

## Installation

You need [uv](https://docs.astral.sh/uv/), your router's **admin** password, and
a machine on the same network as the router.

Save the password first — everything needs it. After that the **skill** and the
**MCP server** are independent: install one, the other, or both, in any order.

### Save your router password — required

```bash
mkdir -p ~/.config/asuswrt
cat > ~/.config/asuswrt/.env <<'EOF'
ROUTER_USER=admin
ROUTER_PASS=your-router-password
EOF
```

That is the whole configuration — the router's address is your machine's default
gateway, detected on every run. Use the router's **admin** account; a limited
family-member account cannot log in.

### Install the skill

**Claude Code**

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
claude plugin marketplace add gittycat/asuswrt-tools
claude plugin install asuswrt@asuswrt
```

The plugin carries the skill **and** registers the MCP server, read-only, so on
Claude Code this is the whole installation. Register the server yourself, below,
only if you want the agent to be able to change router settings.

**Codex** — skills are plain folders, so copy this one in:

```bash
uv tool install "asuswrt @ git+https://github.com/gittycat/asuswrt-tools"

git clone --depth 1 https://github.com/gittycat/asuswrt-tools /tmp/asuswrt-tools
mkdir -p ~/.agents/skills
cp -r /tmp/asuswrt-tools/skills/asuswrt ~/.agents/skills/
rm -rf /tmp/asuswrt-tools
```

Restart Codex. `/skills` should now list `asuswrt`.

### Install the MCP server

**Claude Code**

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
claude mcp add --scope user asuswrt -- asuswrt-mcp
```

That server is read-only. To let the agent change settings too, insert
`--env ASUSWRT_MCP_ALLOW_WRITES=1` before the name:

```bash
claude mcp add --env ASUSWRT_MCP_ALLOW_WRITES=1 --scope user asuswrt -- asuswrt-mcp
```

**Codex**

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
codex mcp add asuswrt -- asuswrt-mcp

# or, allowing writes:
codex mcp add asuswrt --env ASUSWRT_MCP_ALLOW_WRITES=1 -- asuswrt-mcp
```

**Claude Desktop** (macOS and Windows — there is no Linux build) — install the
server, then the one-click extension:

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
curl -LO https://raw.githubusercontent.com/gittycat/asuswrt-tools/main/extension/asuswrt.mcpb
open asuswrt.mcpb     # macOS. On Windows: start asuswrt.mcpb
```

Claude Desktop opens an install dialog with three settings: the path to
`asuswrt-mcp`, already filled in, and two switches that are off —
**Allow changes to the router** and **Allow reboot and firmware upgrade**. Turn
the first on if you want the agent to be able to change settings, and leave the
second off unless you mean it.

If double-clicking does nothing, or you would rather download the file in a
browser, use **Settings → Extensions → Advanced settings → Install Extension…**
and pick it. Editing
`claude_desktop_config.json` by hand still works too, and is
[in the details below](#claude-desktop-by-hand).

### Check it works

```bash
asuswrt system     # your model, firmware and MAC
```

If that prints your router, the agent side works too.

---

## Try it

Say **asus** in your first request so the skill or the tools load. After that
the agent keeps using them on its own.

Ask:

```
What devices are connected to my Asus router?
Review the security settings on my Asus router
Is my Asus router's firmware up to date?
Is the asus router's admin page reachable from the internet?
The internet feels slow — check the asus router's CPU, memory and WAN
```

Change:

```
Open port 32400 on the asus for my media server
Turn on the guest WiFi on the asus for my visitors
Turn off WPS on my Asus router
Close the Plex port on the asus again
```

Every change is previewed first and applied only after you agree.

---

## Using it without an agent

The same program works as an ordinary command.

```bash
asuswrt show                    # everything below, in one connection
asuswrt system                  # model, firmware, mac, aimesh
asuswrt system health           # uptime, cpu, ram, wan
asuswrt clients --online        # who's connected
asuswrt wan                     # ip, gateway, dns, protocol
asuswrt firewall                # firewall, dos, wan admin access, filters
asuswrt parental                # parental control state and rules
asuswrt portforward             # port forwarding switch and rules
asuswrt guest                   # guest networks
asuswrt wifi                    # wps, wpa mode, frame protection, country
asuswrt firmware --notes        # installed vs offered version, release note
asuswrt nvram get vts_rulelist  # any raw setting, by name
```

Add `--json` to any of them for machine-readable output.

Changes take two runs. The first is always a dry run:

```bash
asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20
# → prints what it would do, changes nothing, exits 3

asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
# → applies it
```

What can be changed at all: **port forwarding** (add, remove, enable, disable),
**guest WiFi** (any of the six networks), **WiFi security** (WPS, WPA2/WPA3
mode, frame protection, country code), **parental control** (on or off),
**firmware upgrade** and **reboot**.

---

## Built for agents

A human reading a router's web UI notices when something looks wrong. An agent
does not. So the judgement lives in the tool, where a model cannot talk its way
around it, rather than in instructions it is asked to follow.

- **Nothing changes unless you say so.** A mutation without `--yes` prints what
  it *would* do and exits 3; an MCP write without `confirm: true` returns a
  preview. Silence is never approval, so any command is safe to run once.
- **No raw writes.** `asuswrt nvram get` reads any setting on the router, and
  there is deliberately no `set`. Blind raw writes are how a working router
  config gets wrecked. Only the reviewed, named commands can change anything.
- **Changes are read back, not assumed.** The router happily accepts a WiFi
  country code and then ignores it. Every WiFi command re-reads the setting,
  prints `before -> after`, and fails if nothing moved.
- **Predictable, guessable grammar.** Noun then verb, `show` as the only read
  verb, `--json` on every read. An agent can reach the right command without
  hunting through help output, and never has to parse a table.
- **The likely mistakes are blocked in code.** A duplicate port needs
  `--force`; `upgrade_firmware` needs the exact version string that the check
  returned; the skill forbids rebooting unless you used the word; MCP write
  tools are hidden rather than refused, so an agent cannot retry one into
  working.
- **Errors carry their own diagnosis.** `No route to host`, for example, has
  several causes, and the message lists them plus a `curl` check that separates
  them — so the agent relays a real answer instead of inventing one.
- **Your password stays local.** It lives in a `.env` file outside this
  repository, is read only by the program running on your machine, and is never
  sent to a model.

---

## Limitations

- **One request at a time.** Every command and every MCP tool call logs in, does
  its work, and logs out, costing about a second. Fine for asking a few
  questions; the wrong tool for continuous monitoring.
- **Personal use, not a service.** One person, one router. Do not put it behind
  a web app or share it between users.
- **One router per config.** The detected gateway, or `ROUTER_HOST`, is a single
  address. Individual AiMesh nodes cannot be addressed.
- **`No route to host` has more than one cause.** It is returned both by an
  absent router and by a local machine that refuses to route to it — a stale ARP
  entry, or macOS Local Network privacy. See
  [`docs/troubleshooting.md`](docs/troubleshooting.md).
- **Content filters are read-only.** URL and keyword rules can be read but not
  changed, and their setting names are unconfirmed. If `asuswrt firewall` shows
  `? (None)`, the name is wrong for your firmware.
- **Parental control is one switch.** On or off works; per-device rules still
  need the web UI.
- **WiFi control is partial.** WPS, WPA mode, frame protection and country code
  can be changed. SSID, password, channel and bandwidth cannot.
- **The country code may be locked.** Stock firmware often derives it from the
  hardware model and ignores the change. The command tells you when that
  happens; the web UI is the fallback.
- **A firmware update can break this.** None of this is a supported API.

## Two settings this project will not turn on

Both come up in every security review of an ASUS router, so the tools treat them
as settled rather than raise them with you each time. If you disagree, each is
one checkbox away in the web UI — this project simply will not propose them.

- **AiProtection**, and with it Traffic Analyzer, Apps Analyzer, Adaptive QoS,
  Game Boost and Web History. All of them are gated behind a single bundled
  Trend Micro EULA: accepting it for any one feature starts the Trend Micro DPI
  engine and sends browsing data off the router. It costs no money — the price
  is the data. So `TM_EULA=0` and `bwdpi_db_enable=0` are the expected reading
  here, not a misconfiguration. The sub-flags `wrs_mals_enable`, `wrs_cc_enable`
  and `wrs_vp_enable` can show `1` while the engine is off; that means
  configured but not running, which is the desired end state.
- **DoS protection** (`fw_dos_x`). It adds firewall rules limiting new
  connections and ICMP to roughly one packet per second. The community
  consensus on SNBForums is that this stops nothing real — against an actual
  flood the uplink saturates long before the router matters — while it does
  break legitimate traffic, with users reporting they had to disable it for
  Cloudflare and for media servers. `0` is both the AsusWRT default and the
  right value for a home router.

Sources for both are in
[`settings.md`](skills/asuswrt/reference/settings.md#features-with-a-settled-answer).

Tested on an ASUS RT-AX59U running stock firmware `3.0.0.4` (not Merlin), with
the `asusrouter` library 1.21. Other AsusWRT routers should work — the library
lists 27 confirmed models from WiFi 4 through WiFi 7, on stock and Merlin — but
the details in [`settings.md`](skills/asuswrt/reference/settings.md) were
confirmed on an RT-AX59U only. Two data types (`system`, `temperature`) return
nothing on this model and are not used.

---

# Details - Not for humans

Nothing below is needed to install or use the tool. It is here for edge cases,
and for the agent reading this file.

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
git clone https://github.com/gittycat/asuswrt-tools
uv tool install "./asuswrt-tools[mcp]" --force
```

Update the Claude Code plugin later with
`claude plugin marketplace update asuswrt`.

## When the skill loads

The skill enters context on **asus router**, or on a request about your "local
network" or "wifi". The word *router* alone does not load it — in a codebase
that almost always means Express, React Router or message routing, and the skill
would load for unrelated work. Once loaded, the hint is no longer needed: the
agent will use it for *who's on my WiFi?* or *what devices are on my home
network?* on its own.

In Codex, `/skills` lists it and `$asuswrt` invokes it explicitly; in the
ChatGPT desktop app it appears under **Skills** in the sidebar.

The skill deliberately carries only what a tool schema cannot: the CLI, when a
reboot or a flash is allowed, and the pointers into `reference/`. Per-tool
safety notes live in the MCP tool descriptions, and the preview-then-confirm
contract is enforced in the server itself — so neither one restates the other.

The one deliberate duplication is [the two settings above](#two-settings-this-project-will-not-turn-on),
which are repeated in the `get_overview`, `get_firewall_and_filters` and
`get_nvram` descriptions. The skill is not always there: the Claude Desktop
extension ships the MCP server with no skill mechanism at all, and registering
the server by hand installs no skill either. An agent that reads `fw_dos_x=0`
with no other context reports it as a gap to close. A test pins the wording in
all three descriptions.

## The MCP server

It speaks MCP over **stdio**, so the host starts `asuswrt-mcp` as a child
process. There is no URL, no port and no network listener.

### What the agent is allowed to do

The server starts read-only. Writes are opt-in, through environment variables
set where you registered the server — or, in Claude Desktop, the two switches in
the extension's settings, which set the same variables:

| What you set | Tools the agent sees |
| --- | --- |
| *(nothing)* | the 12 read tools |
| `ASUSWRT_MCP_ALLOW_WRITES=1` | + 8 tools that change settings |
| both that and `ASUSWRT_MCP_ALLOW_DANGEROUS=1` | + `reboot_router`, `upgrade_firmware` |

`ASUSWRT_MCP_ALLOW_DANGEROUS` on its own does nothing; it needs the writes
variable too. Both open on `1`, `true`, `yes` or `on`, and on nothing else.
Tools you have not enabled are never advertised — the agent cannot see them,
cannot call them, and they cost no context. The variables are read once at
startup, so after changing one, restart the host.

### The tools

```
reads (always)       get_overview  get_system  get_health  get_wan
                     list_clients  get_firewall_and_filters
                     get_parental_control  list_port_forwards
                     list_guest_networks  get_wireless
                     check_firmware_update  get_nvram

writes (opt-in)      add_port_forward  remove_port_forward
                     set_port_forwarding_enabled  set_parental_control_enabled
                     set_guest_network_enabled  set_wps_enabled
                     set_wifi_security  set_wifi_country

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

Any host implementing the [Agent Skills](https://agentskills.io) or MCP specs
works unchanged: the skill is the `skills/asuswrt` folder, the server is
`asuswrt-mcp`.

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

---

## Credits

- **[asusrouter](https://github.com/Vaskivskyi/asusrouter)** by
  [Vaskivskyi](https://github.com/Vaskivskyi) (Apache-2.0) — the HTTP API client
  for AsusWRT that does all the protocol work here. Also used by the core Home
  Assistant AsusWRT integration.
- **[mcp](https://github.com/modelcontextprotocol/python-sdk)** — the official
  Python SDK for the Model Context Protocol, which runs the stdio server.
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — loads the
  router credentials from the `.env` file.

## License

MIT
