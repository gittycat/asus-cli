"""Payload -> human-readable lines.

Every function here is pure: it takes a payload (the same shape the CLI's
read helpers already build, or return today) and returns `list[str]`. No
printing, no argparse, no router access, no exceptions raised for router
state — that all stays in the CLI.

This module is a temporary sibling of `cli.py` rather than `cli/render.py`.
The target layout (see docs/mcp-server-plan.md) puts it inside a `cli/`
package alongside `cli/main.py`, but `src/asuswrt/cli.py` cannot become both
a module and a package at once, and this phase (2b) is scoped to keep
`cli.py` a module. Phase 2c moves this file to `cli/render.py` alongside the
`cli.py` -> `cli/main.py` move.
"""

from __future__ import annotations

from typing import Any

from asuswrt.ops import BANDS, MFP_NAMES, _split_rulelist
from asuswrt.router import enum_name


def _onoff(value: Any) -> str:
    """Render an nvram boolean, keeping the raw value visible when it is not one."""
    return {"1": "ON", "0": "OFF"}.get(str(value), f"? ({value!r})")


def system(payload: dict[str, Any]) -> list[str]:
    """Identity: what the router is."""
    return [
        f"Model      {payload['model']}",
        f"Firmware   {payload['firmware']}  (merlin={payload['merlin']})",
        f"MAC        {payload['mac']}",
        f"Serial     {payload['serial']}",
        f"AiMesh     {payload['aimesh']}",
    ]


def health(payload: dict[str, Any]) -> list[str]:
    """Live load: everything that moves while the router is running."""
    hours = payload["uptime_hours"]
    cpu_total = payload["cpu_usage"]
    cores = payload["cpu_cores"]
    ram = payload["ram"]
    return [
        f"Uptime     {hours // 24} d {hours % 24} h",
        f"CPU        {cpu_total:.1f}% over {len(cores)} cores"
        if cpu_total is not None
        else "CPU        unavailable",
        f"RAM        {ram.get('usage', 0):.1f}%  "
        f"({(ram.get('used') or 0) / 1024:.0f} / {(ram.get('total') or 0) / 1024:.0f} MB)",
        f"WAN        {payload['wan_link']}  ip={payload['wan_ip']}",
    ]


def wan(payload: dict[str, Any]) -> list[str]:
    internet = payload.get("internet", {})
    unit = internet.get("unit")
    lines = [
        f"Link       {enum_name(internet.get('link'))}",
        f"IP         {internet.get('ip_address')}",
        f"Unit       {unit}",
    ]
    port = payload.get(unit) if unit is not None else None
    if isinstance(port, dict):
        lines += [
            f"State      {enum_name(port.get('state'))}",
            f"Protocol   {enum_name((port.get('main') or {}).get('protocol'))}",
            f"Gateway    {(port.get('main') or {}).get('gateway')}",
            f"DNS        {(port.get('main') or {}).get('dns')}",
        ]
    return lines


def dns(payload: dict[str, Any]) -> list[str]:
    """Which resolvers the router forwards to, and what LAN clients are told.

    The WAN unit is printed because it is part of the nvram names — a reader
    comparing this against `asuswrt nvram get ...` needs to know whether to
    ask for wan0_ or wan1_.
    """
    unit = payload["unit"]
    raw = payload["nvram"]
    automatic = str(raw.get(f"wan{unit}_dnsenable_x")) == "1"

    lan = (
        "the router itself"
        if str(raw.get("dhcpd_dns_router")) == "1"
        else " ".join(
            v for v in (raw.get("dhcp_dns1_x"), raw.get("dhcp_dns2_x")) if v
        )
        or "-"
    )

    return [
        f"WAN DNS           {'automatic (from the ISP)' if automatic else 'manual'}"
        f"   (wan{unit})",
        f"  Server 1        {raw.get(f'wan{unit}_dns1_x') or '-'}",
        f"  Server 2        {raw.get(f'wan{unit}_dns2_x') or '-'}",
        f"  In use          {raw.get(f'wan{unit}_dns') or '-'}",
        "",
        f"LAN clients use   {lan}",
        f"DNS-over-TLS      {_onoff(raw.get('dnspriv_enable'))}",
        f"DNSSEC            {_onoff(raw.get('dnssec_enable'))}",
        f"Rebind protection {_onoff(raw.get('dns_norebind'))}",
        f"Forward local     {_onoff(raw.get('dns_fwd_local'))}",
    ]


def led(payload: dict[str, Any]) -> list[str]:
    return [f"LEDs              {_onoff(payload.get('led_val'))}"]


def upnp(payload: dict[str, Any]) -> list[str]:
    """UPnP state, with every switch shown because any one of them turns it on."""
    raw = payload["nvram"]
    lines = [
        f"UPnP              {'ON' if payload['enabled'] else 'OFF'}",
        "",
        "  switches",
    ]
    lines += [
        f"    {name:<24} {_onoff(value)}"
        for name, value in raw.items()
        if name.endswith("upnp_enable")
    ]
    lines += [
        "",
        f"  Secure mode     {_onoff(raw.get('upnp_secure'))}"
        "   (only lets a device map a port to itself)",
        f"  Advertisement   {_onoff(raw.get('upnp_mnp'))}",
        # "0" is the auto setting, and it is a truthy string — say so rather
        # than printing a bare 0 that reads like a missing value.
        f"  Listen port     {port if (port := str(raw.get('upnp_port') or '0')) != '0' else 'auto'}",
    ]
    if payload["enabled"]:
        lines += [
            "",
            "Any program on the network can open an inbound port to itself while",
            "this is on, without asking. Turn it off with: asuswrt upnp disable",
        ]
    return lines


def client_lines(rows: list[dict[str, Any]]) -> list[str]:
    lines = [f"{'NAME':<24} {'IP':<16} {'TYPE':<14} {'MAC':<18} STATE"]
    lines += [
        f"{(r['name'] or '-'):<24} {(r['ip'] or '-'):<16} {r['type']:<14} "
        f"{r['mac']:<18} {'online' if r['online'] else 'offline'}"
        for r in rows
    ]
    lines.append(f"\n{sum(r['online'] for r in rows)} online / {len(rows)} listed")
    return lines


def port_forwarding(payload: dict[str, Any]) -> list[str]:
    rules = payload["rules"]
    lines = [f"Port forwarding is {payload['state']} ({len(rules)} rule(s))"]
    if rules:
        lines.append(f"\n{'NAME':<20} {'EXT':<8} {'->':<2} {'INTERNAL':<22} PROTO")
        lines += [
            f"{(r.name or '-'):<20} {r.port_external:<8} {'->':<2} "
            f"{r.ip_address + ':' + r.port:<22} {r.protocol}"
            for r in rules
        ]
    return lines


def firewall(payload: dict[str, Any]) -> list[str]:
    raw = payload["nvram"]
    pc = payload["parental_control"]

    def flag(name: str) -> str:
        return _onoff(raw.get(name))

    return [
        f"Firewall          {flag('fw_enable_x')}",
        f"DoS protection    {flag('fw_dos_x')}",
        f"Logging           {flag('fw_log_x')}",
        f"WAN web access    {flag('misc_http_x')}",
        f"Port forwarding   {flag('vts_enable_x')}",
        f"URL filter        {flag('url_enable_x')} "
        f"({len(_split_rulelist(raw.get('url_rulelist')))} entries)",
        f"Keyword filter    {flag('keyword_enable_x')} "
        f"({len(_split_rulelist(raw.get('keyword_rulelist')))} entries)",
        f"Parental control  {enum_name(pc.get('state'))} "
        f"({len(pc.get('rules') or [])} rules, block_all={enum_name(pc.get('block_all'))})",
    ]


def parental(payload: dict[str, Any]) -> list[str]:
    rules = payload.get("rules") or []
    lines = [
        f"Parental control  {enum_name(payload.get('state'))}",
        f"Block all         {enum_name(payload.get('block_all'))}",
        f"Rules             {len(rules)}",
    ]
    lines += [f"  {rule}" for rule in rules]
    return lines


def guest(payload: dict[str, Any]) -> list[str]:
    lines = [f"{'NETWORK':<12} {'STATE':<8} SSID"]
    for key, value in sorted(payload.items()):
        if not isinstance(value, dict):
            continue
        state = "ON" if value.get("bss_enabled") else "OFF"
        lines.append(f"{key:<12} {state:<8} {value.get('ssid', '-')}")
    return lines


def wifi(payload: dict[str, Any]) -> list[str]:
    lines = [
        f"WPS               {_onoff(payload.get('wps_enable_x'))}"
        f"  (wps_enable={payload.get('wps_enable')!r},"
        f" multiband={payload.get('wps_multiband')!r})",
        "",
        f"{'BAND':<8} {'RADIO':<7} {'AUTH':<10} {'CRYPTO':<8} {'MFP':<10} COUNTRY",
    ]
    for band, i in BANDS.items():
        mfp = str(payload.get(f"wl{i}_mfp"))
        lines.append(
            f"{band:<8} {_onoff(payload.get(f'wl{i}_radio')):<7} "
            f"{str(payload.get(f'wl{i}_auth_mode_x')):<10} "
            f"{str(payload.get(f'wl{i}_crypto')):<8} "
            f"{MFP_NAMES.get(mfp, mfp):<10} {payload.get(f'wl{i}_country_code')}"
        )
    return lines


def firmware(payload: dict[str, Any], *, notes: bool) -> list[str]:
    """The full `firmware show` report. `notes` is a CLI flag, not router state."""
    status = payload.get("status")
    latest = payload.get("latest")
    lines = [f"Current    {payload.get('current')}"]
    if status == "update":
        lines.append(f"Latest     {latest}   ** update available **")
    elif status == "current":
        lines.append(f"Latest     {latest}   (up to date)")
    else:
        lines.append(
            "Latest     could not verify — the router got no answer from ASUS"
        )
    if payload.get("state_beta"):
        lines.append(f"Beta       {payload.get('available_beta')}")

    note = payload.get("release_note")
    if note and notes:
        lines += ["", "Release note:", str(note)]
    elif note and status == "update":
        lines.append("\nRun `asuswrt firmware show --notes` for the release note.")
    if status == "update":
        lines.append(f"Upgrade with: asuswrt firmware upgrade --to {latest} --yes")
    return lines


def overview_clients(payload: dict[str, Any]) -> list[str]:
    """The `show` sweep's client line: a count, not the full table."""
    return [
        f"{payload['online']} online / {payload['known']} known"
        "   (full table: asuswrt clients)"
    ]


def overview_firmware(payload: dict[str, Any]) -> list[str]:
    """The `show` sweep's short firmware summary — not the full `firmware()` report."""
    status = payload.get("status")
    latest = payload.get("latest")
    lines = [f"Current    {payload.get('current')}"]
    if status == "update":
        lines.append(f"Latest     {latest}   ** update available **")
    elif status == "current":
        lines.append(f"Latest     {latest}   (up to date)")
    else:
        lines.append("Latest     could not verify")
    return lines


def overview(
    sections: list[tuple[str, str, Any, list[str]]], *, firmware_checked: bool
) -> list[str]:
    """The `show` sweep: each section's title, its lines, then a blank line.

    Its own renderer rather than a concatenation of the others: some
    sections (clients, firmware) already arrive here as short summaries
    rather than the full per-noun report, and only this function knows to
    add the closing hint when the firmware update was not checked.
    """
    out: list[str] = []
    for title, _, _, lines in sections:
        out += [title, *lines, ""]
    if not firmware_checked:
        out.append("Firmware update not checked. Run: asuswrt firmware show")
    return out


def apply_report(result: dict[str, Any], description: str) -> list[str]:
    """The before/after report for an nvram write.

    The verdict is the read-back, never `result["ok"]`. `ok` is the router's
    `modify` flag, and a router that had nothing to change reports no
    modification — so keying off it calls a correct, idempotent write a
    failure. What matters is whether the requested values are in place now,
    which is exactly what an empty `unchanged` says.
    """
    lines = [f"{'Applied' if not result['unchanged'] else 'FAILED'}: {description}"]
    for name, after in result["after"].items():
        before = result["before"].get(name)
        if name in result["unchanged"]:
            # The write was accepted and then ignored by the firmware.
            suffix = "  (REFUSED)"
        elif str(before) == str(after):
            # Already correct before the write. A success, not a refusal.
            suffix = "  (already set)"
        else:
            suffix = ""
        lines.append(f"  {name:<22} {before!r} -> {after!r}{suffix}")

    if result["unchanged"]:
        lines.append(
            "\nDid not take the requested value: "
            + ", ".join(result["unchanged"])
            + "\nThe firmware is refusing the write; use the web UI for these."
        )
    return lines
