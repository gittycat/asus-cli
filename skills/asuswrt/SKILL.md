---
name: asuswrt
description: Inspect and control an ASUS (AsusWRT) home router over its HTTP API - connected devices, WAN and internet status, CPU and RAM, firewall state, port forwarding, guest WiFi, parental control and WiFi security (WPS, WPA2/WPA3, country code). The request must name the router explicitly: use this skill only when it says "asus", or asks who is connected to my WiFi / what devices are on my home network. Do NOT load on the word "router" by itself - in a codebase that almost always means Express, React Router, vue-router, or API and message routing.
---

# ASUS router control

Drive the router through the `asuswrt` command. It talks to the router's HTTP API —
the same one the ASUS Router mobile app uses. No SSH, no web UI.

## First: check for MCP tools

If `mcp__asuswrt__*` tools are present in this session, they are the same
operations as the CLI, already typed and validated. **Prefer them.**

- **Reads** — use the MCP tool. `get_overview` first for broad status, then a
  specific tool only if you need the detailed rows.
- **Writes** — if the matching MCP write tool exists, use it: call it once with
  `confirm=false` to get a preview, show the user what it says, then call again
  with `confirm=true`. Never both in one step.
- **If the write tool is absent, MCP writes are disabled by the server's
  gate.** Say so and stop. **Do not run the CLI mutation instead** — that
  defeats a deliberate setting, and the user turned it off on purpose.

Use the CLI mutation path only when the user asks for the CLI specifically, and
keep its dry-run-then-`--yes` sequence when you do. Everything below describes
the CLI; the safety rules apply identically to the MCP tools.

## Before anything else

Check the command exists:

```bash
command -v asuswrt || echo "not installed"
```

If missing, tell the user to run `uv tool install .` from the repository and
stop. Do not try to work around it by writing your own Python.

If a command reports that `ROUTER_PASS` is not set, it prints the exact paths
it searched. Relay them and stop — never ask the user for the password in chat.

## Reading state

The command tree is **noun then verb**, and it is regular: `show` is the only
read verb, and a bare noun means `show`. You never have to guess which command
holds a reading — pick the noun.

```
asuswrt show          # every reading below, in one connection
asuswrt <noun>        # same as `asuswrt <noun> show`
```

| Noun | What it reads |
|---|---|
| `system` | model, firmware, MAC, serial, AiMesh — nothing that moves |
| `system health` | uptime, CPU, RAM, WAN summary — everything that moves |
| `wan` | internet connection detail |
| `clients` | known devices; `--online` for only the connected ones |
| `firewall` | firewall, DoS, filters, parental control summary |
| `parental` | parental control state and rules |
| `portforward` | the global switch and the rules |
| `guest` | guest wireless networks |
| `wifi` | radio, WPA mode, MFP, country code, WPS |
| `firmware` | installed version and what ASUS is offering right now |
| `nvram get <var> ...` | any raw setting the nouns do not cover |

**Start with `asuswrt show`** for anything resembling "how is the router" or
"is everything OK". Each noun is a separate process and therefore a separate
login to the router, so eight nouns cost eight handshakes; `show` costs one.
It leaves out the firmware check (see below) and prints a client count rather
than the table — run `asuswrt clients` when you need the devices themselves.

Add `--json` to any read when you need to parse it. `asuswrt --json show`
returns one object keyed by noun. Prefer the plain output when reporting to
the user — it is already formatted for reading.

Two readings are slow, and both say why:

- `asuswrt system health` and `asuswrt show` take ~2 s. CPU usage is a delta
  between two samples, so the command deliberately samples twice.
- `asuswrt firmware` takes ~7 s. It makes the router query ASUS every time and
  ignores the copy in nvram, which is only refreshed by a periodic check that
  is off by default and is therefore routinely months stale. There is no
  cached mode: a version you might flash from has to be the current one.
  `asuswrt show --firmware` folds this check into the sweep.

At a terminal the slow calls show a spinner on stderr; piped or captured they
print nothing extra, so what you receive is unaffected.

Older names still work and still do the same thing — `info`, `status`,
`pf list`, `guest list`, `firmware info`, `nvram <var>` — but use the names
above when you write a command.

## Changing state

**No mutating command acts on its own.** Each one either asks first or
refuses:

| Situation | What happens |
|---|---|
| `--yes` (or `-y`) passed | Acts immediately, no question |
| A person at a terminal | Prints what it would do, prompts `[y/N]` |
| **No terminal, no `--yes`** | Prints what it would do, **exits 3**, touches nothing |

You are the third row. A bare mutating command is therefore a safe dry run,
and exit 3 means "refused for want of consent" — distinct from exit 1, which
means it tried and failed.

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
asuswrt firmware upgrade --yes [--to VERSION]    # downloads, flashes, reboots
asuswrt reboot --yes
```

`portforward` is also spelled `pf`, and `set-security` / `set-country` also
answer to `security` / `country`.

### Rules you must follow

1. **Run the dry run first, show the user its output, then ask before adding
   `--yes`.** Do not chain them in one step.
2. **Never run `asuswrt reboot`** unless the user asked for a reboot in those
   words. It drops every connection in the house for about a minute.
3. **Port forwarding exposes a device to the internet.** Before adding a rule,
   say which device and port become reachable. If the target port is 22, 3389,
   445 or a database port, say so plainly and confirm the user intends it.
4. **Check `asuswrt portforward` first.** The global switch can be OFF, in which
   case rules exist but do nothing — `asuswrt portforward add` warns about this,
   but say it too.
5. **`asuswrt nvram get` is read-only on purpose.** Writes exist only as named
   commands — `portforward`, `guest`, `parental`, `wifi`. If a setting has no
   command, say it needs the web UI rather than improvising a raw write.
6. **Never run `asuswrt firmware upgrade` unless the user asked to upgrade the
   firmware in those words.** It writes flash and reboots; a power cut partway
   bricks the router. Show `asuswrt firmware --notes` first so the user sees
   the version and the release note, then the dry run, then ask. Because you
   have no terminal, `--yes` also requires `--to` naming the exact offered
   version — read it from `asuswrt firmware`, never guess it. When the
   command returns, say the upgrade was *requested*: the API reports nothing
   about the download or the flash, and only `asuswrt system` after the reboot
   shows whether it worked.

   Reporting the firmware version is only worth doing to answer one question:
   is there a newer version to install? Say the installed version, the offered
   version, and whether an upgrade is available. If the two match, say it is up
   to date and stop there.
7. **`asuswrt wifi set-security` and `asuswrt wifi set-country` restart both radios.** Every
   wireless client drops and reconnects. Say so before applying. These write
   nvram directly, so the command reads each value back afterwards and prints
   `before -> after`; a country code write in particular is often refused by
   stock firmware, and the read-back is what tells you whether it took.

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
default and the right setting for a home router. Someone genuinely under
attack needs their ISP, not this checkbox. Sources are in
[reference/settings.md](reference/settings.md#features-with-a-settled-answer).

## When something is not covered

The CLI covers the common cases, not all of AsusWRT. For anything else:

- Read the current value with `asuswrt nvram get <var>` to confirm what the
  setting is called and how it is encoded.
- Look it up in [reference/settings.md](reference/settings.md), which lists the
  variables, their encodings and which are verified against real hardware.
- If it needs a write the CLI does not implement, say so rather than improvising.

Worked examples for common requests are in
[reference/recipes.md](reference/recipes.md).

## Reporting back

Answer with the numbers, not the raw dump. "14 devices online, WAN is connected
at 203.0.113.4, CPU 3%" beats pasting a JSON blob. Show the table from
`asuswrt clients` when the user asks who is on the network — it is already a table.
