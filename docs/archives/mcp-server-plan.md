# Plan: add an MCP server, rename to `asuswrt`

**Executor:** Sonnet, in this repo, one phase at a time. Each phase ends with a
*Done when* check. Do not start the next phase until it passes.

**Reviewed by:** Codex (GPT-5.6, high reasoning) — session
`01a0618f-308a-7212-a8db-08d801f55abe`. Its blocking findings are folded in
below. What was deliberately *not* adopted, and why, is in Appendix C.

---

## What this is

A Python CLI (`asus-cli`, becoming `asuswrt`) that drives an ASUS home router
over its HTTP API. Around it: an Agent Skill so Claude Code and Codex can use
the CLI, and a Claude Code plugin manifest. This plan adds a third surface —
an MCP server — so any MCP-capable agent app can use the same operations
without a shell.

## Scope — read this before judging any decision below

This is a **home-router admin tool for one person, or one AI agent acting for
that person.** Typical session: a few queries, occasionally one or two config
changes. It is not a service. There are no concurrent users, no tenants, no
uptime target, and no one else's data. The blast radius of a mistake is one
household's Wi-Fi for a few minutes.

Every design choice below is sized to that. Where a "proper server" would
add connection pools, retry policies, lifespan managers and cache-freshness
rules, this plan does the simplest thing that is *correct* for one user, and
says so.

## Nothing is deployed

No one uses this yet. There is no backward compatibility to keep. Old names,
old config paths and old aliases are deleted, not kept.

---

## Decisions

| Question | Decision | Why |
|---|---|---|
| Repo shape | One repo, one PyPI distribution, one Claude Code plugin holding the skill *and* the MCP server | The shared code is 187 lines of transport plus hardware-verified constants. Two repos means publishing that as a dependency and coordinating version bumps for every change |
| Names | Import root `asuswrt`; command `asuswrt`; distribution `asuswrt`; plugin `asuswrt`; skill dir `skills/asuswrt/` | `asus_cli.mcp_server` would read as "the CLI's MCP server". AsusWRT is the firmware family the tool talks to. GitHub repo becomes `asuswrt-tools` (owner does this by hand) |
| Transport | stdio only | The router is a LAN device and the credential is its admin password. HTTP is a ROADMAP.md entry, not code |
| Connection model | **One login per tool call, same as the CLI** | See "Why per-call" below. This single choice removes most of the server-grade complexity a reviewer would otherwise ask for |
| Tool shape | One typed tool per operation, ~22 tools | Schemas with `Literal` and ranges do the agent's validation for it. A generic `read(resource)` tool pushes valid names into prose the agent has to guess |
| Write safety | Reads always registered. Writes only when `ASUSWRT_MCP_ALLOW_WRITES=1`. Reboot and firmware flash also need `ASUSWRT_MCP_ALLOW_DANGEROUS=1` | Gates *hide* tools rather than reject calls, so an unregistered tool costs no context and cannot be retried |
| Confirmation | Every write tool has `confirm: bool = False`. Without it the tool only *previews* — reads current state, reports what would change and why it matters, writes nothing. With it, the tool applies | Same two-step the CLI already uses (`--yes`). See "Why preview, not a token" |
| MCP must not import the CLI | `ops.py` is the only thing both surfaces share. Enforced by a test | stdout is the JSON-RPC channel on stdio; one stray `print` under a tool call kills the connection |

### Why per-call connection

The CLI opens a session, does its work, logs out — once per process. The MCP
server will do exactly that once per tool call. Cost: roughly one second of
login per call. For "a few queries and one or two changes" that is nothing.

What it buys, by *not* holding a session open:

- no lifecycle to manage, no lifespan hook, nothing to tear down on shutdown
- no reconnect logic, and therefore no question of retrying a write that may
  have already landed
- no stale-cache hazard — `asusrouter` caches reads for 5 s per instance, and a
  fresh instance per call has an empty cache
- no interaction with the router's limit on concurrent admin sessions beyond
  what the CLI already does today

One `asyncio.Lock` around every tool call serialises them, so two calls from
an eager host cannot log in at once. That is the whole concurrency story.

### Why preview, not a token

The CLI refuses an unconfirmed mutation because a shell loop has nobody else
to ask. Over MCP the host *usually* shows an approval dialog — but the MCP spec
says tool annotations are hints, and some hosts auto-approve. So the server
cannot lean on the host: it needs its own two-step.

Codex proposed a preview call that returns a short-lived token bound to the
current router state, with the apply call requiring that token. That protects
against state changing between preview and apply by a *different* actor. With
one user and one agent, that actor is the user themself in the web UI at the
same moment, and the protection is not worth a token store. `confirm=True` is
the same guarantee the CLI's `--yes` gives: one call cannot both discover the
consequence and act on it. The preview result is shaped so it can never be
mistaken for success (`status: "preview"`, `applied: false`).

---

## Target layout

```
asuswrt-tools/
├── pyproject.toml
├── ROADMAP.md                       new
├── docs/mcp-server-plan.md          this file
├── .claude-plugin/
│   ├── plugin.json                  declares skill + MCP server
│   └── marketplace.json
├── skills/asuswrt/                  was skills/asus-cli/
│   ├── SKILL.md
│   ├── reference/{settings,recipes}.md
│   └── agents/openai.yaml
├── src/asuswrt/                     was src/asus_cli/
│   ├── router.py                    transport — unchanged role
│   ├── ops.py                       NEW: domain operations, no I/O
│   ├── cli/
│   │   ├── main.py                  was cli.py: argparse, confirm, exit codes
│   │   └── render.py                NEW: payload -> human lines
│   ├── mcp_server.py                NEW: the stdio server
│   └── probe.py
└── tests/                           stays flat
```

Dependency direction, one way only: `router ← ops ← cli` and `router ← ops ←
mcp_server`. Never `mcp_server → cli`, never `cli → mcp_server`.

`mcp_server.py` is a flat module rather than an `asuswrt/mcp/` package so
that `import mcp` inside it unambiguously means the SDK.

---

## Phase 0 — verify, then fix the plan text (≈20 min)

No code. Three facts the plan cannot safely assume:

1. **The MCP Python SDK.** Codex reports the stable line is now **2.x**
   (2.1.1 at review time), with `MCPServer` replacing v1's `FastMCP`, snake-case
   `ToolAnnotations` fields, and `ToolError` under
   `mcp.server.mcpserver.exceptions`. Confirm against PyPI and the SDK docs.
   Then **rewrite every SDK reference in Phase 3 of this file** to match, and
   pin `mcp>=2.1,<3` (or whatever the confirmed line is — never unbounded).
2. **How a Claude Code plugin declares an MCP server** — `mcpServers` inline in
   `.claude-plugin/plugin.json`, or a `.mcp.json` at the plugin root. Check the
   current plugin reference.
3. **`asuswrt` on PyPI.** If taken, stop and report. Do not pick another name.

**Done when:** all three are answered with a source under "Phase 0 findings"
at the bottom of this file, and Phase 3's SDK names have been corrected.

---

## Phase 1 — rename, nothing else (≈20 min)

Mechanical. If a step tempts you to improve something, don't.

1. `git mv src/asus_cli src/asuswrt` and `git mv skills/asus-cli skills/asuswrt`
2. `asus_cli` → `asuswrt` in every import (`grep -rn asus_cli src tests`)
3. `pyproject.toml`: `name = "asuswrt"`; scripts become
   ```toml
   asuswrt = "asuswrt.cli:main"
   asuswrt-probe = "asuswrt.probe:main"     # `probe` was far too generic a name
   ```
   Only these two. `asuswrt.cli.main` and `asuswrt.mcp_server` do not exist yet.
   Leave `version` alone; it is set once, at the end.
4. `router.py::config_paths()` — three candidates, in this order, nothing else:
   `$ASUSWRT_ENV_FILE`, `./.env`, `~/.config/asuswrt/.env`. Delete the three
   legacy paths and the comment explaining them.
5. `ArgumentParser(prog="asuswrt")`, and `asus-cli ` → `asuswrt ` inside the
   hint strings the CLI prints ("Run: asus-cli pf enable --yes" and friends).
6. Delete the old-name wheels in `dist/`.

**Done when:** `uv run pytest` is green with no test file edited except for
the import path. `uv tool install . --force` into a throwaway
`UV_TOOL_DIR` gives a working `asuswrt system`. Skill docs still say
`asus-cli` — that is Phase 5.

**Commit:** `rename package and command to asuswrt`

---

## Phase 2 — split `cli.py` in three commits (≈2 h)

`cli.py` is 1139 lines of domain logic and formatting intertwined. It becomes:

- `ops.py` — one function per operation. Takes a router, returns a payload.
  Never prints, never reads argv or stdin, never imports argparse.
- `cli/render.py` — one function per read. Takes a payload, returns lines.
  Pure.
- `cli/main.py` — argparse tree (unchanged, hidden aliases included),
  `needs_confirm`, `progress`, `emit`, exit codes, and thin `cmd_*` wrappers.

The seam already exists: the read helpers return `(payload, lines)`. `ops`
keeps the payload; `render` takes the lines.

### The payload contract — the part that goes wrong if you rush it

`ops` returns payloads **as the helpers build them today** — library enums,
`PortForwardingRule` objects, integer WAN unit keys and all. It does *not*
run them through `jsonable()`. The CLI's `emit` and the MCP boundary each do
that themselves, as `emit` already does. Reason: `jsonable()` turns enum
`CONNECTED` into a number and the WAN unit key `0` into `"0"`, and the
renderers need the originals. Converting early would silently change the
human output for `wan`, `firewall` and `parental`.

Three renderers need more than the payload:

- `render.firmware(payload, *, notes: bool)` — whether to print the release
  note is a CLI flag, not router state
- `render.overview(sections)` — the sweep prints a client *count* and a short
  firmware line, not the full tables; it is its own renderer, not a
  concatenation of the others
- the spinner stays in the CLI: `cmd_firmware_show` wraps `ops.firmware` in
  `progress(...)`; `ops` never touches stderr

### 2a — golden snapshot, then extract `render.py`

First, before touching any code, add `tests/test_golden.py`: one parametrised
test that runs each canonical read command and each mutation (as a dry run
and with `--yes`) through the existing `invoke()` helper against `FakeRouter`,
and compares `(exit code, stdout, stderr, router.services, router.states,
router.applied_pf_rules)` against `tests/golden.json`. Generate that file
once, now, with a small script; commit it; **do not regenerate it during
Phase 2.** The existing suite mostly checks substrings, so it would stay
green through output changes this snapshot will catch.

Then move the `lines` half of every read helper, plus `_onoff`,
`_client_lines` and the before/after block of `_report_apply`, into
`cli/render.py`. `cli.py` stays a module and imports from it.

**Commit:** `extract rendering from the CLI`

### 2b — extract `ops.py`

Move the payload half of every helper, every mutation's router-facing logic,
and the constants (`FIREWALL_VARS`, `WIFI_VARS`, `BANDS`, `WPA_MODES`,
`MFP_VALUES`, `MFP_NAMES`, `_split_rulelist`, `_bands`, `_update_status`,
`CPU_SAMPLE_SECONDS`, `FIRMWARE_CHECK_SECONDS`) into `ops.py`. Keep the
comments on the constants — they record what was verified on real hardware.
The full function list and return shapes are in Appendix A. `cmd_*` functions
in `cli.py` become `connect → ops → render → emit`.

Add `tests/test_ops.py`: each ops function against `FakeRouter`, asserting
the payload survives `jsonable()` + `json.dumps` and has the expected keys.

**Commit:** `extract domain operations from the CLI`

### 2c — move `cli.py` to `cli/main.py`

Create `cli/__init__.py` and `cli/main.py`, change the script to
`asuswrt = "asuswrt.cli.main:main"`, and update `tests/helpers.py` to
`from asuswrt.cli import main as cli` — it monkeypatches `cli.connect`, so
`main.py` must still import `connect` at module level.

**Commit:** `move the CLI into its own package`

**Done when (all three):** `uv run pytest` green; `test_golden.py` untouched
since 2a; `tests/test_layering.py` (added here, see Phase 3b) passes for
`ops.py`.

---

## Phase 3 — the MCP server (≈2.5 h)

### 3a — `src/asuswrt/mcp_server.py`

**SDK surface (verified in Phase 0, pin `mcp>=2,<3`).**
`from mcp.server.mcpserver import MCPServer, Context` — v1's
`mcp.server.fastmcp.FastMCP` does not exist in this line. Instantiate once,
module level: `mcp = MCPServer("asuswrt")`. Every tool is a plain async
function registered with the decorator:

```python
from mcp.types import ToolAnnotations
from mcp.server.mcpserver.exceptions import ToolError

@mcp.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
async def get_system() -> dict:
    ...
```

`ToolAnnotations` fields are snake_case — `read_only_hint`, `destructive_hint`,
`idempotent_hint`, `open_world_hint`, `title` — never the wire-format
`readOnlyHint`/`destructiveHint`/etc.; the SDK converts snake_case to the
wire format itself. `ToolError` (imported as above, from
`mcp.server.mcpserver.exceptions`, not `mcp.server.fastmcp.exceptions`) is
what `run()` below raises for every anticipated failure — the SDK turns it
into `is_error=True` with the message as tool content, and logs it at INFO
with no traceback. Anything else raised is treated as a crash and reaches
the client with a generic message, so `run()` must not let `AsusRouterError`,
`ConfigError` or a domain `ValueError` escape uncaught.

**Startup.** Load the `.env` file (split the dotenv-loading half out of
`router.load_config()` into `router.load_env()` so it can run without
requiring `ROUTER_PASS`), *then* read the two gate variables, *then* register
tools. Gates are read once; changing them means restarting the server, and
the README says so.

**Every tool call goes through one helper:**

```python
_lock = asyncio.Lock()

async def run(op, *args, timeout=30):
    async with _lock, asyncio.timeout(timeout):
        try:
            async with connect() as router:
                return jsonable(await op(router, *args))
        except ConfigError as e:
            raise ToolError(str(e))          # carries the searched paths, not the password
        except AsusRouterError as e:
            raise ToolError(f"Router error: {e}")
        except ValueError as e:
            raise ToolError(str(e))          # ops' domain refusals
```

Timeouts: 30 s for reads, 60 s for the firmware check and for writes. No
automatic retry of anything — the agent can retry a read itself, and a write
must never be retried by the server. If a write times out or loses the
connection, the `ToolError` says *"The change may or may not have been
applied. Call `<matching read tool>` to check."*

**stdout belongs to the protocol.** Server logging — tool name, duration,
outcome — goes to stderr only. Never the arguments, never config objects.

**Read tools** — always registered, `read_only_hint=True`:

`get_overview`, `get_system`, `get_health`, `get_wan`, `list_clients`,
`get_firewall_and_filters`, `get_parental_control`, `list_port_forwards`,
`list_guest_networks`, `get_wireless`, `check_firmware_update`, `get_nvram`

`get_overview` is a *summary*: counts for clients, no firmware check, no raw
nvram. Its description says: "Use first for broad status. Call a specific tool
afterwards only for detailed rows." `check_firmware_update` is named for what
it does — it makes the router ask ASUS, and takes ~5 s.

**Write tools** — registered only with `ASUSWRT_MCP_ALLOW_WRITES=1`:

`add_port_forward`, `remove_port_forward`, `set_port_forwarding_enabled`,
`set_parental_control_enabled`, `set_guest_network_enabled`, `set_wps_enabled`,
`set_wifi_security`, `set_wifi_country`

**Dangerous tools** — need both gates:

`reboot_router`, `upgrade_firmware`

**The write contract.** Every write tool takes `confirm: bool = False`.

- `confirm=False` → connect, read what the change would touch, return
  `{"status": "preview", "applied": false, "change": "<one sentence>",
  "warnings": [...], "current": {...}}`. Writes nothing.
  `remove_port_forward` lists every rule that would go, so an agent asking
  for `port=443` sees it would remove both the TCP and UDP rule.
- `confirm=True` → apply, return `{"status": "applied", ...}` with the
  before/after/unchanged block for nvram writes, or `{"status": "requested"}`
  for reboot and upgrade, which the API only acknowledges.
- **These are `ToolError`, never a successful result:** the library reports
  `applied=False`; `unchanged` is non-empty (the firmware ignored the write);
  `remove_port_forward` matches nothing; `add_port_forward` clashes without
  `force=True`; `upgrade_firmware`'s `to` does not match what the router
  offers.

`upgrade_firmware` takes a **required** `to: str` — the exact version from
`check_firmware_update`. That is the CLI's "never flash whatever turned up"
rule as a parameter.

**Schemas do the validation.** `Literal["2ghz", "5ghz"]`, `Literal["TCP",
"UDP", "BOTH", "OTHER"]`, ports `1..65535`, guest index `1..3`, country code
two letters, nvram names non-empty, `remove_port_forward` needs at least one
of `name`/`port`.

**Annotations per tool, not per class.** `set_*_enabled` are idempotent;
`add_port_forward`, `remove_port_forward`, `reboot_router`, `upgrade_firmware`
are not. `check_firmware_update` is read-only from the router's point of view
but does make it contact ASUS — say so in the description.

**Descriptions carry the safety rules from SKILL.md**, because the description
is all the agent sees:

| Rule | Tool |
|---|---|
| Forwarding exposes a device to the internet; name 22/3389/445/db ports plainly | `add_port_forward` |
| Rules do nothing while the global switch is OFF | `add_port_forward` (and returned `global_state`) |
| Never reboot unless asked in those words | `reboot_router` |
| Flash writes flash and reboots; power loss bricks; report *requested*, not done | `upgrade_firmware` |
| Restarts both radios, every wireless client drops; the read-back proves it took | `set_wifi_security`, `set_wifi_country` |
| Read-only by design | `get_nvram` |

### 3b — tests

`tests/test_mcp_tools.py`, with `FakeRouter` patched in for `connect`:

- registration: default → the 12 read tools only; writes gate → +8; both
  gates → all 22
- every read tool returns JSON and leaves `FakeRouter.touched` False
- every write tool with `confirm=False` returns `status: "preview"` and
  leaves `touched` False
- every write tool with `confirm=True` sends the same nvram payload / service
  call as its twin in `test_mutations.py`
- each failure in the write contract surfaces as a tool error with the
  expected message — assert the MCP result's error flag, not just that
  Python raised
- `ConfigError` message contains the searched paths and not `ROUTER_PASS`

`tests/test_layering.py`, walking the `ast`:

- `mcp_server.py` does not import `asuswrt.cli`
- `ops.py` imports neither `argparse` nor `asuswrt.cli`
- `ops.py` and `router.py` contain no `print(` and no `sys.stdout`

`tests/test_mcp_stdio.py` — one test. Start `asuswrt-mcp` as a subprocess
with no router configured, send `initialize` and `tools/list` over stdin,
assert every stdout line parses as JSON-RPC and the tool list matches the
gate. This is the only test that catches stdout contamination for real.
No tool is invoked (that needs a router).

`mcp` goes in the `dev` dependency group so these always run. No
`importorskip`.

**Done when:** `uv sync --group dev && uv run pytest` green;
`ASUSWRT_MCP_ALLOW_WRITES=1 asuswrt-mcp` answers `tools/list` by hand.

**Commit:** `add stdio MCP server`

---

## Phase 4 — plugin packaging (≈30 min)

Declare the server in the plugin using the Phase 0 finding. Expected:

```json
"mcpServers": { "asuswrt": { "command": "asuswrt-mcp" } }
```

**Be honest about what the plugin delivers.** It registers the server; it
does not install the Python program. A clean plugin install with no
`asuswrt` distribution present will try to start a command that does not
exist. So: `plugin.json`'s description and the README both state the
prerequisite — install `asuswrt` with the `mcp` extra first — and the check
below proves the failure mode is legible.

Rename plugin and marketplace entries to `asuswrt`; point `repository` and
`source` at `github.com/gittycat/asuswrt-tools`.

**Done when:** in a clean shell with no `asuswrt-mcp` on PATH,
`claude --plugin-dir .` reports the server failing to start with a message
that names the missing command. Then install the distribution and repeat:
skill listed, server connected.

**Commit:** `ship the MCP server with the plugin`

---

## Phase 5 — documentation and version (≈1 h)

1. **`ROADMAP.md`**, two entries:
   - *Streamable HTTP transport.* stdio today because the router is LAN-only
     and the credential is its admin password. HTTP would let a hosted agent
     reach it and would raise who-may-connect, what-authenticates, and which
     interface to bind — worth answering only against a concrete use case.
   - *Read-only default.* What would have to be true to ship writes on by
     default.

2. **`skills/asuswrt/SKILL.md`**
   - `name: asuswrt`; every `asus-cli` command → `asuswrt`
   - New section near the top: when `mcp__asuswrt__*` tools are present,
     use them for **reads**. For **writes**: if the MCP write tool exists,
     use it (preview, show the user, then `confirm=True`). If it is absent,
     say MCP writes are disabled — **do not fall back to the CLI to get
     around the gate.** Use the CLI mutation path only when the user asks for
     it, and keep its dry-run-then-`--yes` sequence.
   - Keep the "older names still work" paragraph for now (see *Deferred*).

3. **`reference/recipes.md`, `reference/settings.md`, `agents/openai.yaml`** —
   names only.

4. **`README.md`** — the title already says "MCP and SKILL"; make it true.
   - Install: `uv tool install "git+https://github.com/gittycat/asuswrt-tools" --with mcp`
     (verify the uv flag for extras on tool installs)
   - "MCP server" section: the two gates, restart-to-apply, the tool list,
     and a copy-pasteable client config block
   - Positioning, consistent with SKILL.md: the skill is the *guidance*
     (when to act, what to warn about); MCP is the preferred *execution*
     surface when the host has it; the CLI is what both fall back to
   - Config path `~/.config/asuswrt/.env`; tests table gains the new files

5. **`env.example`** — new path and `ASUSWRT_ENV_FILE`.

6. **Version.** Set `0.6.0` once, in `pyproject.toml` and `plugin.json`.

**Done when:**
`git grep -nE 'asus[-_]cli' -- . ':(exclude)docs/'` returns nothing.

**Commit:** `document the MCP server and the rename`

---

## Deferred until after the refactor

The argparse tree has hidden aliases from before it was regularised: `info`,
`status`, `pf`, `list`, `firmware info`, `wifi security`, `wifi country`.
`pf` and `list` are handy; the rest are legacy. **Leave the parser alone
through all phases** — deciding this mid-refactor means editing parser tests
during a phase whose gate is that they don't change. Raise it with the owner
afterwards.

## Out of scope

HTTP transport, MCP resources or prompts, any router capability the CLI does
not already have, PyPI publication, swapping the `asusrouter` library, a uv
workspace, renaming again.

---

## Appendix A — `ops.py` functions

Reads. Each returns the payload the matching helper builds today.

| Function | From |
|---|---|
| `system(router)` | `_system_show` |
| `health(router, cpu_sample)` | `_system_health` |
| `wan(router)` | `_wan_show` |
| `clients(router, online_only=False)` | `_client_rows` |
| `firewall(router)` | `_firewall_show` |
| `parental(router)` | `_parental_show` |
| `port_forwarding(router)` | `_pf_show` — rules stay `PortForwardingRule` objects |
| `guest(router)` | `_guest_show` |
| `wifi(router)` | `_wifi_show` |
| `firmware(router, wait)` | `_latest_firmware` + `_update_status` → `{**firmware, "status", "latest"}` |
| `nvram(router, names)` | body of `cmd_nvram` |
| `overview(router, cpu_sample, include_firmware, wait)` | body of `cmd_show`, minus rendering |

Writes. Each returns a dict and prints nothing. Domain refusals are
`ValueError` with the message the CLI prints today.

| Function | Returns |
|---|---|
| `port_forward_add(router, rule, force=False)` | `{"applied", "rule", "clash", "global_state"}` |
| `port_forward_remove(router, name=None, port=None, proto=None)` | `{"applied", "removed": [...]}` — empty means no match |
| `set_port_forwarding(router, enabled)` | `{"applied"}` |
| `set_parental_control(router, enabled)` | `{"applied"}` |
| `set_guest_network(router, band, index, enabled)` | `{"applied"}` |
| `set_wps(router, enabled)` | `apply_nvram` result |
| `set_wifi_security(router, band, mode, mfp=None)` | `apply_nvram` result |
| `set_wifi_country(router, band, code)` | `apply_nvram` result |
| `reboot(router)` | `{"requested"}` |
| `firmware_upgrade(router, wait, to, beta=False)` | `{"requested", "current", "latest"}`; `ValueError` on up-to-date / unverifiable / `to` mismatch |

## Appendix B — result shapes at the MCP boundary

```
preview     {"status": "preview",   "applied": false, "change": str, "warnings": [str], "current": {...}}
applied     {"status": "applied",   "applied": true,  ...before/after/unchanged for nvram writes}
requested   {"status": "requested", ...}                           reboot, upgrade
error       ToolError with a message that says what to do next
```

## Appendix C — reviewer findings not adopted, and why

Codex's review assumed a long-lived shared connection and sized its findings
to that. Choosing per-call connection removed the need for most of them.
The rest were judged against the scope statement at the top.

| Finding | Decision |
|---|---|
| Lifespan-owned connection manager with retained context manager | Not needed — no connection outlives a call |
| Force-fresh reads to defeat the library's 5 s cache | Not needed — a fresh `AsusRouter` per call has an empty cache |
| Retry reads once, never retry writes, indeterminate-outcome handling | Halved: no automatic retries at all. The indeterminate-outcome *message* is kept |
| Preview token bound to router state, single-use, expiring | Replaced by `confirm: bool`. The token guards against a second actor changing state between preview and apply; there is no second actor |
| Per-tool-class deadline policy including lock wait | One timeout per call, two values |
| Cancellation semantics | Covered by the timeout message; per-call connection means cancellation just drops that session |
| Structured logging | One stderr line per call |
| Fix `FakeRouter.async_get_data` ignoring `force` | Not needed once nothing depends on `force` |
| Subprocess test that also invokes a tool | Kept the subprocess test, but only `initialize` + `tools/list` — invoking a tool needs a router |
| Golden characterisation tests | Adopted, as one snapshot file |
| Three commits for Phase 2, entry points per phase, SDK 2.x, plugin prerequisite, CLI-fallback bypass, discriminated result shapes, `Literal` schemas, tool renames, no `importorskip`, version set once | Adopted |

## Phase 0 findings

Checked 2026-09-02.

1. **MCP SDK.** Confirmed: the stable line is **2.x** (2.1.1 is current on PyPI
   as of this check; 2.0.0 was the first stable 2.x release). v1's
   `mcp.server.fastmcp.FastMCP` is gone in v2 — the server class is
   `MCPServer`, imported `from mcp.server.mcpserver import MCPServer`. Tools
   register with the `@mcp.tool(...)` decorator, annotated via
   `annotations=ToolAnnotations(...)` (`ToolAnnotations` re-exported from
   `mcp.types`), whose fields are snake_case: `read_only_hint`,
   `destructive_hint`, `idempotent_hint`, `open_world_hint`, `title` — not the
   wire-format `readOnlyHint`/etc. `ToolError` lives at
   `mcp.server.mcpserver.exceptions.ToolError`; raising it returns
   `is_error=True` with the message as tool content, logged at INFO with no
   traceback (any other exception is treated as a crash). The SDK's own
   migration guide pins the dependency as `mcp>=2,<3`.
   Sources: [PyPI: mcp](https://pypi.org/project/mcp/) (2.1.1, checked live);
   [Migration Guide: v1 to v2](https://py.sdk.modelcontextprotocol.io/migration/);
   [python-sdk README](https://github.com/modelcontextprotocol/python-sdk/blob/main/README.md);
   [Tools — MCP Python SDK](https://py.sdk.modelcontextprotocol.io/servers/tools/).
2. **Plugin MCP declaration.** Confirmed: Claude Code supports **both** —
   an `mcpServers` field inline in `.claude-plugin/plugin.json`, or a
   standalone `.mcp.json` at the plugin root. Either is valid for a
   single-server plugin like this one; the plan's Phase 4 sketch (inline
   `mcpServers` in `plugin.json`) is a supported form, not a guess.
   Source: [Plugins reference — Claude Code Docs](https://code.claude.com/docs/en/plugins-reference).
3. **PyPI `asuswrt`.** Confirmed **available** — `https://pypi.org/project/asuswrt/`
   returns PyPI's "Page Not Found (404)", i.e. no such project exists.
   Verified live in-browser (not cached), 2026-09-02, since a bare fetch of
   that URL can render as an ambiguous empty shell. No stop condition
   triggered; proceed with the name as planned.
   Source: [pypi.org/project/asuswrt/](https://pypi.org/project/asuswrt/) (404, checked live).
