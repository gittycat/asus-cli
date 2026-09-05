---
name: asuswrt
description: Inspect and control an ASUS (AsusWRT) home router over its HTTP API - connected devices, WAN and internet status, CPU and RAM, firewall state, port forwarding, guest WiFi, parental control and WiFi security (WPS, WPA2/WPA3, country code). The request must name the router explicitly: use this skill only when it says "asus", or asks who is connected to my WiFi / what devices are on my home network. Do NOT load on the word "router" by itself - in a codebase that almost always means Express, React Router, vue-router, or API and message routing.
---

# ASUS router control

Two surfaces reach the same router: the `asuswrt` command and the
`mcp__asuswrt__*` tools. Both speak the router's HTTP API — the one the ASUS
mobile app uses. No SSH, no web UI.

## Which surface

**If `mcp__asuswrt__*` tools are present, prefer them** — same operations,
typed and validated, and each tool's own description carries its safety notes
and its preview-then-apply contract. Read the tool's description; do not
re-derive it from here.

**A missing write tool means writes are switched off in the server's config.**
Say so and stop. **Do not run the CLI mutation instead** — the user turned them
off on purpose.

Use the CLI when no MCP tools are present, or when the user asks for it by name.
The [rules for both surfaces](#rules-for-both-surfaces) apply either way.

## The CLI

### Before anything else

```bash
command -v asuswrt || echo "not installed"
```

If missing, tell the user to run `uv tool install .` from the repository and
stop. Do not work around it by writing your own Python.

If a command reports that `ROUTER_PASS` is not set, it prints the exact paths it
searched. Relay them and stop — never ask the user for the password in chat.

The router's address is the machine's default gateway, read at every run. If a
command says the gateway could not be detected, ask the user for the router's
address — do not guess one.

**A `No route to host` error does not mean the router is down.** The route was
rejected before any packet left the machine, which happens both when the router
is genuinely absent and when the local machine refuses to reach it. The error
already lists the known causes and a `curl` command that separates them. **Show
that whole message to the user** rather than summarising it as "the router is
unreachable" or diagnosing it yourself — the causes are not settled, and
`docs/troubleshooting.md` records what to capture before probing, because
probing destroys the evidence.

### Reading state

The command tree is **noun then verb**, and `show` is the only read verb, so a
bare noun means `show`. Pick the noun; you never have to guess the command.

| Noun | What it reads |
|---|---|
| `system` | model, firmware, MAC, serial, AiMesh — nothing that moves |
| `system health` | uptime, CPU, RAM, WAN summary — everything that moves |
| `wan` | internet connection detail |
| `dns` | WAN resolvers, and what LAN clients are told to use |
| `upnp` | whether devices can open their own inbound ports |
| `led` | router status lights |
| `clients` | known devices; `--online` for only the connected ones |
| `firewall` | firewall, DoS, filters, parental control summary |
| `parental` | parental control state and rules |
| `portforward` | the global switch and the rules |
| `guest` | guest wireless networks |
| `wifi` | radio, WPA mode, MFP, country code, WPS |
| `firmware` | installed version and what ASUS is offering right now |
| `nvram get <var> ...` | any raw setting the nouns do not cover |

**Start with `asuswrt show`** for anything resembling "how is the router". Each
noun is a separate process and therefore a separate login, so eight nouns cost
eight handshakes and `show` costs one. It omits the firmware check and prints a
client count rather than the client table.

Add `--json` when you need to parse; `asuswrt --json show` returns one object
keyed by noun. Report the plain output — it is already formatted for reading.

Two readings are slow, and say why: `system health` and `show` take ~2 s (CPU
is a delta between two samples), `firmware` ~7 s (it makes the router query
ASUS rather than trust the months-stale nvram copy). Older names — `info`,
`status`, `pf list`, `guest list`, `firmware info`, `nvram <var>` — still work,
but write the names above.

### Changing state

**No mutating command acts on its own.** Each one either asks first or refuses:

| Situation | What happens |
|---|---|
| `--yes` (or `-y`) passed | Acts immediately, no question |
| A person at a terminal | Prints what it would do, prompts `[y/N]` |
| **No terminal, no `--yes`** | Prints what it would do, **exits 3**, touches nothing |

You are the third row, so running a mutation bare is a safe dry run, and exit 3
means "refused for want of consent" — distinct from exit 1, which means it tried
and failed. Show the user that output, ask, then re-run with `--yes`. Never
chain the two in one step.

```bash
asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20        # dry run, exits 3
asuswrt portforward add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
```

Available mutations:

```bash
asuswrt portforward add --name NAME --port EXT --to-ip IP [--to-port INT] [--proto TCP|UDP|BOTH] --yes
asuswrt portforward remove --name NAME --yes     # or --port EXT
asuswrt portforward enable --yes                 # global port forwarding switch
asuswrt portforward disable --yes
asuswrt guest enable --band 2ghz --id 1 --yes
asuswrt guest disable --band 5ghz --id 1 --yes
asuswrt parental enable --yes
asuswrt parental disable --yes
asuswrt wifi wps disable --yes                   # or enable
asuswrt wifi set-security --band both|2ghz|5ghz --mode wpa2|wpa2wpa3|wpa3 [--mfp capable] --yes
asuswrt wifi set-country --band 5ghz --code AU --yes
asuswrt dns set --server1 8.8.8.8 [--server2 8.8.4.4] --yes
asuswrt dns auto --yes                           # back to the ISP's resolvers
asuswrt upnp disable --yes                       # or enable
asuswrt led on --yes                             # or off
asuswrt firmware upgrade --yes [--to VERSION]    # downloads, flashes, reboots
asuswrt reboot --yes
```

`portforward` is also spelled `pf`, and `set-security` / `set-country` also
answer to `security` / `country`.

## Rules for both surfaces

1. **Never reboot** unless the user asked for a reboot in those words. It drops
   every connection in the house for about a minute.
2. **Never upgrade firmware** unless the user asked to upgrade in those words.
   Show the release note first (`asuswrt firmware --notes`), then the preview,
   then ask. Having no terminal, you must also pass `--to` with the exact
   offered version — read it from `asuswrt firmware`, never guess it. Report the
   result as *requested*: the API says nothing about the
   download or the flash, and only reading `system` after the reboot shows
   whether it worked. Reporting a firmware version is worth doing only to answer
   one question — is there a newer version to install? Give the installed
   version, the offered version, and whether an upgrade is available; if they
   match, say it is up to date and stop there.
3. **Port forwarding exposes a device to the internet.** Say which device and
   port become reachable before adding a rule, and confirm the user means it
   when the target is 22, 3389, 445 or a database port. Check the global switch
   too — rules exist but do nothing while it is off. **UPnP is the same exposure without
   the decision** — any program on the LAN can open its own inbound port while
   it is on. Off is the right state; never enable it unless the user asked for
   UPnP in those words.
4. **nvram access is read-only on purpose.** Writes exist only as named
   commands. If a setting has no command, say it needs the web UI rather than
   improvising a raw write.
5. **Changing WiFi security or country restarts both radios**, dropping every
   wireless client. Say so before applying. Both read the value back and report
   `before -> after`; a country code write is often refused by stock firmware,
   and that read-back is the only thing that tells you.
6. **Changing WAN DNS changes name resolution for every device.** Say so before
   applying, and say how to undo it: `asuswrt dns auto` restores the ISP's
   servers and keeps working even when nothing resolves, because this tool
   reaches the router by address. A successful write is not proof the resolver
   changed — nvram taking the value and the service applying it are separate
   things; verify with a lookup, not with the exit code.

## Features to leave off

Both of these come up in every security review of an ASUS router. The answers
are settled — apply them, do not re-open the question with the user each time.

**Never accept the Trend Micro EULA.** AiProtection, Traffic Analyzer, Apps
Analyzer, Adaptive QoS, Game Boost and Web History are all gated behind it, and
accepting it hands browsing data to Trend Micro. Treat it as a hard no: if a
feature requires that EULA, the feature is unavailable. Do not recommend
enabling it, and do not frame the privacy trade-off as an open decision. On a
router where the EULA was never accepted, `bwdpi_db_enable=0` is the correct
state, not a misconfiguration to flag.

**Leave DoS protection off** (`fw_dos_x=0`). All it does is rate-limit new
connections and ICMP to roughly one per second. The professional consensus on
SNBForums is that this will not stop a real flood — the uplink saturates
regardless — while it does break legitimate traffic, with users reporting they
had to disable it for Cloudflare and for media servers. Off is the AsusWRT
default and the right setting for a home router. Someone genuinely under attack
needs their ISP, not this checkbox. Sources are in
[reference/settings.md](../../docs/settings.md#features-with-a-settled-answer).

## When something is not covered

The tools cover the common cases, not all of AsusWRT. For anything else, read
the value with `nvram get <var>` to confirm its name and encoding, then look it
up in [reference/settings.md](../../docs/settings.md) — variables, encodings, and
which are verified against real hardware. If it needs a write that does not
exist, say so rather than improvising. Worked examples for common requests are
in [reference/recipes.md](reference/recipes.md).

## Reporting back

Answer with the numbers, not the raw dump. "14 devices online, WAN is connected
at 203.0.113.4, CPU 3%" beats pasting a JSON blob. Show the client table when
the user asks who is on the network — it is already a table.
