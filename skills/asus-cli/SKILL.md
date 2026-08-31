---
name: asus-cli
description: Inspect and control an ASUS (AsusWRT) home router over its HTTP API - connected devices, WAN and internet status, CPU and RAM, firewall state, port forwarding, guest WiFi, parental control and WiFi security (WPS, WPA2/WPA3, country code). The request must name the router explicitly: use this skill only when it says "asus", or asks who is connected to my WiFi / what devices are on my home network. Do NOT load on the word "router" by itself - in a codebase that almost always means Express, React Router, vue-router, or API and message routing.
---

# ASUS router control

Drive the router through the `asus-cli` command. It talks to the router's HTTP API —
the same one the ASUS Router mobile app uses. No SSH, no web UI.

## Before anything else

Check the command exists:

```bash
command -v asus-cli || echo "not installed"
```

If missing, tell the user to run `uv tool install .` from the repository and
stop. Do not try to work around it by writing your own Python.

If a command reports that `ROUTER_PASS` is not set, it prints the exact paths
it searched. Relay them and stop — never ask the user for the password in chat.

## Reading state

| Task | Command |
|---|---|
| Model, firmware, uptime | `asus-cli info` |
| CPU, RAM, WAN, uptime | `asus-cli status` |
| Connected devices | `asus-cli clients --online` |
| All known devices | `asus-cli clients` |
| Internet connection detail | `asus-cli wan` |
| Firewall + filters + parental control | `asus-cli firewall` |
| Port forwarding rules | `asus-cli pf list` |
| Guest networks | `asus-cli guest list` |
| Wireless security (WPA mode, MFP, WPS, country) | `asus-cli wifi show` |
| Firmware version and available update | `asus-cli firmware info` |
| Any raw setting | `asus-cli nvram <var> [<var> ...]` |

Add `--json` to any read command when you need to parse the output rather
than show it. Prefer the plain output when reporting to the user — it is
already formatted for reading.

`asus-cli status` takes ~2 seconds: CPU usage is a delta between two samples, so
the command deliberately samples twice.

`asus-cli firmware info` takes ~7 seconds because it makes the router query ASUS
rather than trust its stored value. At a terminal it shows a spinner on
stderr; when the output is piped or captured it prints nothing extra, so what
you receive is unaffected. `--cached` skips the wait and the check.

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
asus-cli pf add --name Plex --port 32400 --to-ip 192.168.50.20   # dry run, exits 3
asus-cli pf add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
```

Available mutations:

```bash
asus-cli pf add --name NAME --port EXT --to-ip IP [--to-port INT] [--proto TCP|UDP|BOTH] --yes
asus-cli pf remove --name NAME --yes          # or --port EXT
asus-cli pf enable --yes                      # global port forwarding switch
asus-cli pf disable --yes
asus-cli guest enable --band 2ghz --id 1 --yes
asus-cli guest disable --band 5ghz --id 1 --yes
asus-cli parental enable --yes
asus-cli parental disable --yes
asus-cli wifi wps disable --yes               # or enable
asus-cli wifi security --band both|2ghz|5ghz --mode wpa2|wpa2wpa3|wpa3 [--mfp capable] --yes
asus-cli wifi country --band 5ghz --code AU --yes
asus-cli firmware upgrade --yes [--to VERSION]    # downloads, flashes, reboots
asus-cli reboot --yes
```

### Rules you must follow

1. **Run the dry run first, show the user its output, then ask before adding
   `--yes`.** Do not chain them in one step.
2. **Never run `asus-cli reboot`** unless the user asked for a reboot in those
   words. It drops every connection in the house for about a minute.
3. **Port forwarding exposes a device to the internet.** Before adding a rule,
   say which device and port become reachable. If the target port is 22, 3389,
   445 or a database port, say so plainly and confirm the user intends it.
4. **Check `asus-cli pf list` first.** The global switch can be OFF, in which case
   rules exist but do nothing — `asus-cli pf add` warns about this, but say it too.
5. **`asus-cli nvram` is read-only on purpose.** Writes exist only as named
   commands — `pf`, `guest`, `parental`, `wifi`. If a setting has no command,
   say it needs the web UI rather than improvising a raw write.
6. **Never run `asus-cli firmware upgrade` unless the user asked to upgrade the
   firmware in those words.** It writes flash and reboots; a power cut partway
   bricks the router. Show `asus-cli firmware info --notes` first so the user sees
   the version and the release note, then the dry run, then ask. Because you
   have no terminal, `--yes` also requires `--to` naming the exact offered
   version — read it from `asus-cli firmware info`, never guess it. When the
   command returns, say the upgrade was *requested*: the API reports nothing
   about the download or the flash, and only `asus-cli info` after the reboot
   shows whether it worked.
7. **`asus-cli wifi security` and `asus-cli wifi country` restart both radios.** Every
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

- Read the current value with `asus-cli nvram <var>` to confirm what the setting is
  called and how it is encoded.
- Look it up in [reference/settings.md](reference/settings.md), which lists the
  variables, their encodings and which are verified against real hardware.
- If it needs a write the CLI does not implement, say so rather than improvising.

Worked examples for common requests are in
[reference/recipes.md](reference/recipes.md).

## Reporting back

Answer with the numbers, not the raw dump. "14 devices online, WAN is connected
at 203.0.113.4, CPU 3%" beats pasting a JSON blob. Show the table from
`asus-cli clients` when the user asks who is on the network — it is already a table.
