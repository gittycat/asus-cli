# ASUS Router MCP for AI Agents

Allows you to control a local Asus WRT home router via AI prompts instead of using the Asus web admin interface or ios app.

Works with any agent that speaks MCP — Claude Code, Codex, Claude Desktop,
ChatGPT and Gemini among them.

It uses the included small python program, `asuswrt` that speaks the router's
unpublished HTTP API — the same one the official ASUS mobile app uses. No SSH,
no scraping the web UI.


---

## Installation

You need [uv](https://docs.astral.sh/uv/), your router's **admin** password, and
a machine on the same network as the router.

Save the password first — everything needs it. Then register the MCP server
with whichever agent you use.

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

### Install the MCP server

**Claude Code** — the plugin registers the server for you, read-only:

```bash
uv tool install "asuswrt[mcp] @ git+https://github.com/gittycat/asuswrt-tools"
claude plugin marketplace add gittycat/asuswrt-tools
claude plugin install asuswrt@asuswrt
```

Or register it yourself, which is also how you allow writes:

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
[in the reference](docs/reference.md#claude-desktop-by-hand).

### Check it works

```bash
asuswrt system     # your model, firmware and MAC
```

If that prints your router, the agent side works too.

---

## Try it

Say **asus** in your first request so the tools load. After that the agent
keeps using them on its own.

Ask:

```
What devices are connected to my Asus router?
Review the security settings on my Asus router
Is my Asus router's firmware up to date?
Is the asus router's admin page reachable from the internet?
The internet feels slow — check the asus router's CPU, memory and WAN
Which DNS servers is my Asus router using?
Can devices open their own ports on my Asus router?
```

Change:

```
Open port 32400 on the asus for my media server
Turn on the guest WiFi on the asus for my visitors
Turn off WPS on my Asus router
Point the asus router's DNS at 8.8.8.8
Turn off UPnP on my Asus router
Turn off the lights on my Asus router
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
  returned; the tools refuse to reboot unless you used the word; MCP write
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
- **UPnP is a single switch, and the off→on→off round trip is untested.** The
  three UPnP variables are all written and read back, but they were already off
  on the router this was built against, so a genuine on→off transition has not
  been confirmed on hardware. Check `asuswrt upnp` after disabling it.
- **DNS control is the WAN pair only.** The resolvers the router forwards to can
  be set, or handed back to the ISP. IPv6 resolvers, per-client DNS Filter rules
  and DNS-over-TLS profiles still need the web UI. A successful write proves the
  value stuck in nvram, not that resolution changed — verify with a lookup.
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
[`settings.md`](docs/settings.md#features-with-a-settled-answer).

Tested on an ASUS RT-AX59U running stock firmware `3.0.0.4` (not Merlin), with
the `asusrouter` library 1.21. Other AsusWRT routers should work — the library
lists 27 confirmed models from WiFi 4 through WiFi 7, on stock and Merlin — but
the details in [`settings.md`](docs/settings.md) were
confirmed on an RT-AX59U only. Two data types (`system`, `temperature`) return
nothing on this model and are not used.

---

## Details

Install paths, where the password is read from, the MCP
tool list and its two-call writes, the Claude Desktop extension, and how to add
a setting the tool does not cover are in
[`docs/reference.md`](docs/reference.md). Problems are in
[`docs/troubleshooting.md`](docs/troubleshooting.md).

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
