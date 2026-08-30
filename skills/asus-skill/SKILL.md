---
name: asus-skill
description: Inspect and control an ASUS (AsusWRT) home router over its HTTP API - connected devices, WAN and internet status, CPU and RAM, firewall state, port forwarding, guest WiFi and parental control. The request must name the router explicitly: use this skill only when it says "asus", or asks who is connected to my WiFi / what devices are on my home network. Do NOT load on the word "router" by itself - in a codebase that almost always means Express, React Router, vue-router, or API and message routing.
---

# ASUS router control

Drive the router through the `asus` command. It talks to the router's HTTP API —
the same one the ASUS Router mobile app uses. No SSH, no web UI.

## Before anything else

Check the command exists:

```bash
command -v asus || echo "not installed"
```

If missing, tell the user to run `uv tool install .` from the repository and
stop. Do not try to work around it by writing your own Python.

If a command reports that `ROUTER_PASS` is not set, it prints the exact paths
it searched. Relay them and stop — never ask the user for the password in chat.

## Reading state

| Task | Command |
|---|---|
| Model, firmware, uptime | `asus info` |
| CPU, RAM, WAN, uptime | `asus status` |
| Connected devices | `asus clients --online` |
| All known devices | `asus clients` |
| Internet connection detail | `asus wan` |
| Firewall + filters + parental control | `asus firewall` |
| Port forwarding rules | `asus pf list` |
| Guest networks | `asus guest list` |
| Any raw setting | `asus nvram <var> [<var> ...]` |

Add `--json` to any read command when you need to parse the output rather
than show it. Prefer the plain output when reporting to the user — it is
already formatted for reading.

`asus status` takes ~2 seconds: CPU usage is a delta between two samples, so
the command deliberately samples twice.

## Changing state

**Every mutating command requires `--confirm`.** Without it the command prints
what it would do and exits 3, touching nothing. Use that as a dry run.

```bash
asus pf add --name Plex --port 32400 --to-ip 192.168.50.20   # dry run, exits 3
asus pf add --name Plex --port 32400 --to-ip 192.168.50.20 --confirm
```

Available mutations:

```bash
asus pf add --name NAME --port EXT --to-ip IP [--to-port INT] [--proto TCP|UDP|BOTH] --confirm
asus pf remove --name NAME --confirm          # or --port EXT
asus pf enable --confirm                      # global port forwarding switch
asus pf disable --confirm
asus guest enable --band 2ghz --id 1 --confirm
asus guest disable --band 5ghz --id 1 --confirm
asus parental enable --confirm
asus parental disable --confirm
asus reboot --confirm
```

### Rules you must follow

1. **Run the dry run first, show the user its output, then ask before adding
   `--confirm`.** Do not chain them in one step.
2. **Never run `asus reboot`** unless the user asked for a reboot in those
   words. It drops every connection in the house for about a minute.
3. **Port forwarding exposes a device to the internet.** Before adding a rule,
   say which device and port become reachable. If the target port is 22, 3389,
   445 or a database port, say so plainly and confirm the user intends it.
4. **Check `asus pf list` first.** The global switch can be OFF, in which case
   rules exist but do nothing — `asus pf add` warns about this, but say it too.
5. **`asus nvram` is read-only on purpose.** There is no write equivalent. If a
   setting can only be changed by writing nvram, say it needs the web UI.

## When something is not covered

The CLI covers the common cases, not all of AsusWRT. For anything else:

- Read the current value with `asus nvram <var>` to confirm what the setting is
  called and how it is encoded.
- Look it up in [reference/settings.md](reference/settings.md), which lists the
  variables, their encodings and which are verified against real hardware.
- If it needs a write the CLI does not implement, say so rather than improvising.

Worked examples for common requests are in
[reference/recipes.md](reference/recipes.md).

## Reporting back

Answer with the numbers, not the raw dump. "14 devices online, WAN is connected
at 203.0.113.4, CPU 3%" beats pasting a JSON blob. Show the table from
`asus clients` when the user asks who is on the network — it is already a table.
