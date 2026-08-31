# AsusWRT settings reference

ASUS publishes no documentation for nvram variables or for the HTTP API. Every
entry below carries how it was established, so you can tell a verified fact
from an educated guess.

**Provenance labels**

| Label | Meaning |
|---|---|
| `library` | Read from the `asusrouter` package source. Definitive for how this tool behaves. |
| `hardware` | Observed on a live RT-AX59U, firmware `3.0.0.4.388.34011_gfae8cb3`. |
| `unverified` | From general AsusWRT knowledge. Confirm with `asus-cli nvram <var>` before relying on it. |

Anything marked `unverified` can be promoted in one command:

```bash
asus-cli nvram fw_enable_x fw_dos_x        # empty result = wrong name for this firmware
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

### Wireless security — `hardware` for the reads, mixed for the writes

Written by `asus-cli wifi wps|security|country`. All reads below were observed on
an RT-AX59U; the write values are marked separately because accepting a write
is not the same as the value sticking.

| Variable | Meaning | Provenance |
|---|---|---|
| `wps_enable` | WPS runtime flag | `hardware` |
| `wps_enable_x` | WPS as the web UI writes it | `hardware` |
| `wps_multiband` | WPS active on both bands | `hardware` |
| `wl<i>_auth_mode_x` | WPA mode for band `i` | `hardware` (`psk2` observed) |
| `wl<i>_crypto` | Cipher; `aes` for anything modern | `hardware` |
| `wl<i>_mfp` | 802.11w: `0` off, `1` capable, `2` required | `hardware` |
| `wl<i>_country_code` | Regulatory region | `hardware` |

`wps_enable` and `wps_enable_x` are both present and both `1` on a router with
WPS on, so `asus-cli wifi wps` writes both — otherwise the radio and the web UI
disagree about the state.

`auth_mode_x` values, of which only `psk2` is confirmed on this firmware:

| CLI `--mode` | `auth_mode_x` | Default `mfp` | Provenance |
|---|---|---|---|
| `wpa2` | `psk2` | `0` | `hardware` |
| `wpa2wpa3` | `psk2sae` | `1` (capable) | `unverified` |
| `wpa3` | `sae` | `2` (required) | `unverified` |

WPA3 requires management frame protection, which is why the mode carries the
`mfp` default with it. `--mfp` overrides it when a stubborn legacy client will
not associate.

**Country code is frequently locked.** Stock firmware derives the regulatory
region from the hardware SKU, and a write to `wl<i>_country_code` can be
accepted and then silently ignored. `reg_spec` and `location_code` show what
the firmware believes it is. This is why `apply_nvram` reads every variable
back and `_report_apply` fails the command when a value did not change — never
report a wireless write as applied on the strength of the service result
alone.

Applying any of these calls `restart_wireless`, which drops every wireless
client for a few seconds.

### Firmware — `hardware`

`AsusData.FIRMWARE` on an RT-AX59U returns `current`, `available`, `state`
(true when an update exists), the same three for `_beta`, a `webs` sub-dict of
status enums, and `release_note`. `available` is `None` whenever `state` is
false, so test `state` rather than truthiness of the version string.

Both actions go through `AsusSystem`:

| State | Service | Effect |
|---|---|---|
| `FIRMWARE_CHECK` | `firmware_check` | Router queries ASUS; result lands in `AsusData.FIRMWARE` |
| `FIRMWARE_UPGRADE` | `firmware_upgrade` | Downloads, writes flash, reboots |

Both are dispatched with `service=None` and `expect_modify=False`
(`system.py::STATE_MAP`), so `async_set_state` returns True as soon as the
request is sent. **It is not evidence that anything happened.** The check is
asynchronous with no completion signal, which is why `asus-cli firmware info`
sleeps before re-reading; the upgrade reports nothing at all, which is why
`asus-cli firmware upgrade` says "requested" and points at `asus-cli info`.

`asus-cli firmware info` runs the check every time rather than reporting the
stored value, because `webs_state_info` is refreshed only by the router's own
periodic check and `webs_update_enable` is `0` by default — the stored version
can be arbitrarily old.

Distinguishing "no update" from "could not check" matters and is easy to get
wrong. `webs["available"]` is populated only from an actual reply, so an empty
one means nothing was learned, while a populated one no newer than `current`
means genuinely up to date. `_update_status` returns `unknown` for the first
and `current` for the second; `firmware["state"]` alone cannot tell them
apart.

### Features with a settled answer

Two AsusWRT features look like obvious security wins and are not. Both
decisions are already made; treat them as policy rather than as questions to
put back to the user.

**Trend Micro — never accept the EULA.** `bwdpi_db_enable` gates the Trend
Micro DPI engine. Accepting the EULA is what turns it on, and it is a single
bundled consent covering AiProtection, Traffic Analyzer, Apps Analyzer,
Adaptive QoS, Game Boost and Web History — enabling any one of them starts
sending data to Trend Micro. The sub-flags `wrs_mals_enable`, `wrs_cc_enable`
and `wrs_vp_enable` can read `1` while `bwdpi_db_enable` is `0`; that
combination means the features are configured but not running, which is the
desired end state. Reported side effects when it is on include halved
throughput and false positives.

- [Trend Micro features — do you turn them on?](https://www.snbforums.com/threads/asus-router-features-powered-by-trend-micro-do-you-turn-them-on-and-agree-to-have-your-data-collected.82962/)
- [Privacy and TrendMicro](https://www.snbforums.com/threads/privacy-and-trendmicro.55956/)
- [What data is sent to Trend Micro for each feature](https://www.snbforums.com/threads/what-data-is-sent-to-trend-micro-for-each-of-these-features.63471/)

**DoS protection — leave `fw_dos_x=0`.** The setting adds firewall rules
limiting new connections and ICMP to about one per second. Against a real
flood the uplink saturates before the router matters, so it buys nothing;
meanwhile it breaks legitimate traffic, and users report having to switch it
off for Cloudflare and for media servers. `0` is the AsusWRT default and the
correct value for a home router.

- [DoS Protection from Asus Firewall — on or off?](https://www.snbforums.com/threads/dos-protection-from-asus-firewall-on-or-off.41149/)
- [Should I enable ASUS DoS Protection](https://www.snbforums.com/threads/should-i-enable-asus-dos-protection.45641/)
- [DoS protection breaks Cloudflare / Emby](https://www.snbforums.com/threads/firewall-enable-dos-protection-i-have-to-turn-it-off-for-cloudflare-emby-to-work.55058/)

### Firewall and filtering — `unverified`

Not covered by any library data type; the CLI reads them straight from nvram.

| Variable | Expected meaning |
|---|---|
| `fw_enable_x` | Firewall on/off |
| `fw_dos_x` | DoS protection — leave `0`, see above |
| `fw_log_x` | Firewall logging |
| `misc_http_x` | Web UI reachable from the WAN |
| `url_enable_x` | URL filter on/off |
| `url_rulelist` | URL filter entries, same `<`/`>` encoding |
| `keyword_enable_x` | Keyword filter on/off |
| `keyword_rulelist` | Keyword filter entries |

If `asus-cli firewall` shows `? (None)` for one of these, the name is wrong for
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
asus-cli --json nvram vts_rulelist wl0.1_bss_enabled fw_enable_x
```

`asus-cli nvram` has deliberately no write counterpart. Blind nvram writes are
the fastest way to brick a working configuration, so every write this tool can
perform is exposed as a named command with its own validation — `pf`, `guest`,
`parental` and `wifi`. `router.apply_nvram` is the shared implementation: it
writes the variables, restarts the named service, then reads the variables
back so a write the firmware quietly refused is reported as a failure.
