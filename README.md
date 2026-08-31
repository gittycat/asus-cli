# ASUS Router MCP and SKILL for AI Agents

## TLDR

> Use the SKILL if you're using Claude Code or Codex. It consumes less than 2400 tokens.
>
> The MCP server is for AI apps or web based interfaces. It will still be lazy
> loaded to minimise context use. That's what CC and Codex do as of Aug 2026
> instead of loading the full schema in context.
>
> Both include a custom python tool, **asus-cli**, to connect to a home ASUS (AsusWRT) router.  The tool can be used manually but it aimed at AI agents. As such,a few railguards and utilities were built in such as not including direct nvram set, including json output everywhere, using guessable non-verb grammar, and requiring confirmation for any config change

The MCP and SKILL are loaded into the context when you write **asus router** in
your prompt. The word "router" alone is way too generic in a tech context.
That would likely result in the skill being needlessly loaded
for unrelated requests. Once loaded, the model doesn't need the asus hint.
It'll use the skill for requests such as
`who's on my WiFi?` or `what devices are on my home network?`

This `aus-cli` python tool uses the unpublished HTTP API of the ASUS router.
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

**1. Install the CLI program that the skill will drive**

```bash
uv tool install git+https://github.com/gittycat/asus-cli
```

OR ...  
 from a local git clone, which also builds the wheel for you:

```bash
git clone https://github.com/gittycat/asus-cli
uv tool install ./asus-cli --force
```

Either way `uv` puts the `asus-cli` command in `~/.local/bin`; run
`uv tool update-shell` once if that directory is not on your `PATH`.

**2. Save your router credentials**

```bash
mkdir -p ~/.config/asus-cli
cat > ~/.config/asus-cli/.env <<'EOF'
ROUTER_HOST=192.168.50.1
ROUTER_USER=admin
ROUTER_PASS=your-router-password
EOF

asus-cli system    # should print your model, firmware and MAC
```

**3. Install the skill**

```bash
# Claude Code
claude plugin marketplace add gittycat/asus-cli
claude plugin install asus-cli@asus-cli -y

# Codex
mkdir -p ~/.agents/skills
git clone --depth 1 https://github.com/gittycat/asus-cli /tmp/ars \
  && cp -r /tmp/ars/skills/asus-cli ~/.agents/skills/ && rm -rf /tmp/ars
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
Goose, Junie — reads the same `skills/asus-cli` folder from its own skills
directory. Check your agent's docs for the path; the skill needs no changes.

**Claude Code, one clone with the source included.** Cloning into your skills
directory registers it as a plugin *and* gives you something to install the CLI
from:

```bash
git clone https://github.com/gittycat/asus-cli ~/.claude/skills/asus-cli
uv tool install ~/.claude/skills/asus-cli --force
```

**Claude Code, one session only**, while editing a local checkout:

```bash
claude --plugin-dir /path/to/asus-cli
```

Do not combine these with the marketplace install — the skill would load twice
under two identities.

**Updating:** `claude plugin marketplace update asus-cli`, or
`git pull` in the clone.

**Config lookup order**, first match wins:

1. `$ASUS_ENV_FILE`, if you set it
2. `.env` in the current directory
3. `~/.config/asus-cli/.env`

Older config directories (`~/.config/asus-skill`, `~/.config/asus-router`) are
still read after those, so an existing install keeps working after the rename.

`env.example` is a starting template. If `asus-cli system` gives a login error, check
that your account is the router **admin**, not a limited family member.

</details>

## asus-cli tool

You can call the asus-cli tool works on its own, without an agent:

```bash
asus-cli show                    # all of the below in one connection
asus-cli system                  # model, firmware, mac, aimesh
asus-cli system health           # uptime, cpu, ram, wan
asus-cli clients --online        # who's connected
asus-cli wan                     # ip, gateway, dns, protocol
asus-cli firewall                # firewall + filters + parental control
asus-cli parental                # parental control state and rules
asus-cli portforward             # port forwarding switch and rules
asus-cli guest                   # guest networks
asus-cli wifi                    # wps, wpa mode, frame protection, country
asus-cli firmware --notes        # installed vs offered version, release note
asus-cli nvram get vts_rulelist  # any raw setting
```

Add `--json` to any of them for machine-readable output.

Changing things takes two steps by design:

```bash
asus-cli portforward add --name Plex --port 32400 --to-ip 192.168.50.20
# → prints what it would do, changes nothing, exits 3

asus-cli portforward add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
# → applies it
```

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

---

## Safety

The design assumes an AI agent will be driving this, so the guardrails are in
the tool rather than in the instructions.

- **Nothing changes without consent.** `--yes` acts; at a terminal you get a
  `[y/N]` prompt; with neither, the command prints what it would do and exits
  3 without touching anything. Silence never means yes, so a bare mutating
  command is a safe dry run.
- **No raw writes.** `asus-cli nvram get` reads any setting; there is deliberately no
  write counterpart. Blind nvram writes are how working configurations get
  destroyed. Only reviewed, named operations can write.
- **Writes are verified, not assumed.** The router reporting that it ran the
  service does not mean the value stuck — a country code write is routinely
  accepted and then ignored. Every `asus-cli wifi` command reads the variables back
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
specifics in [`settings.md`](skills/asus-cli/reference/settings.md) were
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
[settings reference](skills/asus-cli/reference/settings.md) with provenance
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

The choice to ship a **CLI plus a Skill**, rather than an MCP server, follows
current guidance from both vendors:

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

The short version: the router is a local system reachable by a local library.
A skill that documents a CLI costs ~100 tokens until someone mentions their
router, whereas an MCP server announces its whole tool surface at startup — and
the skill runs in every compatible agent rather than one vendor's.

**When an MCP server would be the better choice.** If you want this in a host
with no shell — Claude Desktop, claude.ai, ChatGPT connectors — a skill cannot
help, because there is nothing to run the CLI. MCP also gives typed argument
schemas validated before execution, per-tool permission prompts instead of one
coarse "allow this command", and a single remote deployment serving many
clients rather than an install on every machine. The two are not exclusive:
an MCP server would be a thin wrapper over the same functions in
`src/asus_cli/router.py`.

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
   sample, so a single fetch always returns `None`. `asus-cli system health` samples twice,
   two seconds apart.
3. **`client.state` is not the online flag.** `ConnectionState` is an `IntEnum`
   where `CONNECTED = 1`; comparing it to a string silently reports every device
   as offline. The real flag is `client.connection.online`.

The port forwarding helpers are additionally marked *legacy, "not tested, not
used, not documented"* in the library source, with a note that they may be
removed ([issue #611](https://github.com/Vaskivskyi/asusrouter/issues/611)).
They are confined to `src/asus_cli/router.py` and the two `pf` commands so a
breaking change stays a one-file fix.

---

## Limitations

- **Read-only for content filtering.** URL and keyword filter rules can be read
  but not written. The variable names for them are `unverified` — if
  `asus-cli firewall` shows `? (None)`, that name is wrong for your firmware.
- **Parental control is a global switch.** Per-device rules need the web UI.
- **Limited wireless control.** WPS, WPA mode, frame protection and country
  code are settable; SSID, password, channel and bandwidth are not.
- **Country code may be locked.** Stock firmware often derives it from the
  hardware SKU and silently ignores the write. The command tells you when
  that happens; the fix is the web UI.
- **AiMesh nodes are not addressed individually.** Everything applies to the
  main router.
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
in `src/asus_cli/cli.py` to read it, and to the settings reference with a
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
