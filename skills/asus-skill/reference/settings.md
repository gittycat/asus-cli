# AsusWRT settings reference

ASUS publishes no documentation for nvram variables or for the HTTP API. Every
entry below carries how it was established, so you can tell a verified fact
from an educated guess.

**Provenance labels**

| Label | Meaning |
|---|---|
| `library` | Read from the `asusrouter` package source. Definitive for how this tool behaves. |
| `hardware` | Observed on a live RT-AX59U, firmware `3.0.0.4.388.34011_gfae8cb3`. |
| `unverified` | From general AsusWRT knowledge. Confirm with `asus nvram <var>` before relying on it. |

Anything marked `unverified` can be promoted in one command:

```bash
asus nvram fw_enable_x fw_dos_x        # empty result = wrong name for this firmware
```

---

## Data types available through the API

Fetched by name via the library's `AsusData` enum. Status is what an RT-AX59U
actually returned.

| Data type | Status | Contents |
|---|---|---|
| `cpu` | `hardware` OK | `total` plus one key per core (4 on RT-AX59U) |
| `ram` | `hardware` OK | `free`, `total`, `used`, `usage` — all in kB |
| `boottime` | `hardware` OK | `datetime`, `uptime` (seconds) |
| `wan` | `hardware` OK | `internet`, `0`, `1`, `aggregation`, `dualwan` |
| `network` | `hardware` OK | traffic counters per interface |
| `clients` | `hardware` OK | dict keyed by MAC |
| `wlan` | `hardware` OK | `2ghz`, `5ghz` |
| `gwlan` | `hardware` OK | `2ghz_1..3`, `5ghz_1..3` |
| `port_forwarding` | `hardware` OK | `state`, and `rules` **only when rules exist** |
| `parental_control` | `hardware` OK | `state`, `block_all`, `rules` |
| `led` | `hardware` OK | `state` |
| `ports` | `hardware` OK | `wan`, `lan`, `usb` |
| `firmware` | `hardware` OK | current/available versions |
| `aimesh` | `hardware` OK | dict keyed by node MAC |
| `system` | `hardware` empty | Not exposed on RT-AX59U stock firmware |
| `temperature` | `hardware` empty | Not exposed on RT-AX59U stock firmware |

### Shapes that are easy to get wrong

`library` + `hardware`, all three confirmed by reading the parsers and then
observing the failure on real data:

- **CPU usage is a delta.** `process_cpu` computes `usage` by differencing the
  current sample against the previous one. A single fetch always yields
  `usage: None`. Two samples are required.
- **WAN is nested.** There is no top-level `status` or `ip`. Use
  `wan["internet"]["link"]` and `wan["internet"]["ip_address"]`; per-port state
  is at `wan[0]` / `wan[1]`, selected by `wan["internet"]["unit"]`.
- **Client online state is not `client.state`.** `ConnectionState` is an
  `IntEnum` (`CONNECTED = 1`), and the reliable flag is
  `client.connection.online`.
- **`port_forwarding["rules"]` may not exist.** `process_port_forwarding` only
  sets the key when `vts_rulelist` is non-empty. Always use `.get("rules") or []`.

---

## nvram variables

### Port forwarding — `library`, `hardware`

| Variable | Meaning |
|---|---|
| `vts_enable_x` | Global switch. `0` = off, `1` = on |
| `vts_rulelist` | All rules, as one string |

Encoding, from `process_port_forwarding` (read) and `compile_port_forwarding`
(write). Records are separated by `<`, fields by `>`; over HTTP they arrive
escaped as `&#60` and `&#62`:

```
<name>ext_port>internal_ip>internal_port>protocol>source_ip>
```

Field order is identical in both directions. `protocol` is `TCP`, `UDP`,
`BOTH` or `OTHER`. Empty fields are written as empty strings, not omitted.

The list is a **single nvram string**, so there is no per-rule API: adding one
rule means reading all of them, appending, and writing the whole list back.
Applying calls the `restart_firewall` service.

### Wireless — `library`

| Variable | Meaning |
|---|---|
| `wl<i>_radio` | Radio on/off for band `i` (`0` = 2.4 GHz, `1` = 5 GHz) |
| `wl<i>.<n>_bss_enabled` | Guest network `n` (1-3) on band `i` |
| `wl<i>.<n>_expire` | Guest network expiry; set to `0` when enabling |

This is why the CLI's `--band 2ghz --id 1` becomes `wl0.1_bss_enabled`.
Applying calls `restart_wireless;restart_firewall`.

### Firewall and filtering — `unverified`

Not covered by any library data type; the CLI reads them straight from nvram.

| Variable | Expected meaning |
|---|---|
| `fw_enable_x` | Firewall on/off |
| `fw_dos_x` | DoS protection |
| `fw_log_x` | Firewall logging |
| `misc_http_x` | Web UI reachable from the WAN |
| `url_enable_x` | URL filter on/off |
| `url_rulelist` | URL filter entries, same `<`/`>` encoding |
| `keyword_enable_x` | Keyword filter on/off |
| `keyword_rulelist` | Keyword filter entries |

If `asus firewall` shows `? (None)` for one of these, the name is wrong for
this firmware. Find the real one by changing the setting in the web UI and
diffing `nvram show` over SSH — see the README section on extending coverage.
Promote the entry to `hardware` once you have confirmed it.

---

## Service calls

`library`. Applying a setting means writing the nvram keys and naming a service
to restart. The services this tool uses:

| Service | Restarts |
|---|---|
| `restart_firewall` | Port forwarding, filtering, parental control |
| `restart_wireless` | Radios and guest networks |
| `reboot` | The whole router |

An RT-AX59U reports 97 available services (`hardware`). The library's
`AsusSystem` enum lists the ones it knows how to call.

---

## Reading any variable

The HTTP API exposes a generic nvram read. This is the same mechanism the
library uses to collect device identity, so it is as reliable as the rest:

```bash
asus nvram vts_rulelist wl0.1_bss_enabled fw_enable_x --json
```

There is deliberately no write counterpart in this tool. Blind nvram writes
are the fastest way to brick a working configuration, and the safe write paths
are already exposed as named commands.
