# ASUS Router MCP and SKILL for AI Agents

## TLDR

> Use the SKILL if you're using Claude Code or Codex. It consumes less than 2400 tokens.
>
> The MCP server is for AI apps or web based interfaces. It will still be lazy
> loaded to minimise context use. That's what CC and Codex do as of Aug 2026
> instead of loading the full schema in context.
>
> Both include a custom python tool, **asuswrt**, to connect to a home ASUS (AsusWRT) router.  The tool can be used manually but it aimed at AI agents. As such,a few railguards and utilities were built in such as not including direct nvram set, including json output everywhere, using guessable non-verb grammar, and requiring confirmation for any config change

The MCP and SKILL are loaded into the context when you write **asus router** in
your prompt. The word "router" alone is way too generic in a tech context.
That would likely result in the skill being needlessly loaded
for unrelated requests. Once loaded, the model doesn't need the asus hint.
It'll use the skill for requests such as
`who's on my WiFi?` or `what devices are on my home network?`

This `asuswrt` python tool uses the unpublished HTTP API of the ASUS router.
This is the same API used by the official ASUS iOS app.

## Router Params that can be Read

- Router identity and live health — model, firmware, uptime, CPU, RAM
- Internet connection — WAN link, IP, gateway, DNS
- Connected and known devices
- Firewall, DoS protection, WAN admin access, content filters
- Port forwarding
- Guest WiFi
- WiFi security — WPS, WPA mode, frame protection, country code
- Parental control
- Firmware — installed version vs. what ASUS is offering
- Any raw router setting by name

## Router Params that can be Modified

- Port forwarding — add, remove, enable/disable globally
- Guest WiFi — enable/disable any of the six networks
- WiFi security — WPS, WPA2/WPA3 mode, frame protection, country code
- Parental control — enable/disable
- Firmware upgrade, and reboot

## Installation

You need [uv](https://docs.astral.sh/uv/) and your router's admin password.

**1. Install the program that the skill and the MCP server both drive**

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
```

OR ...  
 from a local git clone, which also builds the wheel for you:

```bash
git clone https://github.com/gittycat/asuswrt-tools
uv tool install "./asuswrt-tools[mcp]" --force
```

The `[mcp]` extra pulls in the MCP SDK and is what makes the `asuswrt-mcp`
command work. Leave it off and you get the CLI only — `asuswrt-mcp` will still
be on your `PATH` but will exit with `ModuleNotFoundError: No module named
'mcp'`. (`uv tool install` has no `--extra` flag; the extra goes inside the
requirement string, as above.)

Either way `uv` puts `asuswrt`, `asuswrt-mcp` and `asuswrt-probe` in
`~/.local/bin`; run `uv tool update-shell` once if that directory is not on
your `PATH`.

**2. Save your router credentials**

```bash
mkdir -p ~/.config/asuswrt
cat > ~/.config/asuswrt/.env <<'EOF'
ROUTER_HOST=192.168.50.1
ROUTER_USER=admin
ROUTER_PASS=your-router-password
EOF

asuswrt system    # should print your model, firmware and MAC
```

**3. Install the skill**

```bash
# Claude Code
claude plugin marketplace add gittycat/asuswrt-tools
claude plugin install asuswrt@asuswrt -y

# Codex
mkdir -p ~/.agents/skills
git clone --depth 1 https://github.com/gittycat/asuswrt-tools /tmp/ars \
  && cp -r /tmp/ars/skills/asuswrt ~/.agents/skills/ && rm -rf /tmp/ars
```

## Sample Usage

```
Review the security settings on my Asus router  
  
What devices are connected to my Asus router?
   
Open port 32400 on the asus for my media server
```

**IMPORTANT** Remember to mention **asus** in your first request so that the skill loads in the context.

### Other Agents

**NOT TESTED**

**Any other Agent Skills host** — Cursor, Gemini CLI, GitHub Copilot, VS Code,
Goose, Junie — reads the same `skills/asuswrt` folder from its own skills
directory. Check your agent's docs for the path; the skill needs no changes.

**Claude Code, one clone with the source included.** Cloning into your skills
directory registers it as a plugin *and* gives you something to install the CLI
from:

```bash
git clone https://github.com/gittycat/asuswrt-tools ~/.claude/skills/asuswrt
uv tool install ~/.claude/skills/asuswrt --force
```

**Claude Code, one session only**, while editing a local checkout:

```bash
claude --plugin-dir /path/to/asuswrt-tools
```

Do not combine these with the marketplace install — the skill would load twice
under two identities.

**Updating:** `claude plugin marketplace update asuswrt`, or
`git pull` in the clone.

**Config lookup order**, first match wins:

1. `$ASUSWRT_ENV_FILE`, if you set it
2. `.env` in the current directory
3. `~/.config/asuswrt/.env`

Those three, in that order, and nothing else. The MCP server reads the same
file from the same places.

`env.example` is a starting template. If `asuswrt system` gives a login error, check
that your account is the router **admin**, not a limited family member.

## asuswrt tool

You can call the asuswrt tool works on its own, without an agent:

```bash
asuswrt show                    # all of the below in one connection
asuswrt system                  # model, firmware, mac, aimesh
asuswrt system health           # uptime, cpu, ram, wan
asuswrt clients --online        # who's connected
asuswrt wan                     # ip, gateway, dns, protocol
asuswrt firewall                # firewall + filters + parental control
asuswrt parental                # parental control state and rules
asuswrt portforward             # port forwarding switch and rules
asuswrt guest                   # guest networks
asuswrt wifi                    # wps, wpa mode, frame protection, country
asuswrt firmware --notes        # installed vs offered version, release note
asuswrt nvram get vts_rulelist  # any raw setting
```

Add `--json` to any of them for machine-readable output.

Changing things takes two steps by design:

```bash
asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20
# → prints what it would do, changes nothing, exits 3

asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
# → applies it
```

---

## MCP server

`asuswrt-mcp` speaks MCP over **stdio** — the host starts it as a child
process. There is no HTTP transport and no network listener; see
[ROADMAP.md](ROADMAP.md) for what it would take to add one.

It shares exactly one module with the CLI: `ops.py`, the domain operations. It
does not import the CLI at all, and a test enforces that — on stdio, stdout
*is* the JSON-RPC channel, so a single stray `print` would kill the connection.

### Two gates

Read tools are always available. Everything else is off unless you say
otherwise:

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

This is the CLI's dry-run-then-`--yes` rule, kept because it cannot be
delegated to the host: the MCP spec says tool annotations are *hints*, and some
hosts auto-approve. `upgrade_firmware` additionally requires `to` — the exact
version string from `check_firmware_update` — so nothing ever flashes whatever
happened to turn up.

### Client configuration

**Claude Code:** installing the plugin registers the server for you; nothing to
configure. Add the gates in your settings if you want writes.

**Anything else** — Claude Desktop, or any MCP host with a JSON config:

```json
{
  "mcpServers": {
    "asuswrt": {
      "command": "asuswrt-mcp",
      "env": {
        "ASUSWRT_MCP_ALLOW_WRITES": "1"
      }
    }
  }
}
```

Use the absolute path (`~/.local/bin/asuswrt-mcp`) if the host does not
inherit your shell `PATH` — GUI apps usually do not. Drop the `env` block for a
read-only server, which is the recommended default.

---

## Tests

```bash
uv sync --group dev
uv run pytest
```

The suite drives the CLI end to end — argv through argparse through the
command function to captured stdout — against a fake router built from values
observed on a real RT-AX59U. Only the `AsusRouter` object is replaced;
`read_nvram`, `apply_nvram`, the formatting helpers and the parser all run for
real. **No test contacts a router**, so the suite is safe to run anywhere.

What it covers:

| File | Covers |
| --- | --- |
| `test_parser.py` | Subcommand wiring, required arguments, refused invocations |
| `test_read_commands.py` | Output of every read command, plain and `--json` |
| `test_dry_run.py` | Every mutation refuses without `--yes` and writes nothing |
| `test_mutations.py` | The exact nvram payload and service each mutation sends |
| `test_router.py` | Config loading, nvram read/write, serialisation helpers |
| `test_firmware.py` | Version reporting, the online check, and the flash guards |
| `test_confirmation.py` | The consent matrix: `--yes`, terminal prompt, exit 3 |
| `test_ops.py` | Each domain operation's payload, and that it survives JSON |
| `test_golden.py` | Byte-exact output of every read and mutation, against `golden.json` |
| `test_mcp_tools.py` | Which tools each gate registers, and every preview/apply path |
| `test_mcp_stdio.py` | A real `asuswrt-mcp` subprocess: clean JSON-RPC on stdout |
| `test_layering.py` | MCP never imports the CLI; `ops`/`router` never print |

---

## Safety

The design assumes an AI agent will be driving this, so the guardrails are in
the tool rather than in the instructions.

- **Nothing changes without consent.** `--yes` acts; at a terminal you get a
  `[y/N]` prompt; with neither, the command prints what it would do and exits
  3 without touching anything. Silence never means yes, so a bare mutating
  command is a safe dry run.
- **No raw writes.** `asuswrt nvram get` reads any setting; there is deliberately no
  write counterpart. Blind nvram writes are how working configurations get
  destroyed. Only reviewed, named operations can write.
- **Writes are verified, not assumed.** The router reporting that it ran the
  service does not mean the value stuck — a country code write is routinely
  accepted and then ignored. Every `asuswrt wifi` command reads the variables back
  and prints `before -> after`, exiting non-zero if anything did not change.
- **Duplicate port detection.** Adding a rule for an external port that is
  already forwarded fails unless you pass `--force`.
- **Reboot is opt-in.** The skill instructs the agent never to reboot unless you
  asked for a reboot in those words.
- **Credentials stay local.** They live in a `.env` file outside the repository,
  read only by the CLI on your machine, and never sent to a model.

---
Tested on a ASUS RT-AX59U with `3.0.0.4` (stock, not Merlin) and `asusrouter` python library 1.21.

Other AsusWRT routers should work — the library lists 27 confirmed models
across WiFi 4 through WiFi 7, on stock and Merlin firmware — but the
specifics in [`settings.md`](skills/asuswrt/reference/settings.md) were
confirmed on an RT-AX59U. Two data types (`system`, `temperature`) return
nothing on this model and are simply not used.

---

## How this was built

There is no official ASUS API. Everything here rests on one of three
foundations, and the reference documentation labels every fact with which one:

| Label | Meaning |
| --- | --- |
| `library` | Read directly from the `asusrouter` package source code |
| `hardware` | Observed on a live RT-AX59U |
| `unverified` | General AsusWRT knowledge, not yet confirmed on hardware |

### Sources — the router side

**[asusrouter](https://github.com/Vaskivskyi/asusrouter)** by Vaskivskyi — the
Python library this is built on, and the single most important source. An
HTTP(S) API wrapper for AsusWRT that supports both stock and Merlin firmware,
used by the core Home Assistant AsusWRT integration. Version 1.21.3,
Apache-2.0.

- [Library documentation](https://asusrouter.vaskivskyi.com/library/)
- [RT-AX59U support page](https://asusrouter.vaskivskyi.com/devices/RT-AX59U.html)
  — confirmed the model works, on firmware `388_33911`
- [PyPI](https://pypi.org/project/asusrouter/)

Specific behaviours were taken from reading its source rather than its docs,
because they are not documented anywhere:

| What | Where it came from |
| --- | --- |
| Port forwarding string encoding | `modules/endpoint/hook.py::process_port_forwarding` and `tools/legacy.py::compile_port_forwarding` |
| `vts_enable_x` / `vts_rulelist` names | `modules/port_forwarding.py` |
| Guest WiFi variable pattern | `modules/wlan.py::set_state` |
| CPU usage being a two-sample delta | `modules/endpoint/hook.py::process_cpu` |
| WAN payload nesting | `modules/endpoint/hook.py::process_wan` |
| Client online flag | `modules/client.py` + `modules/connection.py` |
| Generic nvram read over HTTP | `modules/identity.py::collect_identity` + `tools/writers.py::nvram` |

**Why nvram has no reference manual.** ASUS has never published one. The
standing answer from the Asuswrt-Merlin community is that
[there is no documentation](https://www.snbforums.com/threads/documentation-for-nvram-variables.74894/)
and the only real source is `router/shared/defaults.c` in the GPL source drop.
That gap is why this repository ships its own
[settings reference](skills/asuswrt/reference/settings.md) with provenance
labels instead of pretending to be authoritative.

**Firmware options.** There is no Asuswrt-Merlin build for the RT-AX59U;
[the request](https://github.com/gnuton/asuswrt-merlin.ng/issues/930) to gnuton's
fork is open and unsupported. Everything here therefore targets stock firmware.

**Prior art.** Two SSH-based MCP servers exist —
[teefloo/asuswrt-mcp](https://github.com/teefloo/asuswrt-mcp) and
[kcsoukup/asus-merlin-mcp](https://github.com/kcsoukup/asus-merlin-mcp). Both
are young, both require SSH, and neither bundles a settings reference. Both are
also MCP servers, which ties them to hosts speaking that protocol. This project
takes the HTTP path instead — no SSH, no Merlin — and ships as a portable skill
that any Agent Skills host can load.

### Sources — the agent side

This ships **three surfaces over one set of operations** — a CLI, an Agent
Skill that documents it, and an MCP server. That shape follows current guidance
from both vendors:

- [Agent Skills standard](https://agentskills.io) — the open specification.
  Developed by Anthropic, released as an open standard, and implemented by
  Codex, Cursor, Gemini CLI, GitHub Copilot, VS Code, Goose, Junie and others.
  This is why one folder works across all of them.
- [OpenAI: Build skills](https://developers.openai.com/codex/skills) —
  Codex discovery paths (`.agents/skills` walking up from the working
  directory, `~/.agents/skills`, `/etc/codex/skills`) and the optional
  `agents/openai.yaml` presentation file included here.
- [Agent Skills overview](https://platform.claude.com/docs/en/agents-and-tools/agent-skills/overview)
  — the three-level progressive disclosure model this skill is built around:
  metadata always loaded (~100 tokens), `SKILL.md` on trigger, bundled
  reference files only when read. It also confirms that script *output*, not
  script *source*, enters the context window.
- [Equipping agents for the real world with Agent Skills](https://www.anthropic.com/engineering/equipping-agents-for-the-real-world-with-agent-skills)
  — Skills and MCP are complementary layers, not competitors.
- [Code execution with MCP](https://www.anthropic.com/engineering/code-execution-with-mcp)
  — why calling code beats chaining tool calls when the work is local.
- [Plugins reference](https://code.claude.com/docs/en/plugins-reference)
  — `plugin.json` schema and the `skills/<name>/SKILL.md` layout used here.
- [Plugin marketplaces](https://code.claude.com/docs/en/plugin-marketplaces)
  — `marketplace.json` schema and the `marketplace add` / `plugin install` flow
  in the install section above.

The short version: the skill is the **guidance** — when to act, what to warn
about, which questions are already settled. MCP is the preferred **execution**
surface wherever the host has it, because the argument schemas are typed and
validated before anything runs and each tool gets its own permission prompt
rather than one coarse "allow this command". The CLI is what both fall back to,
and the only option in a shell.

Which one you get depends on the host:

| Host | What it can use |
| --- | --- |
| Claude Code, Codex | Skill for guidance, MCP tools for execution, CLI as fallback |
| Any other Agent Skills host | Skill + CLI — the same `skills/asuswrt` folder |
| Claude Desktop, claude.ai, ChatGPT connectors | MCP only — there is no shell to run a CLI in |
| A terminal, no agent | CLI |

Neither surface costs much when idle. The skill's metadata is ~100 tokens until
someone mentions their router; the MCP server's read tools are the only ones
registered unless you open a gate. And they cannot drift apart: both call the
same `ops.py`, which is the one module they share.

### Discovered by testing, not from any source

Three behaviours are in this codebase because a first attempt got them wrong
against real hardware, and the fix came from reading the library source
afterwards. They are called out because they are not written down anywhere:

1. **`port_forwarding["rules"]` does not always exist.** The key is omitted
   entirely when the rule list is empty. The library's own
   `async_set_port_forwarding_rules` indexes `["rules"]` directly, so it raises
   `KeyError` on a router that has no rules yet. This tool builds the rule list
   itself and calls `async_apply_port_forwarding_rules` to avoid that path.
2. **One CPU sample is never enough.** `usage` is computed against the previous
   sample, so a single fetch always returns `None`. `asuswrt system health` samples twice,
   two seconds apart.
3. **`client.state` is not the online flag.** `ConnectionState` is an `IntEnum`
   where `CONNECTED = 1`; comparing it to a string silently reports every device
   as offline. The real flag is `client.connection.online`.

The port forwarding helpers are additionally marked *legacy, "not tested, not
used, not documented"* in the library source, with a note that they may be
removed ([issue #611](https://github.com/Vaskivskyi/asusrouter/issues/611)).
They are confined to `src/asuswrt/router.py` and the port-forwarding
operations in `src/asuswrt/ops.py`, so a breaking change stays a two-file fix
no matter which surface hits it.

---

## Limitations

- **Stateless.** Every command and every MCP tool call logs in, does its work,
  and logs out — about a second of overhead each. Fine for a person or an
  agent asking a few things; wrong for polling.
- **Not a service.** Built for one user and one router. Calls are serialised,
  not pooled. Do not put it behind a web app or share it between users.
- **One router per config.** `ROUTER_HOST` is a single address; AiMesh nodes
  are not addressed individually.
- **Read-only for content filtering.** URL and keyword filter rules can be read
  but not written. The variable names for them are `unverified` — if
  `asuswrt firewall` shows `? (None)`, that name is wrong for your firmware.
- **Parental control is a global switch.** Per-device rules need the web UI.
- **Limited wireless control.** WPS, WPA mode, frame protection and country
  code are settable; SSID, password, channel and bandwidth are not.
- **Country code may be locked.** Stock firmware often derives it from the
  hardware SKU and silently ignores the write. The command tells you when
  that happens; the fix is the web UI.
- **A firmware update can break this.** Nothing here is a supported API.

## Extending coverage

To add a setting the CLI does not have, find its variable name by diffing:

```bash
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > before.txt
# change exactly one setting in the web UI, save
ssh admin@192.168.50.1 'nvram show 2>/dev/null | sort' > after.txt
diff before.txt after.txt
```

The diff names the variable and shows its encoding. Add it to `FIREWALL_VARS`
in `src/asuswrt/ops.py` to read it — the CLI and the MCP server both pick it up
from there — and to the settings reference with a
`hardware` label. SSH is enabled in the web UI under
*Administration → System → Service → Enable SSH* — it is not exposed in the
mobile app.

## Credits

Built on [asusrouter](https://github.com/Vaskivskyi/asusrouter) by
[Vaskivskyi](https://github.com/Vaskivskyi) (Apache-2.0), which does the actual
protocol work and is also used by the core Home Assistant AsusWRT integration.
This repository is a CLI, a safety model and a documentation layer on top of it.

## License

MIT
