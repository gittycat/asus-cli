# Review request: adding an MCP server to a CLI + Agent-Skill repo

**Reviewer:** GPT-5.6, high reasoning. **Role:** adversarial design review, not
implementation. **Artefact under review:** `docs/mcp-server-plan.md` (444
lines, in this repo). This brief gives you the context that plan assumes, the
reasoning behind its settled decisions, and the specific questions I want
answered. Read the plan first, then this.

I wrote the plan. It will be executed by a weaker model (Sonnet) working phase
by phase, which is why it is prescriptive. Assume the executor will follow it
literally and will not notice a gap you do not name.

---

## 1. Source files worth opening

| Path | Lines | Why it matters to the review |
|---|---|---|
| `src/asus_cli/cli.py` | 1139 | The file being split. Argparse tree, all commands, all rendering |
| `src/asus_cli/router.py` | 187 | Transport layer: `connect`, `read_nvram`, `apply_nvram`, `jsonable` |
| `tests/helpers.py` | ~260 | `FakeRouter` and the `invoke()` end-to-end harness |
| `skills/asus-cli/SKILL.md` | 192 | The safety rules that must survive into MCP tool descriptions |
| `pyproject.toml` | 30 | uv_build, src layout, Python ≥3.13 |
| `.claude-plugin/plugin.json` | 15 | Claude Code plugin manifest |

---

## 2. What this repo is

A Python CLI (`asus-cli`) that drives an ASUS RT-AX59U router over AsusWRT's
undocumented HTTP API — the one the official ASUS mobile app uses. It wraps the
third-party `asusrouter` library. Around it: an Agent Skill (`SKILL.md` plus two
reference docs) and a Claude Code plugin manifest. The CLI is written *for*
agents to drive; the skill is how Claude Code and Codex reach it.

**It has never been released or used by anyone but the author.** No backward
compatibility is owed to any name, path, or interface. This is load-bearing —
several plan steps delete things a public project could not.

### Properties of the existing design that the plan must preserve

These are deliberate and hardware-informed. Treat a change to any of them as a
regression unless you argue the point explicitly.

1. **The confirmation contract.** Every mutating command: `--yes` acts
   immediately; a TTY prompts `[y/N]`; **no TTY and no `--yes` prints what it
   would do, exits 3, and touches nothing.** Exit 3 means "refused for want of
   consent", distinct from exit 1 "tried and failed". A bare mutating command
   is therefore a safe dry run. This exists because an agent driving a shell has
   no approval gate — the agent both chooses and runs the command.

2. **Writes are verified by read-back, not by the API's success flag.**
   `apply_nvram` reads the variables before, writes, reads after, and returns
   `{ok, before, after, unchanged}`. Stock firmware accepts some writes and then
   silently ignores them — the wireless country code is the confirmed case. `ok`
   alone is a lie; `unchanged` is the truth.

3. **No raw nvram writes are exposed.** `nvram get` is read-only by design.
   Writes exist only as named, bounded commands.

4. **Read helpers already return `(payload, lines)`** — the machine-readable
   dict and the human lines, side by side. This is the seam the refactor uses.

5. **Constants are hardware-verified.** `FIREWALL_VARS`, `WIFI_VARS`,
   `WPA_MODES`, the `DEFAULT_NVRAM` fixture — all observed on a live RT-AX59U,
   including the awkward values (`fw_log_x` is the string `"none"`, not 0/1;
   the 5 GHz country code is the worldwide default `"AA"`). Comments recording
   these must survive the move.

6. **The test suite is the specification.** It drives argv → argparse → command
   → captured stdout, replacing only the `AsusRouter` object. `read_nvram`,
   `apply_nvram`, the formatters and the parser all run for real. Nothing
   contacts a router.

---

## 3. Settled decisions and why

Do not relitigate these on preference. Do challenge any of them if you have a
concrete failure case — say which one and what breaks.

| Decision | Reasoning |
|---|---|
| One repo, one distribution, one plugin holding skill + MCP server | The shared asset is a 187-line transport module plus the nvram/enum constants. Splitting repos means publishing that as a dependency and version-bumping across repos for every change. Drift between skill docs and MCP tool descriptions is the failure mode that actually matters, and one repo makes it testable |
| Rename `asus_cli` → `asuswrt` everywhere | Once MCP lives in the package, `asus_cli.mcp_server` reads as "the CLI's MCP server". `asuswrt` is the firmware family the tool speaks to. 15 occurrences, 11 files |
| No aliases, no legacy config paths | Nothing is deployed. A third rename is cheap now and expensive after MCP tool names reach agents' saved configs |
| stdio transport only | The router is a LAN device and the credentials are the router's admin password. HTTP raises who-may-connect, what-authenticates, what-interface — questions with no answer until there is a concrete hosted-agent use case. Recorded in ROADMAP.md instead |
| One typed tool per operation, ~22 tools | Discoverability and schema validation for the agent. The alternative — a generic `asus_read(resource)` — pushes valid resource names into prose the agent has to guess at |
| Reads always registered; writes behind `ASUSWRT_MCP_ALLOW_WRITES=1`; reboot and firmware flash behind a second flag | The blast radius is a household's connectivity. Reboot drops every connection; a firmware flash that loses power bricks the device |
| Gates *hide* tools rather than reject calls | A registered-but-always-failing tool costs context and teaches the agent to retry. Absence is unambiguous |
| **No `dry_run` parameter on write tools** | See §5, question 3. This is the decision I most want challenged |

---

## 4. The plan in brief

Six phases, each ending in a check the executor must pass before continuing.

- **Phase 0 — verify three facts.** Current MCP Python SDK version and API
  surface (`FastMCP`, `ToolAnnotations`, `ToolError`); whether a Claude Code
  plugin declares an MCP server via `mcpServers` in `plugin.json` or a
  `.mcp.json`; whether `asuswrt` is free on PyPI. Deliberately unverified in the
  plan so the executor looks them up rather than trusting my recall.

- **Phase 1 — rename.** Mechanical. `src/asus_cli` → `src/asuswrt`,
  `skills/asus-cli` → `skills/asuswrt`, imports, `pyproject.toml` scripts,
  config paths reduced to three, stale `dist/` wheels deleted. Tests green,
  unedited.

- **Phase 2 — split `cli.py`.** Into `ops.py` (domain verbs, JSON-serialisable
  returns, no printing, no argparse) + `cli/render.py` (payload → lines, pure)
  + `cli/main.py` (argparse, `needs_confirm`, exit codes). Roughly 12 read ops
  and 10 write ops, listed individually in the plan with their return shapes.
  **The gate: no assertion text in the five existing test files may change.**
  If one has to, the refactor changed behaviour.

- **Phase 3 — the MCP server.** `src/asuswrt/mcp_server.py`, flat module (not
  `asuswrt/mcp/`, to keep `import mcp` unambiguous). One shared `AsusRouter`
  behind an `asyncio.Lock`, created lazily, one reconnect-and-retry on
  `AsusRouterError`. 12 read tools, 8 write tools, 2 dangerous tools. Safety
  rules from SKILL.md mapped one-by-one onto tool descriptions.
  `upgrade_firmware` takes a **required** `to` naming the offered version.
  New tests: `test_mcp_tools.py`, `test_layering.py`.

- **Phase 4 — plugin packaging.** Declare the server in `plugin.json` so one
  `claude plugin install` delivers skill + MCP server.

- **Phase 5 — documentation.** `ROADMAP.md` (HTTP transport, and the read-only
  default), SKILL.md updated to prefer `mcp__asuswrt__*` tools when present and
  fall back to the shell otherwise, README, `env.example`.

Deferred on purpose to after Phase 5: whether to strip the hidden argparse
aliases (`info`, `status`, `pf`, `list`, …). Deciding it mid-refactor would
mean editing parser tests during a phase whose gate is that they do not change.

---

## 5. Questions I want answered

Ranked. Answer 1–4 even if you have nothing critical to say about them.

**1. Is the shared connection right for a long-lived server?**
The CLI opens one connection per process. The MCP server is long-lived, so I
specified one cached `AsusRouter` behind an `asyncio.Lock`, lazily created,
with one reconnect-and-retry on `AsusRouterError`. Concerns I want addressed:
AsusWRT session tokens expire server-side and the router allows a limited
number of concurrent admin sessions; a global lock serialises every tool call,
which is correct for a device that dislikes concurrency but hides latency;
`_latest_firmware` sleeps ~5 s while holding it. Is per-call connect actually
the safer default? Is reconnect-once too few, or hiding a real fault?

**2. Does the `ops.py` seam lose information the renderer needs?**
`ops` must return JSON-serialisable dicts, so `ops.port_forwarding` returns
rules as dicts where `_pf_show` returned `PortForwardingRule` objects, and
`render` moves from `r.name` to `r["name"]`. Walk the nine read helpers in
`cli.py` and tell me whether any of them renders something the payload does not
carry — because Phase 2's gate is byte-identical stdout, and a helper whose
lines use a local variable absent from its payload will fail that gate late.
`_system_health` and `_firewall_show` are the two I am least sure about.

**3. Is dropping `dry_run` correct, or am I removing the only
consequence-surfacing mechanism?**
My argument: exit-3 exists because a shell loop has no gate, whereas over MCP
the host's approval dialog is that gate; a tool that refused its first call
would teach the agent to retry with the bypass; and `dry_run=True` returns a
success-shaped payload for a change that did not happen, which an agent can
report as done. So instead: consequences go in tool *descriptions*, write tools
return `clash` / `global_state` / `before` / `after` / `unchanged`, and the read
tools serve "look before you leap".
The counter I cannot dismiss: **hosts that auto-approve tool calls** — an
allowlist, or a fully autonomous agent — have no dialog, and then nothing
surfaces the consequence before the write lands. Is that enough to keep a dry
run? If so, what shape avoids the report-it-as-done failure — a distinct
`preview_*` tool, a mandatory `confirm_token` returned by a preview call, or
something else?

**4. Does gating-by-non-registration break real clients?**
Tools are registered or not at process start based on env vars. A client that
caches `tools/list` across a restart, or a user who sets the env var and
restarts expecting new tools, is the case I am unsure of. Is `tools/list_changed`
relevant here, or is a start-time decision the norm? Any client known to
misbehave when a server's tool set changes between runs?

**5. Anything missing that a production stdio MCP server needs.**
The plan covers the stdout-is-the-protocol hazard, error mapping, and the write
gates. I am probably missing: per-call timeouts (the router can hang; the
firmware check already sleeps 5 s), cancellation, whether any error path can
put the router password into a `ToolError` message, and structured logging to
stderr. Name what else.

**6. Tool surface.** 12 read tools including `get_overview`, which returns
everything the other 11 do in one connection. Is that redundancy justified for
an agent, or does it invite "call overview, then call the specific one anyway"?
Any tool name likely to be misread — `get_firewall` returns filters *and* a
parental-control summary, while `get_parental_control` returns the rules.

**7. Phase ordering and risk.** Rename before refactor: right order, or should
the refactor land first so the rename is a pure `git mv`? Is Phase 2 too large
for one commit — should ops/render/main be three?

**8. Is "no existing assertion may change" a sound gate for Phase 2?**
It is the strongest signal I have that the refactor is behaviour-preserving.
Where is it weak? What does the current suite not cover that the split could
break silently?

---

## 6. Out of scope — do not propose

Adding HTTP transport, MCP resources or prompts, any new router capability
beyond what the CLI already does, PyPI publication, swapping the `asusrouter`
library, restructuring into a uv workspace, or renaming again.

---

## 7. Output I want

For each of the eight questions: a direct answer, and where you disagree, the
concrete failure case — inputs, state, what goes wrong — not a preference.

Then, separately:

- **Blocking problems.** Things that will produce broken or unsafe code if the
  executor follows the plan literally. For each: which phase, which step, and
  the corrected text.
- **Gaps.** Things the plan does not say that a literal executor would get
  wrong by omission.
- **Cuts.** Anything specified that is not worth its complexity.

Rank all three lists by severity. Skip anything you would only mention for
completeness.
