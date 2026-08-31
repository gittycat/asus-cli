# Recipes

Worked examples for the requests that actually come up. Each shows the dry run
first, because every mutation refuses to run without `--yes`.

## "Who is on my network?"

```bash
asus-cli clients --online
```

Report the table. If the user asks about a specific device, filter the full
list — `asus-cli clients --json` gives `name`, `vendor`, `ip`, `type`, `guest`.

## "Is my internet down?"

```bash
asus-cli status
```

`WAN CONNECTED` with an IP means the router has a working uplink; the problem
is downstream. `DISCONNECTED` means the router itself lost the WAN.
`asus-cli wan` adds gateway, DNS and protocol.

## "Open port 32400 for my Plex server"

```bash
# 1. See what exists and whether forwarding is even on
asus-cli pf list

# 2. Dry run — prints the rule, changes nothing, exits 3
asus-cli pf add --name Plex --port 32400 --to-ip 192.168.50.20

# 3. Tell the user: 192.168.50.20:32400 becomes reachable from the internet.
#    Then, with their agreement:
asus-cli pf add --name Plex --port 32400 --to-ip 192.168.50.20 --yes
```

If `asus-cli pf list` says port forwarding is OFF, the rule will exist but do
nothing until:

```bash
asus-cli pf enable --yes
```

### Different internal port

```bash
asus-cli pf add --name Web --port 8080 --to-ip 192.168.50.30 --to-port 80 --yes
```

### Restrict to one source address

```bash
asus-cli pf add --name SSH --port 22022 --to-ip 192.168.50.10 --to-port 22 \
  --from-ip 203.0.113.7 --yes
```

## "Close that port again"

```bash
asus-cli pf remove --name Plex              # dry run
asus-cli pf remove --name Plex --yes
```

Removing by external port works too: `asus-cli pf remove --port 32400 --yes`.

## "Turn on the guest WiFi"

```bash
asus-cli guest list
asus-cli guest enable --band 2ghz --id 1 --yes
```

Guest networks are numbered 1-3 per band. `asus-cli guest list` shows the SSID of
each so you can pick the right one.

## "Is my firewall on?"

```bash
asus-cli firewall
```

Shows the firewall switch, DoS protection, logging, WAN web access, both
content filters and parental control in one view. A value shown as `? (None)`
means that variable does not exist under this firmware — see
[settings.md](settings.md).

## "Block the kids' tablet"

Parental control rules are per device and are not settable from this CLI. What
is available:

```bash
asus-cli firewall                    # shows how many rules exist and whether it is on
asus-cli parental enable --yes   # turns the whole feature on
```

Adding a rule for a specific device needs the web UI or the mobile app. Say so
rather than improvising an nvram write.

## "Is my WiFi set up securely?"

```bash
asus-cli wifi show
```

Shows WPS, and per band the radio state, WPA mode, cipher, 802.11w level and
country code. What to look for:

- **WPS ON** — turn it off. The PIN exchange is brute-forceable and nothing on
  a modern network needs it.
- **AUTH `psk2` with MFP `disabled`** — WPA2 only, no management frame
  protection, so deauthentication attacks work freely.
- **COUNTRY mismatched between bands** — a band left on `AA` (worldwide) runs
  the most restrictive channel and power set, which costs throughput.

```bash
asus-cli wifi wps disable                    # dry run
asus-cli wifi wps disable --yes
```

## "Move my WiFi to WPA3"

```bash
asus-cli wifi security --band both --mode wpa2wpa3          # dry run
asus-cli wifi security --band both --mode wpa2wpa3 --yes
```

Prefer `wpa2wpa3` over `wpa3` on a household network: mixed mode turns on
management frame protection while WPA2-only devices — printers, smart plugs,
older IoT — keep working. Warn the user first that both radios restart and
every wireless client reconnects.

If a legacy device will not associate afterwards, relax the frame protection
rather than dropping back to WPA2:

```bash
asus-cli wifi security --band 2ghz --mode wpa2wpa3 --mfp disabled --yes
```

## "Fix the 5 GHz country code"

```bash
asus-cli nvram wl0_country_code wl1_country_code reg_spec location_code
asus-cli wifi country --band 5ghz --code AU --yes
```

Check `reg_spec` and `location_code` first — they say which region the
firmware thinks it is in, and picking the wrong code is a regulatory problem,
not just a performance one. The command reads the value back and fails if it
did not stick, which is common: stock firmware often locks the country code to
the hardware SKU. If it fails, say so and point at the web UI.

## "Is my firmware up to date?"

```bash
asus-cli firmware info             # asks the router to query ASUS, then reports
asus-cli firmware info --notes     # same, plus the release note
asus-cli firmware info --cached    # skip the check, report the stored value
```

`info` runs the online check every time, which takes about seven seconds and
shows a spinner while it waits (only when a person is watching — piped output
is unchanged). The
version stored on the router is refreshed only by its own periodic check, and
that is off by default (`webs_update_enable=0`), so the stored value can be
arbitrarily old. If ASUS cannot be reached the output says **could not
verify** rather than reporting "up to date" — not knowing and knowing there is
nothing to install are different answers.

## "Upgrade the firmware"

Only when the user asked for this in those words.

```bash
# 1. Show them what is on offer, release note included
asus-cli firmware info --notes

# 2. Dry run — names the version itself, no --to needed
asus-cli firmware upgrade

# 3. Only after they agree. --to is required because you have no terminal.
asus-cli firmware upgrade --yes --to 3.0.0.4.388.34098_g9b0c9ae
```

At a terminal a person just answers the prompt; the version is printed for
them to read. Running unattended there is nobody to read it, so `--yes`
demands `--to` and refuses a mismatch. That is what stops an unattended
upgrade flashing whatever happens to be on the server.

The upgrade also refuses to run at all when the latest version could not be
verified. Never work around that by passing `--cached` output into `--to`.

Tell the user before step 3: the house loses connectivity for five to ten
minutes, and losing power mid-flash can brick the router.

Afterwards, do not report success. The API acknowledges the request and then
goes quiet. Wait for the reboot and check:

```bash
asus-cli info
```

## Something not listed here

Read the current value first:

```bash
asus-cli --json nvram <variable>
```

Then check [settings.md](settings.md) for the encoding. If the change requires
a write the CLI does not implement, tell the user which screen in the web UI
does it. Do not attempt raw writes.
