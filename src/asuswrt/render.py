"""Payload -> human-readable lines.

Every function here is pure: it takes a payload (the same shape the CLI's
read helpers already build, or return today) and returns `list[str]`. No
printing, no argparse, no router access, no exceptions raised for router
state — that all stays in the CLI.

This module is a temporary sibling of `cli.py` rather than `cli/render.py`.
The target layout (see docs/mcp-server-plan.md) puts it inside a `cli/`
package alongside `cli/main.py`, but `src/asuswrt/cli.py` cannot become both
a module and a package at once, and this phase (2a) is scoped to keep
`cli.py` a module. Phase 2c moves this file to `cli/render.py` alongside the
`cli.py` -> `cli/main.py` move.

`BANDS` and `MFP_NAMES` are duplicated here from `cli.py`, which still needs
its own copies for building nvram writes and confirmation text. Phase 2b
moves the canonical copies into `ops.py`; this module will import them from
there instead once that exists.
"""

from __future__ import annotations

from typing import Any

from asuswrt.router import enum_name

# Band name -> nvram prefix index. Kept in sync with cli.BANDS by hand until
# Phase 2b, when both import a single copy from ops.py.
BANDS = {"2ghz": 0, "5ghz": 1}

# 802.11w management frame protection, value -> display name. Kept in sync
# with cli.MFP_NAMES until Phase 2b.
MFP_NAMES = {"0": "disabled", "1": "capable", "2": "required"}


def _onoff(value: Any) -> str:
    """Render an nvram boolean, keeping the raw value visible when it is not one."""
    return {"1": "ON", "0": "OFF"}.get(str(value), f"? ({value!r})")


def _split_rulelist(value: Any) -> list[str]:
    """Split an ASUS rule list. Entries are separated by the escaped '<'."""
    if not value or not isinstance(value, str):
        return []
    return [part for part in value.replace("&#60", "<").split("<") if part]


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

    async_run_service reports whether the router accepted the request, not
    whether the value stuck, so this is built from the read-back in `result`.
    """
    lines = [f"{'Applied' if result['ok'] else 'FAILED'}: {description}"]
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
