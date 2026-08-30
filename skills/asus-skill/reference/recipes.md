# Recipes

Worked examples for the requests that actually come up. Each shows the dry run
first, because every mutation refuses to run without `--confirm`.

## "Who is on my network?"

```bash
asus clients --online
```

Report the table. If the user asks about a specific device, filter the full
list — `asus clients --json` gives `name`, `vendor`, `ip`, `type`, `guest`.

## "Is my internet down?"

```bash
asus status
```

`WAN CONNECTED` with an IP means the router has a working uplink; the problem
is downstream. `DISCONNECTED` means the router itself lost the WAN.
`asus wan` adds gateway, DNS and protocol.

## "Open port 32400 for my Plex server"

```bash
# 1. See what exists and whether forwarding is even on
asus pf list

# 2. Dry run — prints the rule, changes nothing, exits 3
asus pf add --name Plex --port 32400 --to-ip 192.168.50.20

# 3. Tell the user: 192.168.50.20:32400 becomes reachable from the internet.
#    Then, with their agreement:
asus pf add --name Plex --port 32400 --to-ip 192.168.50.20 --confirm
```

If `asus pf list` says port forwarding is OFF, the rule will exist but do
nothing until:

```bash
asus pf enable --confirm
```

### Different internal port

```bash
asus pf add --name Web --port 8080 --to-ip 192.168.50.30 --to-port 80 --confirm
```

### Restrict to one source address

```bash
asus pf add --name SSH --port 22022 --to-ip 192.168.50.10 --to-port 22 \
  --from-ip 203.0.113.7 --confirm
```

## "Close that port again"

```bash
asus pf remove --name Plex              # dry run
asus pf remove --name Plex --confirm
```

Removing by external port works too: `asus pf remove --port 32400 --confirm`.

## "Turn on the guest WiFi"

```bash
asus guest list
asus guest enable --band 2ghz --id 1 --confirm
```

Guest networks are numbered 1-3 per band. `asus guest list` shows the SSID of
each so you can pick the right one.

## "Is my firewall on?"

```bash
asus firewall
```

Shows the firewall switch, DoS protection, logging, WAN web access, both
content filters and parental control in one view. A value shown as `? (None)`
means that variable does not exist under this firmware — see
[settings.md](settings.md).

## "Block the kids' tablet"

Parental control rules are per device and are not settable from this CLI. What
is available:

```bash
asus firewall                    # shows how many rules exist and whether it is on
asus parental enable --confirm   # turns the whole feature on
```

Adding a rule for a specific device needs the web UI or the mobile app. Say so
rather than improvising an nvram write.

## Something not listed here

Read the current value first:

```bash
asus nvram <variable> --json
```

Then check [settings.md](settings.md) for the encoding. If the change requires
a write the CLI does not implement, tell the user which screen in the web UI
does it. Do not attempt raw writes.
