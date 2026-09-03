# ASUS Router MCP and SKILL for AI Agents

## TLDR

Use the SKILL if you're using Claude Code or Codex. It consumes 2900 tokens when loaded.

The MCP server takes slightly more tokens at 3200. Still light. Also, MCP definitions are now lazy loaded by Claude Code and Codex. The calls are optimised for fewer round trips which results in token savings too.

Both include a custom python tool, **asuswrt**, to connect to a home ASUS (AsusWRT) router.  The tool can be used manually but it aimed at AI agents. As such,a few railguards and utilities were built in such as not including direct nvram set, including json output everywhere, using guessable non-verb grammar, and requiring confirmation for any config change

The MCP and SKILL are loaded into the context when you write **asus router** or try to inspect your "local network" or "wifi". The word "router" alone won't load the skill. It is way too generic in a tech context.
That would likely result in the skill being needlessly loaded
for unrelated requests. Once loaded, the model doesn't need the asus hint.
It'll use the skill for requests such as
`who's on my WiFi?` or `what devices are on my home network?`

This `asuswrt` python tool uses the unpublished HTTP API of the ASUS router.
This is the same API used by the official ASUS iOS app.

I'll let my agent fill in the details. Here we go...

## Installation

You need [uv](https://docs.astral.sh/uv/) and your router's admin password.

Step 1 and step 2 are always required. After that, install the skill, the MCP
server, or both.

### Step 1 — Install the asuswrt program

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
```

Or from a local clone:

```bash
git clone https://github.com/gittycat/asuswrt-tools
uv tool install "./asuswrt-tools[mcp]" --force
```

This puts `asuswrt`, `asuswrt-mcp` and `asuswrt-probe` in `~/.local/bin`. Run
`uv tool update-shell` once if that directory is not on your `PATH`.

The `[mcp]` extra pulls in the MCP SDK. Leave it off if you only want the CLI
and the skill.

### Step 2 — Save your router credentials

```bash
mkdir -p ~/.config/asuswrt
cat > ~/.config/asuswrt/.env <<'EOF'
ROUTER_USER=admin
ROUTER_PASS=your-router-password
EOF

asuswrt system    # should print your model, firmware and MAC
```


Config lookup order, first match wins:

1. `$ASUSWRT_ENV_FILE`, if you set it
2. `.env` in the current directory
3. `~/.config/asuswrt/.env`

The CLI and the MCP server read the same file from the same places.
If `asuswrt system` returns a login
error, check that the account is the router **admin**, not a limited family
member.

### Step 3a — Install as a skill

**Claude Code** — install from the marketplace:

```bash
claude plugin marketplace add gittycat/asuswrt-tools
claude plugin install asuswrt@asuswrt
```

This also registers the MCP server, so you can skip step 3b.
Update later with `claude plugin marketplace update asuswrt`.

**Codex** — skills are plain folders. Copy this one into `~/.agents/skills`:

```bash
git clone --depth 1 https://github.com/gittycat/asuswrt-tools /tmp/asuswrt-tools
mkdir -p ~/.agents/skills
cp -r /tmp/asuswrt-tools/skills/asuswrt ~/.agents/skills/
rm -rf /tmp/asuswrt-tools
```

Codex picks it up from `~/.agents/skills` on the next start, in the CLI and in
the IDE extension. Run `/skills` to confirm it is listed, or invoke it
explicitly with `$asuswrt`. In the ChatGPT desktop app, skills appear under
**Skills** in the sidebar.

### Step 3b — Install as an MCP server

The server is `asuswrt-mcp`. It speaks MCP over **stdio**, so the host starts
it as a child process — there is no URL and no network listener.

**Claude Code (terminal):**

```bash
claude mcp add --env ASUSWRT_MCP_ALLOW_WRITES=1 --scope user asuswrt -- asuswrt-mcp
```

Drop the `--env` flag for a read-only server, which is the recommended default.

**Claude Desktop (app):** open **Settings → Developer → Edit Config**, then add:

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

Use the absolute path. GUI apps do not inherit your shell `PATH`.

**Codex (terminal):**

```bash
codex mcp add asuswrt --env ASUSWRT_MCP_ALLOW_WRITES=1 -- asuswrt-mcp
```

Or edit `~/.codex/config.toml` directly:

```toml
[mcp_servers.asuswrt]
command = "asuswrt-mcp"
env = { ASUSWRT_MCP_ALLOW_WRITES = "1" }
```

**Codex app and IDE extension:** in the ChatGPT desktop app, **Settings → MCP
servers → Add server**; in the IDE extension, the gear menu → **MCP servers →
Add server**. Choose **STDIO**, name it `asuswrt`, give the absolute path to
`asuswrt-mcp` as the command, then restart.

### Other agents

Any host that implements the [Agent Skills](https://agentskills.io) or MCP
specs works unchanged — the skill is the `skills/asuswrt` folder, the server is
`asuswrt-mcp`.

### Try it

```
Review the security settings on my Asus router

What devices are connected to my Asus router?

Open port 32400 on the asus for my media server
```

**IMPORTANT** Mention **asus** in your first request so the skill loads into
context. After that the agent knows to keep using it.

---

## The asuswrt tool

The tool works on its own, without an agent.

### Reading

```bash
asuswrt show                    # everything below in one connection
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

### Changing

Changes take two steps by design. The first run is always a dry run:

```bash
asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20
# → prints what it would do, changes nothing, exits 3

asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
# → applies it
```

What can be changed:

- **Port forwarding** — add, remove, enable or disable globally
- **Guest WiFi** — enable or disable any of the six networks
- **WiFi security** — WPS, WPA2/WPA3 mode, frame protection, country code
- **Parental control** — enable or disable
- **Firmware upgrade**, and **reboot**

---

## MCP server

### Two gates

Read tools are always available. Everything else is off unless you turn it on:

| Environment variable | Adds |
| --- | --- |
| *(none)* | 12 read tools |
| `ASUSWRT_MCP_ALLOW_WRITES=1` | + 8 write tools |
| `ASUSWRT_MCP_ALLOW_DANGEROUS=1` | + `reboot_router`, `upgrade_firmware` — **also needs the writes gate**; on its own it does nothing |

The gates *hide* tools rather than reject calls, so a tool you have not enabled
costs no context and cannot be retried into working. **They are read once at
startup** — change one and restart the server, or the host, for it to take
effect.

### Tools

```
reads (always)       get_overview  get_system  get_health  get_wan
                     list_clients  get_firewall_and_filters
                     get_parental_control  list_port_forwards
                     list_guest_networks  get_wireless
                     check_firmware_update  get_nvram

writes (gate 1)      add_port_forward  remove_port_forward
                     set_port_forwarding_enabled  set_parental_control_enabled
                     set_guest_network_enabled  set_wps_enabled
                     set_wifi_security  set_wifi_country

dangerous (both)     reboot_router  upgrade_firmware
```

Start with `get_overview` — it is a summary (client *counts*, no firmware
check, no raw nvram) and costs one login. `check_firmware_update` makes the
router contact ASUS and takes about 5 seconds.

### Every write is two calls

Write tools take `confirm: bool = False`, and without it they **change
nothing**:

```jsonc
// confirm omitted → preview only
{"status": "preview", "applied": false,
 "change": "…one sentence…", "warnings": ["…"], "current": {…}}

// confirm: true → applied, with before/after for nvram writes
{"status": "applied", "applied": true, …}
```

This mirrors the CLI's dry-run-then-`--yes` rule, and it stays in the server
because it cannot be delegated to the host: the MCP spec treats tool
annotations as *hints*, and some hosts auto-approve. `upgrade_firmware`
additionally requires `to` — the exact version string from
`check_firmware_update` — so nothing ever flashes whatever happened to turn up.

---

## About safety

An AI agent is expected to be driving this, so the guardrails live in the tool
itself rather than in instructions a model can talk itself out of.

- **Nothing changes unless you say so.** `--yes` applies a change. At a
  terminal you get a `[y/N]` prompt. With neither, the command prints what it
  *would* do, changes nothing, and exits with code 3. Silence never counts as
  approval, so running a command without `--yes` is always safe.
- **No raw writes.** You can read any router setting with `asuswrt nvram get`,
  but there is deliberately no write equivalent. Writing raw settings blindly
  is the usual way a working router config gets wrecked. Only the reviewed,
  named commands can write.
- **Changes are checked, not assumed.** The router saying it accepted a change
  does not mean the change stuck — the WiFi country code, for example, is
  routinely accepted and then quietly ignored. Every `asuswrt wifi` command
  reads the setting back afterwards, prints `before -> after`, and fails if
  nothing actually changed.
- **Duplicate ports are caught.** Forwarding a port that is already forwarded
  fails unless you add `--force`.
- **Reboots only when you ask for one.** The skill tells the agent never to
  reboot unless you used the word.
- **Your password stays on your machine.** It lives in a `.env` file outside
  this repository, is read only by the tool running locally, and is never sent
  to a model.

---

## Limitations

- **One request at a time.** Every command and every MCP tool call logs in,
  does its work, and logs out, costing about a second. That is fine for asking
  a few questions; it is the wrong tool for continuous monitoring.
- **Personal use, not a service.** It is built for one person and one router.
  Do not put it behind a web app or share it between users.
- **One router per config.** The detected gateway, or `ROUTER_HOST`, is a
  single address. Individual AiMesh nodes cannot be addressed.
- **`No route to host` has more than one cause.** The error is returned both
  by an absent router and by a local machine that refuses to route to it —
  a stale ARP entry, or macOS Local Network privacy. The message lists both
  and a `curl` check that separates them. See `docs/troubleshooting.md`.
- **Content filters are read-only.** URL and keyword filter rules can be read
  but not changed, and the setting names for them are unconfirmed. If
  `asuswrt firewall` shows `? (None)`, the name is wrong for your firmware.
- **Parental control is one switch.** Turning it on or off works; per-device
  rules still need the web UI.
- **WiFi control is partial.** WPS, WPA mode, frame protection and country code
  can be changed. SSID, password, channel and bandwidth cannot.
- **The country code may be locked.** Stock firmware often derives it from the
  hardware model and ignores the change. The command tells you when that
  happens; the web UI is the fallback.
- **A firmware update can break this.** None of this is a supported API.

Tested on an ASUS RT-AX59U running stock firmware `3.0.0.4` (not Merlin), with
the `asusrouter` library 1.21. Other AsusWRT routers should work — the library
lists 27 confirmed models from WiFi 4 through WiFi 7, on stock and Merlin — but
the details in [`settings.md`](skills/asuswrt/reference/settings.md) were
confirmed on an RT-AX59U only. Two data types (`system`, `temperature`) return
nothing on this model and are not used.

## Adding missing api

To add a setting the tool does not cover yet, find its variable name by
diffing the router's settings around a change:

```bash
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > before.txt
# change exactly one setting in the web UI, save
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > after.txt
diff before.txt after.txt
```

The diff names the variable and shows how it is encoded. Add it to
`FIREWALL_VARS` in `src/asuswrt/ops.py` to read it — the CLI and the MCP server
both pick it up from there — and record it in the settings reference. SSH is
enabled in the web UI under *Administration → System → Service → Enable SSH*;
it is not exposed in the mobile app.

## Credits

- **[asusrouter](https://github.com/Vaskivskyi/asusrouter)** by
  [Vaskivskyi](https://github.com/Vaskivskyi) (Apache-2.0) — the HTTP API
  client for AsusWRT that does all the protocol work here. Also used by the
  core Home Assistant AsusWRT integration.
- **[mcp](https://github.com/modelcontextprotocol/python-sdk)** — the official
  Python SDK for the Model Context Protocol, which runs the stdio server.
- **[python-dotenv](https://github.com/theskumar/python-dotenv)** — loads the
  router credentials from the `.env` file.

## License

MIT
