"""asus-cli — command line control for an ASUS router over its HTTP API.

Read commands print a human-readable summary, or JSON with --json.
Every command that changes the router asks first. --yes skips the asking;
with no terminal to ask at, the command prints what it would do and exits 3.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import itertools
import json
import sys
from typing import Any

from asusrouter import AsusData, AsusRouterError
from asusrouter.modules.parental_control import AsusParentalControl
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule
from asusrouter.modules.system import AsusSystem
from asusrouter.modules.wlan import AsusWLAN

from asus_cli.router import (
    ConfigError,
    apply_nvram,
    connect,
    enum_name,
    jsonable,
    port_forwarding_rules,
    read_nvram,
)

# Seconds between the two CPU samples needed to compute a usage delta.
CPU_SAMPLE_SECONDS = 2.0

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_CONFIG = 2
EXIT_NEEDS_CONFIRM = 3

# Firewall settings that have no dedicated data type in the library and are
# therefore read straight from nvram. Names verified against a live RT-AX59U.
FIREWALL_VARS = [
    "fw_enable_x",
    "fw_dos_x",
    "fw_log_x",
    "misc_http_x",
    "vts_enable_x",
    "url_enable_x",
    "url_rulelist",
    "keyword_enable_x",
    "keyword_rulelist",
]


def emit(payload: Any, lines: list[str], as_json: bool) -> None:
    """Print either machine-readable JSON or the human summary."""
    if as_json:
        print(json.dumps(jsonable(payload), indent=2, default=str))
    else:
        print("\n".join(lines))


def _onoff(value: Any) -> str:
    """Render an nvram boolean, keeping the raw value visible when it is not one."""
    return {"1": "ON", "0": "OFF"}.get(str(value), f"? ({value!r})")


SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


@contextlib.asynccontextmanager
async def progress(message: str) -> Any:
    """Spin on stderr while something slow runs.

    Silent unless stderr is a terminal: piped and captured output stays byte
    for byte what it would have been, and --json on stdout is unaffected
    either way.
    """
    if not sys.stderr.isatty():
        yield
        return

    async def spin() -> None:
        for i in itertools.count():
            frame = SPINNER_FRAMES[i % len(SPINNER_FRAMES)]
            print(f"\r{frame} {message}", end="", file=sys.stderr, flush=True)
            await asyncio.sleep(0.1)

    task = asyncio.create_task(spin())
    try:
        yield
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
        print("\r" + " " * (len(message) + 4) + "\r", end="", file=sys.stderr, flush=True)


def needs_confirm(args: argparse.Namespace, description: str) -> bool:
    """Decide whether a mutation may proceed. Returns True if it was refused.

    --yes acts immediately. Otherwise, at a terminal, ask the person sitting
    there. With no terminal there is nobody to ask, so the command prints what
    it would do and exits EXIT_NEEDS_CONFIRM — silence is never consent, which
    is what makes the bare command safe to run as a dry run.
    """
    if args.yes:
        return False

    print(f"Would {description}", file=sys.stderr)

    if not sys.stdin.isatty():
        print("Re-run with --yes to apply.", file=sys.stderr)
        return True

    print("Proceed? [y/N] ", end="", file=sys.stderr, flush=True)
    try:
        answer = input().strip().lower()
    except EOFError:
        answer = ""
    if answer in ("y", "yes"):
        return False

    print("Cancelled.", file=sys.stderr)
    return True


# --------------------------------------------------------------------------
# Read commands
# --------------------------------------------------------------------------


async def cmd_info(args: argparse.Namespace) -> int:
    async with connect() as router:
        identity = await router.async_get_identity()
        boottime = await router.async_get_data(AsusData.BOOTTIME) or {}
        hours = int(boottime.get("uptime", 0)) // 3600

        payload = {
            "model": identity.model,
            "product_id": identity.product_id,
            "firmware": str(identity.firmware),
            "merlin": identity.merlin,
            "mac": identity.mac,
            "serial": identity.serial,
            "aimesh": identity.aimesh,
            "services": len(identity.services or []),
            "uptime_hours": hours,
        }
        emit(
            payload,
            [
                f"Model      {identity.model}",
                f"Firmware   {identity.firmware}  (merlin={identity.merlin})",
                f"MAC        {identity.mac}",
                f"Uptime     {hours // 24} d {hours % 24} h",
                f"AiMesh     {identity.aimesh}",
            ],
            args.json,
        )
    return EXIT_OK


async def cmd_status(args: argparse.Namespace) -> int:
    async with connect() as router:
        # CPU usage is a delta between two samples, so one fetch always
        # yields usage=None (hook.py::process_cpu). Take a second sample.
        await router.async_get_data(AsusData.CPU)
        await asyncio.sleep(args.cpu_sample)
        cpu = await router.async_get_data(AsusData.CPU, force=True) or {}
        ram = await router.async_get_data(AsusData.RAM) or {}
        wan = await router.async_get_data(AsusData.WAN) or {}
        boottime = await router.async_get_data(AsusData.BOOTTIME) or {}

        internet = wan.get("internet", {}) if isinstance(wan, dict) else {}
        hours = int(boottime.get("uptime", 0)) // 3600
        cpu_total = (cpu.get("total") or {}).get("usage")
        cores = {k: (v or {}).get("usage") for k, v in cpu.items() if k != "total"}

        payload = {
            "uptime_hours": hours,
            "cpu_usage": cpu_total,
            "cpu_cores": cores,
            "ram": ram,
            "wan_link": enum_name(internet.get("link")),
            "wan_ip": internet.get("ip_address"),
        }
        lines = [
            f"Uptime     {hours // 24} d {hours % 24} h",
            f"CPU        {cpu_total:.1f}% over {len(cores)} cores"
            if cpu_total is not None
            else "CPU        unavailable",
            f"RAM        {ram.get('usage', 0):.1f}%  "
            f"({(ram.get('used') or 0) / 1024:.0f} / {(ram.get('total') or 0) / 1024:.0f} MB)",
            f"WAN        {enum_name(internet.get('link'))}  ip={internet.get('ip_address')}",
        ]
        emit(payload, lines, args.json)
    return EXIT_OK


async def cmd_clients(args: argparse.Namespace) -> int:
    async with connect() as router:
        clients = await router.async_get_data(AsusData.CLIENTS) or {}

        rows = []
        for mac, client in clients.items():
            conn = getattr(client, "connection", None)
            desc = getattr(client, "description", None)
            online = bool(getattr(conn, "online", False))
            if args.online and not online:
                continue
            rows.append(
                {
                    "mac": mac,
                    "name": getattr(desc, "name", None),
                    "vendor": getattr(desc, "vendor", None),
                    "ip": getattr(conn, "ip_address", None),
                    "type": enum_name(getattr(conn, "type", None)),
                    "guest": getattr(conn, "guest", None),
                    "online": online,
                }
            )
        rows.sort(key=lambda r: (not r["online"], r["name"] or r["mac"]))

        lines = [f"{'NAME':<24} {'IP':<16} {'TYPE':<14} {'MAC':<18} STATE"]
        lines += [
            f"{(r['name'] or '-'):<24} {(r['ip'] or '-'):<16} {r['type']:<14} "
            f"{r['mac']:<18} {'online' if r['online'] else 'offline'}"
            for r in rows
        ]
        lines.append(f"\n{sum(r['online'] for r in rows)} online / {len(rows)} listed")
        emit(rows, lines, args.json)
    return EXIT_OK


async def cmd_wan(args: argparse.Namespace) -> int:
    async with connect() as router:
        wan = await router.async_get_data(AsusData.WAN) or {}
        internet = wan.get("internet", {})
        unit = internet.get("unit")
        lines = [
            f"Link       {enum_name(internet.get('link'))}",
            f"IP         {internet.get('ip_address')}",
            f"Unit       {unit}",
        ]
        port = wan.get(unit) if unit is not None else None
        if isinstance(port, dict):
            lines += [
                f"State      {enum_name(port.get('state'))}",
                f"Protocol   {enum_name((port.get('main') or {}).get('protocol'))}",
                f"Gateway    {(port.get('main') or {}).get('gateway')}",
                f"DNS        {(port.get('main') or {}).get('dns')}",
            ]
        emit(wan, lines, args.json)
    return EXIT_OK


# --------------------------------------------------------------------------
# Port forwarding
# --------------------------------------------------------------------------


async def cmd_pf_list(args: argparse.Namespace) -> int:
    async with connect() as router:
        data = await router.async_get_data(AsusData.PORT_FORWARDING) or {}
        rules = await port_forwarding_rules(router)
        state = enum_name(data.get("state"))

        lines = [f"Port forwarding is {state} ({len(rules)} rule(s))"]
        if rules:
            lines.append(f"\n{'NAME':<20} {'EXT':<8} {'->':<2} {'INTERNAL':<22} PROTO")
            lines += [
                f"{(r.name or '-'):<20} {r.port_external:<8} {'->':<2} "
                f"{r.ip_address + ':' + r.port:<22} {r.protocol}"
                for r in rules
            ]
        emit({"state": state, "rules": rules}, lines, args.json)
    return EXIT_OK


async def cmd_pf_add(args: argparse.Namespace) -> int:
    rule = PortForwardingRule(
        name=args.name,
        ip_address=args.to_ip,
        port=str(args.to_port or args.port),
        protocol=args.proto,
        ip_external=args.from_ip or "",
        port_external=str(args.port),
    )
    description = (
        f"add rule {rule.name!r}: :{rule.port_external} -> "
        f"{rule.ip_address}:{rule.port} {rule.protocol}"
    )
    if needs_confirm(args, description):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        current = await port_forwarding_rules(router)
        clash = [
            r
            for r in current
            if r.port_external == rule.port_external and r.protocol == rule.protocol
        ]
        if clash and not args.force:
            print(
                f"External port {rule.port_external}/{rule.protocol} is already "
                f"forwarded to {clash[0].ip_address}:{clash[0].port}. "
                "Use --force to add anyway.",
                file=sys.stderr,
            )
            return EXIT_ERROR

        # Build the full list ourselves and apply it in one write. The whole
        # rule list is a single nvram string, so this is read-modify-write.
        ok = await router.async_apply_port_forwarding_rules([*current, rule])
        print(f"{'Applied' if ok else 'FAILED'}: {description}")

        data = await router.async_get_data(AsusData.PORT_FORWARDING, force=True) or {}
        if data.get("state") == AsusPortForwarding.OFF:
            print("Note: port forwarding is globally OFF. Run: asus-cli pf enable --yes")
        return EXIT_OK if ok else EXIT_ERROR


async def cmd_pf_remove(args: argparse.Namespace) -> int:
    async with connect() as router:
        current = await port_forwarding_rules(router)

        def matches(rule: PortForwardingRule) -> bool:
            if args.name and rule.name != args.name:
                return False
            if args.port and rule.port_external != str(args.port):
                return False
            if args.proto and rule.protocol != args.proto:
                return False
            return bool(args.name or args.port)

        doomed = [r for r in current if matches(r)]
        if not doomed:
            print("No matching rule.", file=sys.stderr)
            return EXIT_ERROR

        description = "remove " + ", ".join(
            f"{r.name!r} (:{r.port_external} -> {r.ip_address}:{r.port})" for r in doomed
        )
        if needs_confirm(args, description):
            return EXIT_NEEDS_CONFIRM

        keep = [r for r in current if r not in doomed]
        ok = await router.async_apply_port_forwarding_rules(keep)
        print(f"{'Applied' if ok else 'FAILED'}: {description}")
        return EXIT_OK if ok else EXIT_ERROR


async def cmd_pf_toggle(args: argparse.Namespace) -> int:
    target = AsusPortForwarding.ON if args.action == "enable" else AsusPortForwarding.OFF
    if needs_confirm(args, f"turn port forwarding {target.name} globally"):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        ok = await router.async_set_state(target)
        print(f"{'Applied' if ok else 'FAILED'}: port forwarding {target.name}")
        return EXIT_OK if ok else EXIT_ERROR


# --------------------------------------------------------------------------
# Firewall / filtering
# --------------------------------------------------------------------------


async def cmd_firewall(args: argparse.Namespace) -> int:
    async with connect() as router:
        raw = await read_nvram(router, FIREWALL_VARS)
        pc = await router.async_get_data(AsusData.PARENTAL_CONTROL) or {}

        def flag(name: str) -> str:
            return _onoff(raw.get(name))

        lines = [
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
        emit({"nvram": raw, "parental_control": pc}, lines, args.json)
    return EXIT_OK


def _split_rulelist(value: Any) -> list[str]:
    """Split an ASUS rule list. Entries are separated by the escaped '<'."""
    if not value or not isinstance(value, str):
        return []
    return [part for part in value.replace("&#60", "<").split("<") if part]


async def cmd_parental(args: argparse.Namespace) -> int:
    target = AsusParentalControl.ON if args.action == "enable" else AsusParentalControl.OFF
    if needs_confirm(args, f"turn parental control {target.name}"):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        ok = await router.async_set_state(target)
        print(f"{'Applied' if ok else 'FAILED'}: parental control {target.name}")
        return EXIT_OK if ok else EXIT_ERROR


# --------------------------------------------------------------------------
# Wireless / guest network
# --------------------------------------------------------------------------


async def cmd_guest_list(args: argparse.Namespace) -> int:
    async with connect() as router:
        gwlan = await router.async_get_data(AsusData.GWLAN) or {}
        lines = [f"{'NETWORK':<12} {'STATE':<8} SSID"]
        for key, value in sorted(gwlan.items()):
            if not isinstance(value, dict):
                continue
            state = "ON" if value.get("bss_enabled") else "OFF"
            lines.append(f"{key:<12} {state:<8} {value.get('ssid', '-')}")
        emit(gwlan, lines, args.json)
    return EXIT_OK


async def cmd_guest_toggle(args: argparse.Namespace) -> int:
    # api_id is "<band index>.<guest index>" and becomes wl<api_id>_bss_enabled
    # (asusrouter/modules/wlan.py::set_state).
    band_index = {"2ghz": 0, "5ghz": 1}[args.band]
    api_id = f"{band_index}.{args.id}"
    target = AsusWLAN.ON if args.action == "enable" else AsusWLAN.OFF

    if needs_confirm(args, f"turn guest network {args.band}_{args.id} {target.name}"):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        ok = await router.async_set_state(target, api_type="gwlan", api_id=api_id)
        print(f"{'Applied' if ok else 'FAILED'}: guest {args.band}_{args.id} {target.name}")
        return EXIT_OK if ok else EXIT_ERROR


# --------------------------------------------------------------------------
# Wireless security
# --------------------------------------------------------------------------

# Band name -> nvram prefix index. wl0 is 2.4 GHz, wl1 is 5 GHz.
BANDS = {"2ghz": 0, "5ghz": 1}

# WPA mode -> (wl<i>_auth_mode_x value, default wl<i>_mfp).
# "psk2" is verified on RT-AX59U; "psk2sae" and "sae" are the standard
# AsusWRT values but are not verified there, which is why every write is
# read back before it is reported as applied.
WPA_MODES = {
    "wpa2": ("psk2", "0"),
    "wpa2wpa3": ("psk2sae", "1"),
    "wpa3": ("sae", "2"),
}

# 802.11w management frame protection.
MFP_VALUES = {"disabled": "0", "capable": "1", "required": "2"}
MFP_NAMES = {v: k for k, v in MFP_VALUES.items()}

WIFI_VARS = ["wps_enable", "wps_enable_x", "wps_multiband", "wps_band_x"] + [
    f"wl{i}_{suffix}"
    for i in (0, 1)
    for suffix in ("radio", "auth_mode_x", "crypto", "mfp", "country_code")
]


def _bands(selection: str) -> list[int]:
    return [0, 1] if selection == "both" else [BANDS[selection]]


def _report_apply(result: dict[str, Any], description: str, as_json: bool) -> int:
    """Print the before/after of an nvram write and pick an exit code.

    async_run_service reports whether the router accepted the request, not
    whether the value stuck, so the read-back is what decides success here.
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
    emit(result, lines, as_json)
    return EXIT_OK if result["ok"] and not result["unchanged"] else EXIT_ERROR


async def cmd_wifi_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        raw = await read_nvram(router, WIFI_VARS)

        lines = [
            f"WPS               {_onoff(raw.get('wps_enable_x'))}"
            f"  (wps_enable={raw.get('wps_enable')!r},"
            f" multiband={raw.get('wps_multiband')!r})",
            "",
            f"{'BAND':<8} {'RADIO':<7} {'AUTH':<10} {'CRYPTO':<8} {'MFP':<10} COUNTRY",
        ]
        for band, i in BANDS.items():
            mfp = str(raw.get(f"wl{i}_mfp"))
            lines.append(
                f"{band:<8} {_onoff(raw.get(f'wl{i}_radio')):<7} "
                f"{str(raw.get(f'wl{i}_auth_mode_x')):<10} "
                f"{str(raw.get(f'wl{i}_crypto')):<8} "
                f"{MFP_NAMES.get(mfp, mfp):<10} {raw.get(f'wl{i}_country_code')}"
            )
        emit(raw, lines, args.json)
    return EXIT_OK


async def cmd_wifi_wps(args: argparse.Namespace) -> int:
    value = "1" if args.action == "enable" else "0"
    description = f"turn WPS {'ON' if args.action == 'enable' else 'OFF'} on all bands"
    if args.action == "enable":
        description += " (the WPS PIN exchange is brute-forceable)"
    if needs_confirm(args, description):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        # wps_enable_x is what the web UI writes and wps_enable is the runtime
        # flag; both are present on RT-AX59U and both are set here so the UI
        # and the radio agree afterwards.
        result = await apply_nvram(
            router,
            {"wps_enable": value, "wps_enable_x": value, "wps_multiband": value},
            "restart_wireless",
        )
        return _report_apply(result, description, args.json)


async def cmd_wifi_security(args: argparse.Namespace) -> int:
    auth, default_mfp = WPA_MODES[args.mode]
    mfp = MFP_VALUES[args.mfp] if args.mfp else default_mfp

    values: dict[str, str] = {}
    for i in _bands(args.band):
        values[f"wl{i}_auth_mode_x"] = auth
        values[f"wl{i}_crypto"] = "aes"
        values[f"wl{i}_mfp"] = mfp

    description = (
        f"set {args.band} to {args.mode} (auth_mode_x={auth}, crypto=aes, "
        f"mfp={MFP_NAMES[mfp]}) — every wireless client reconnects"
    )
    if needs_confirm(args, description):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        result = await apply_nvram(router, values, "restart_wireless")
        return _report_apply(result, description, args.json)


async def cmd_wifi_country(args: argparse.Namespace) -> int:
    code = args.code.upper()
    values = {f"wl{i}_country_code": code for i in _bands(args.band)}
    description = f"set the {args.band} country code to {code}"
    if needs_confirm(args, description):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        result = await apply_nvram(router, values, "restart_wireless")
        exit_code = _report_apply(result, description, args.json)
        if result["unchanged"]:
            print(
                "Country code is usually locked to the hardware SKU on stock "
                "firmware. Compare against: asus-cli nvram reg_spec location_code",
                file=sys.stderr,
            )
        return exit_code


# --------------------------------------------------------------------------
# Firmware
# --------------------------------------------------------------------------

# The router queries ASUS asynchronously and the API gives no completion
# signal, so the result is read back after a pause.
FIRMWARE_CHECK_SECONDS = 5.0


async def _latest_firmware(router: Any, wait: float, cached: bool) -> dict[str, Any]:
    """Read firmware state, refreshing it against ASUS unless told not to.

    `available` is a value cached in the router's nvram, refreshed only by the
    router's own periodic check — which is off by default (webs_update_enable).
    A version you are about to flash from has to be current, so the check is
    run every time rather than trusting whatever was last left there.
    """
    if not cached:
        async with progress("Retrieving router info"):
            if await router.async_set_state(AsusSystem.FIRMWARE_CHECK):
                await asyncio.sleep(wait)
            return await router.async_get_data(AsusData.FIRMWARE, force=True) or {}
    return await router.async_get_data(AsusData.FIRMWARE, force=True) or {}


def _update_status(firmware: dict[str, Any]) -> tuple[str, str | None]:
    """Classify firmware state as (status, latest version).

    status is "update", "current" or "unknown". "unknown" is the honest answer
    when the router could not reach ASUS: webs.available is only populated from
    a reply, so an empty one means nothing was learned — which is different
    from having learned that there is nothing to install.
    """
    webs = firmware.get("webs") or {}

    if enum_name(webs.get("error")) not in ("NONE", "None"):
        return "unknown", None
    if not webs.get("available"):
        return "unknown", None
    if firmware.get("state") and firmware.get("available"):
        return "update", str(firmware["available"])
    return "current", str(webs["available"])


async def cmd_firmware_info(args: argparse.Namespace) -> int:
    async with connect() as router:
        firmware = await _latest_firmware(router, args.wait, args.cached)
        status, latest = _update_status(firmware)

        lines = [f"Current    {firmware.get('current')}"]
        if status == "update":
            lines.append(f"Latest     {latest}   ** update available **")
        elif status == "current":
            lines.append(f"Latest     {latest}   (up to date)")
        else:
            lines.append(
                "Latest     could not verify — the router got no answer from ASUS"
            )
        if args.cached:
            lines.append("           (cached; not checked online just now)")
        if firmware.get("state_beta"):
            lines.append(f"Beta       {firmware.get('available_beta')}")

        note = firmware.get("release_note")
        if note and args.notes:
            lines += ["", "Release note:", str(note)]
        elif note and status == "update":
            lines.append("\nRun `asus-cli firmware info --notes` for the release note.")

        emit({**firmware, "status": status, "latest": latest}, lines, args.json)
    return EXIT_OK


async def cmd_firmware_upgrade(args: argparse.Namespace) -> int:
    """Download and flash a new firmware.

    Unlike the other mutations this connects before it can honour the dry run,
    because the version on offer has to be read before it can be named. Reading
    firmware state has no side effects.
    """
    async with connect() as router:
        firmware = await _latest_firmware(router, args.wait, cached=False)
        current = str(firmware.get("current"))
        status, latest = _update_status(firmware)

        if args.beta:
            if not firmware.get("state_beta") or not firmware.get("available_beta"):
                print(
                    f"No beta update is available; current version is {current}.",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            status, latest = "update", str(firmware["available_beta"])

        if status == "unknown":
            print(
                "Cannot verify the latest firmware version — the router got no "
                "answer from ASUS. Refusing to flash on an unverified version.",
                file=sys.stderr,
            )
            return EXIT_ERROR
        if status == "current":
            print(f"Already up to date on {current}.", file=sys.stderr)
            return EXIT_ERROR

        # With a terminal the version is shown and confirmed interactively.
        # Without one there is nobody to read it, so --yes has to name the
        # version explicitly rather than flash whatever turned up.
        if args.yes and not sys.stdin.isatty():
            if not args.to:
                print(
                    f"Refusing to flash unattended without --to.\n"
                    f"  offered  {latest}\n"
                    "Pass --to with that version to confirm it is the intended one.",
                    file=sys.stderr,
                )
                return EXIT_ERROR
            if args.to != latest:
                print(
                    "--to does not match what the router is offering.\n"
                    f"  requested  {args.to}\n"
                    f"  offered    {latest}",
                    file=sys.stderr,
                )
                return EXIT_ERROR

        description = (
            f"FLASH firmware {latest} over {current}.\n"
            "  The router downloads from ASUS, writes flash, then reboots.\n"
            "  Every connection in the house drops for several minutes.\n"
            "  Losing power while flash is being written can brick the router."
        )
        if needs_confirm(args, description):
            return EXIT_NEEDS_CONFIRM

        if not await router.async_set_state(AsusSystem.FIRMWARE_UPGRADE):
            print("FAILED: the router refused the upgrade request", file=sys.stderr)
            return EXIT_ERROR

        # The API acknowledges the request; it reports nothing about the
        # download or the flash. Do not call this a completed upgrade.
        print(
            f"Upgrade to {latest} requested.\n"
            "The router reports no progress over this API. Expect 5-10 minutes "
            "of downtime, then confirm the new version with: asus-cli info"
        )
        return EXIT_OK


# --------------------------------------------------------------------------
# Raw access / system
# --------------------------------------------------------------------------


async def cmd_nvram(args: argparse.Namespace) -> int:
    """Read arbitrary nvram variables. Read-only by design."""
    async with connect() as router:
        raw = await read_nvram(router, args.names)
        emit(raw, [f"{k:<24} {v!r}" for k, v in raw.items()], args.json)
    return EXIT_OK


async def cmd_reboot(args: argparse.Namespace) -> int:
    if needs_confirm(args, "REBOOT the router (drops every connection for ~60 s)"):
        return EXIT_NEEDS_CONFIRM

    async with connect() as router:
        ok = await router.async_set_state(AsusSystem.REBOOT)
        print(f"{'Reboot requested' if ok else 'FAILED'}")
        return EXIT_OK if ok else EXIT_ERROR


# --------------------------------------------------------------------------
# Parser
# --------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="asus-cli", description="Control an ASUS router over its HTTP API."
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    def mutation(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument(
            "--yes", "-y", action="store_true", dest="yes",
            help="apply without asking; without it you are prompted, or the "
                 "command exits 3 when there is no terminal to ask at",
        )
        # Former name, kept working but no longer advertised.
        sp.add_argument("--confirm", action="store_true", dest="yes",
                        help=argparse.SUPPRESS)
        return sp

    p = sub.add_parser("info", help="model, firmware, uptime")
    p.set_defaults(func=cmd_info)

    p = sub.add_parser("status", help="cpu, ram, wan, uptime")
    p.add_argument("--cpu-sample", type=float, default=CPU_SAMPLE_SECONDS)
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("clients", help="connected and known devices")
    p.add_argument("--online", action="store_true", help="only currently online devices")
    p.set_defaults(func=cmd_clients)

    p = sub.add_parser("wan", help="internet connection detail")
    p.set_defaults(func=cmd_wan)

    # -- port forwarding ---------------------------------------------------
    pf = sub.add_parser("pf", help="port forwarding").add_subparsers(
        dest="pf_command", required=True
    )

    p = pf.add_parser("list", help="show rules")
    p.set_defaults(func=cmd_pf_list)

    p = mutation(pf.add_parser("add", help="add a rule"))
    p.add_argument("--name", required=True, help="label for the rule")
    p.add_argument("--port", required=True, type=int, help="external port")
    p.add_argument("--to-ip", required=True, help="internal IP to forward to")
    p.add_argument("--to-port", type=int, help="internal port (default: same as --port)")
    p.add_argument("--proto", default="TCP", choices=["TCP", "UDP", "BOTH", "OTHER"])
    p.add_argument("--from-ip", default="", help="restrict to this source IP")
    p.add_argument("--force", action="store_true", help="allow a duplicate external port")
    p.set_defaults(func=cmd_pf_add)

    p = mutation(pf.add_parser("remove", help="remove rules by name and/or external port"))
    p.add_argument("--name")
    p.add_argument("--port", type=int)
    p.add_argument("--proto", choices=["TCP", "UDP", "BOTH", "OTHER"])
    p.set_defaults(func=cmd_pf_remove)

    for action in ("enable", "disable"):
        p = mutation(pf.add_parser(action, help=f"{action} port forwarding globally"))
        p.set_defaults(func=cmd_pf_toggle, action=action)

    # -- firewall ----------------------------------------------------------
    p = sub.add_parser("firewall", help="firewall, filters and parental control state")
    p.set_defaults(func=cmd_firewall)

    parental = sub.add_parser("parental", help="parental control").add_subparsers(
        dest="parental_command", required=True
    )
    for action in ("enable", "disable"):
        p = mutation(parental.add_parser(action, help=f"{action} parental control"))
        p.set_defaults(func=cmd_parental, action=action)

    # -- guest wifi --------------------------------------------------------
    guest = sub.add_parser("guest", help="guest wireless networks").add_subparsers(
        dest="guest_command", required=True
    )
    p = guest.add_parser("list", help="show guest networks")
    p.set_defaults(func=cmd_guest_list)

    for action in ("enable", "disable"):
        p = mutation(guest.add_parser(action, help=f"{action} a guest network"))
        p.add_argument("--band", required=True, choices=["2ghz", "5ghz"])
        p.add_argument("--id", required=True, type=int, choices=[1, 2, 3])
        p.set_defaults(func=cmd_guest_toggle, action=action)

    # -- wireless security -------------------------------------------------
    wifi = sub.add_parser("wifi", help="wireless security settings").add_subparsers(
        dest="wifi_command", required=True
    )

    p = wifi.add_parser("show", help="radio, WPA mode, MFP, country code, WPS")
    p.set_defaults(func=cmd_wifi_show)

    wps = wifi.add_parser("wps", help="Wi-Fi Protected Setup").add_subparsers(
        dest="wps_command", required=True
    )
    for action in ("enable", "disable"):
        p = mutation(wps.add_parser(action, help=f"{action} WPS on all bands"))
        p.set_defaults(func=cmd_wifi_wps, action=action)

    p = mutation(wifi.add_parser("security", help="WPA mode and frame protection"))
    p.add_argument("--band", default="both", choices=["2ghz", "5ghz", "both"])
    p.add_argument("--mode", required=True, choices=sorted(WPA_MODES))
    p.add_argument(
        "--mfp",
        choices=sorted(MFP_VALUES),
        help="802.11w level; defaults to what the mode needs",
    )
    p.set_defaults(func=cmd_wifi_security)

    p = mutation(wifi.add_parser("country", help="regulatory country code"))
    p.add_argument("--band", default="both", choices=["2ghz", "5ghz", "both"])
    p.add_argument("--code", required=True, help="two-letter code, e.g. AU")
    p.set_defaults(func=cmd_wifi_country)

    # -- firmware ----------------------------------------------------------
    firmware = sub.add_parser("firmware", help="firmware version and upgrade")
    firmware_sub = firmware.add_subparsers(dest="firmware_command", required=True)

    p = firmware_sub.add_parser("info", help="current and latest version")
    p.add_argument("--notes", action="store_true", help="show the release note")
    p.add_argument("--cached", action="store_true",
                   help="skip the online check and report the router's cached value")
    p.add_argument("--wait", type=float, default=FIRMWARE_CHECK_SECONDS)
    p.set_defaults(func=cmd_firmware_info)

    p = mutation(firmware_sub.add_parser("upgrade", help="download and flash firmware"))
    p.add_argument("--to", help="version to install; required with --yes when "
                               "there is no terminal to confirm at")
    p.add_argument("--beta", action="store_true", help="target the beta channel")
    p.add_argument("--wait", type=float, default=FIRMWARE_CHECK_SECONDS)
    p.set_defaults(func=cmd_firmware_upgrade)

    # -- raw / system ------------------------------------------------------
    p = sub.add_parser("nvram", help="read raw nvram variables (read-only)")
    p.add_argument("names", nargs="+", help="variable names")
    p.set_defaults(func=cmd_nvram)

    p = mutation(sub.add_parser("reboot", help="reboot the router"))
    p.set_defaults(func=cmd_reboot)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not hasattr(args, "yes"):
        args.yes = True  # read-only commands never need confirmation

    try:
        sys.exit(asyncio.run(args.func(args)))
    except ConfigError as err:
        print(str(err), file=sys.stderr)
        sys.exit(EXIT_CONFIG)
    except AsusRouterError as err:
        print(f"Router error: {err}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
    except KeyboardInterrupt:
        sys.exit(EXIT_ERROR)


if __name__ == "__main__":
    main()
