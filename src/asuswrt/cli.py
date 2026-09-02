"""asuswrt — command line control for an ASUS router over its HTTP API.

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

from asuswrt import render
from asuswrt.router import (
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


async def _system_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    """Identity: what the router is. None of it changes until a reboot or a flash."""
    identity = await router.async_get_identity()
    payload = {
        "model": identity.model,
        "product_id": identity.product_id,
        "firmware": str(identity.firmware),
        "merlin": identity.merlin,
        "mac": identity.mac,
        "serial": identity.serial,
        "aimesh": identity.aimesh,
        "services": len(identity.services or []),
    }
    return payload, render.system(payload)


async def _system_health(router: Any, cpu_sample: float) -> tuple[dict[str, Any], list[str]]:
    """Live load: everything that moves while the router is running."""
    # CPU usage is a delta between two samples, so one fetch always
    # yields usage=None (hook.py::process_cpu). Take a second sample.
    await router.async_get_data(AsusData.CPU)
    await asyncio.sleep(cpu_sample)
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
    return payload, render.health(payload)


async def _wan_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    wan = await router.async_get_data(AsusData.WAN) or {}
    return wan, render.wan(wan)


async def _client_rows(router: Any, online_only: bool = False) -> list[dict[str, Any]]:
    clients = await router.async_get_data(AsusData.CLIENTS) or {}
    rows = []
    for mac, client in clients.items():
        conn = getattr(client, "connection", None)
        desc = getattr(client, "description", None)
        online = bool(getattr(conn, "online", False))
        if online_only and not online:
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
    return rows


# --------------------------------------------------------------------------
# Read commands
# --------------------------------------------------------------------------


async def cmd_system_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _system_show(router)
        emit(payload, lines, args.json)
    return EXIT_OK


async def cmd_system_health(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _system_health(router, args.cpu_sample)
        emit(payload, lines, args.json)
    return EXIT_OK


async def cmd_clients(args: argparse.Namespace) -> int:
    async with connect() as router:
        rows = await _client_rows(router, args.online)
        emit(rows, render.client_lines(rows), args.json)
    return EXIT_OK


async def cmd_wan(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _wan_show(router)
        emit(payload, lines, args.json)
    return EXIT_OK


async def cmd_show(args: argparse.Namespace) -> int:
    """Every read in one connection.

    Each `<noun> show` is a separate process and therefore a separate login to
    the router, so answering "how is the router doing" one noun at a time costs
    a handshake per noun. This walks the same helpers over a single connection.

    The firmware check is left out unless asked for: it makes the router query
    ASUS and adds several seconds, and it answers a question ("should I
    upgrade") that is not part of a status sweep.
    """
    async with connect() as router:
        sections: list[tuple[str, str, Any, list[str]]] = []

        payload, lines = await _system_show(router)
        sections.append(("SYSTEM", "system", payload, lines))

        payload, lines = await _system_health(router, args.cpu_sample)
        sections.append(("HEALTH", "health", payload, lines))

        payload, lines = await _wan_show(router)
        sections.append(("INTERNET", "wan", payload, lines))

        rows = await _client_rows(router)
        online = sum(r["online"] for r in rows)
        sections.append(
            (
                "CLIENTS",
                "clients",
                {"online": online, "known": len(rows)},
                [
                    f"{online} online / {len(rows)} known"
                    "   (full table: asuswrt clients)"
                ],
            )
        )

        payload, lines = await _firewall_show(router)
        sections.append(("FIREWALL", "firewall", payload, lines))

        payload, lines = await _parental_show(router)
        sections.append(("PARENTAL CONTROL", "parental", payload, lines))

        payload, lines = await _pf_show(router)
        sections.append(("PORT FORWARDING", "port_forwarding", payload, lines))

        payload, lines = await _guest_show(router)
        sections.append(("GUEST WIFI", "guest", payload, lines))

        payload, lines = await _wifi_show(router)
        sections.append(("WIRELESS", "wifi", payload, lines))

        if args.firmware:
            firmware = await _latest_firmware(router, args.wait)
            status, latest = _update_status(firmware)
            lines = [f"Current    {firmware.get('current')}"]
            if status == "update":
                lines.append(f"Latest     {latest}   ** update available **")
            elif status == "current":
                lines.append(f"Latest     {latest}   (up to date)")
            else:
                lines.append("Latest     could not verify")
            sections.append(
                (
                    "FIRMWARE",
                    "firmware",
                    {**firmware, "status": status, "latest": latest},
                    lines,
                )
            )

        out = render.overview(sections, firmware_checked=args.firmware)
        emit({key: payload for _, key, payload, _ in sections}, out, args.json)
    return EXIT_OK


# --------------------------------------------------------------------------
# Port forwarding
# --------------------------------------------------------------------------


async def _pf_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    data = await router.async_get_data(AsusData.PORT_FORWARDING) or {}
    rules = await port_forwarding_rules(router)
    payload = {"state": enum_name(data.get("state")), "rules": rules}
    return payload, render.port_forwarding(payload)


async def cmd_pf_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _pf_show(router)
        emit(payload, lines, args.json)
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
            print("Note: port forwarding is globally OFF. Run: asuswrt pf enable --yes")
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


async def _firewall_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    raw = await read_nvram(router, FIREWALL_VARS)
    pc = await router.async_get_data(AsusData.PARENTAL_CONTROL) or {}
    payload = {"nvram": raw, "parental_control": pc}
    return payload, render.firewall(payload)


async def cmd_firewall_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _firewall_show(router)
        emit(payload, lines, args.json)
    return EXIT_OK


async def _parental_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    pc = await router.async_get_data(AsusData.PARENTAL_CONTROL) or {}
    return pc, render.parental(pc)


async def cmd_parental_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _parental_show(router)
        emit(payload, lines, args.json)
    return EXIT_OK


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


async def _guest_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    gwlan = await router.async_get_data(AsusData.GWLAN) or {}
    return gwlan, render.guest(gwlan)


async def cmd_guest_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _guest_show(router)
        emit(payload, lines, args.json)
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
    emit(result, render.apply_report(result, description), as_json)
    return EXIT_OK if result["ok"] and not result["unchanged"] else EXIT_ERROR


async def _wifi_show(router: Any) -> tuple[dict[str, Any], list[str]]:
    raw = await read_nvram(router, WIFI_VARS)
    return raw, render.wifi(raw)


async def cmd_wifi_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        payload, lines = await _wifi_show(router)
        emit(payload, lines, args.json)
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
                "firmware. Compare against: asuswrt nvram reg_spec location_code",
                file=sys.stderr,
            )
        return exit_code


# --------------------------------------------------------------------------
# Firmware
# --------------------------------------------------------------------------

# The router queries ASUS asynchronously and the API gives no completion
# signal, so the result is read back after a pause.
FIRMWARE_CHECK_SECONDS = 5.0


async def _latest_firmware(router: Any, wait: float) -> dict[str, Any]:
    """Read firmware state, always refreshing it against ASUS first.

    The router keeps a copy of `available` in nvram, but it is only refreshed
    by the router's own periodic check — which is off by default
    (webs_update_enable), so the stored value is routinely months stale and
    worth nothing. The only number that matters here is what ASUS is offering
    right now, because the sole purpose of reading it is to decide whether to
    upgrade. So the check is run every time and the stored value is ignored.
    """
    async with progress("Asking the router to check with ASUS"):
        if await router.async_set_state(AsusSystem.FIRMWARE_CHECK):
            await asyncio.sleep(wait)
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


async def cmd_firmware_show(args: argparse.Namespace) -> int:
    async with connect() as router:
        firmware_data = await _latest_firmware(router, args.wait)
        status, latest = _update_status(firmware_data)
        payload = {**firmware_data, "status": status, "latest": latest}
        emit(payload, render.firmware(payload, notes=args.notes), args.json)
    return EXIT_OK


async def cmd_firmware_upgrade(args: argparse.Namespace) -> int:
    """Download and flash a new firmware.

    Unlike the other mutations this connects before it can honour the dry run,
    because the version on offer has to be read before it can be named. Reading
    firmware state has no side effects.
    """
    async with connect() as router:
        firmware = await _latest_firmware(router, args.wait)
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
            "of downtime, then confirm the new version with: asuswrt system show"
        )
        return EXIT_OK


# --------------------------------------------------------------------------
# Raw access / system
# --------------------------------------------------------------------------


async def cmd_nvram(args: argparse.Namespace) -> int:
    """Read arbitrary nvram variables. Read-only by design.

    `nvram get a b` and `nvram a b` are the same command: `get` is the regular
    verb, but no nvram variable is called that, so a leading one is the verb.
    """
    names = args.names[1:] if args.names[:1] == ["get"] else args.names
    if not names:
        print("Give at least one variable name.", file=sys.stderr)
        return EXIT_ERROR

    async with connect() as router:
        raw = await read_nvram(router, names)
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
    """Build the command tree.

    The shape is noun -> verb, and it is regular on purpose: every noun has a
    `show`, `show` is the only read verb, and a bare noun means `show`. An
    agent that knows the nouns can therefore reach any reading without being
    told which command happens to hold it.

    Names that existed before the tree was regularised still work but are
    hidden from --help: `info`, `status`, `pf`, `list`, `firmware info`,
    `wifi security`, `wifi country`. Nothing is ever removed, because a name
    an agent has already learned is a contract.
    """
    parser = argparse.ArgumentParser(
        prog="asuswrt", description="Control an ASUS router over its HTTP API."
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

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

    def flags(*adders: Any) -> argparse.ArgumentParser:
        """A reusable set of options, so a noun and its `show` both accept them."""
        parent = argparse.ArgumentParser(add_help=False)
        for add in adders:
            add(parent)
        return parent

    def cpu_sample(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--cpu-sample", type=float, default=CPU_SAMPLE_SECONDS,
                        help="seconds between the two CPU samples")

    def online(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--online", action="store_true",
                        help="only currently online devices")

    def fw_read(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--notes", action="store_true", help="show the release note")
        sp.add_argument("--wait", type=float, default=FIRMWARE_CHECK_SECONDS,
                        help="seconds to wait for the router's reply from ASUS")

    def noun(
        name: str,
        help_text: str,
        read: Any,
        *,
        aliases: list[str] | None = None,
        read_aliases: list[str] | None = None,
        opts: argparse.ArgumentParser | None = None,
    ) -> Any:
        """Add a noun whose bare form reads it, and return its verb table."""
        parents = [opts] if opts else []
        np = sub.add_parser(name, help=help_text, aliases=aliases or [], parents=parents)
        np.set_defaults(func=read)
        verbs = np.add_subparsers(dest=f"{name}_command", required=False)
        sp = verbs.add_parser(
            "show", help=help_text, aliases=read_aliases or [], parents=parents
        )
        sp.set_defaults(func=read)
        return verbs

    # -- everything at once ------------------------------------------------
    p = sub.add_parser(
        "show", help="every reading in one connection", parents=[flags(cpu_sample)]
    )
    p.add_argument("--firmware", action="store_true",
                   help="also check ASUS for a firmware update (adds ~7 s)")
    p.add_argument("--wait", type=float, default=FIRMWARE_CHECK_SECONDS,
                   help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_show)

    # -- system ------------------------------------------------------------
    system = noun("system", "model, firmware, MAC, AiMesh", cmd_system_show)
    p = system.add_parser(
        "health", help="uptime, CPU, RAM, WAN", parents=[flags(cpu_sample)]
    )
    p.set_defaults(func=cmd_system_health)

    # -- network -----------------------------------------------------------
    noun("wan", "internet connection detail", cmd_wan)
    noun("clients", "connected and known devices", cmd_clients, opts=flags(online))

    # -- firewall and parental control -------------------------------------
    noun("firewall", "firewall, filters and parental control state", cmd_firewall_show)

    parental = noun("parental", "parental control", cmd_parental_show)
    for action in ("enable", "disable"):
        p = mutation(parental.add_parser(action, help=f"{action} parental control"))
        p.set_defaults(func=cmd_parental, action=action)

    # -- port forwarding ---------------------------------------------------
    pf = noun(
        "portforward", "port forwarding", cmd_pf_show,
        aliases=["pf"], read_aliases=["list"],
    )

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

    # -- guest wifi --------------------------------------------------------
    guest = noun(
        "guest", "guest wireless networks", cmd_guest_show, read_aliases=["list"]
    )
    for action in ("enable", "disable"):
        p = mutation(guest.add_parser(action, help=f"{action} a guest network"))
        p.add_argument("--band", required=True, choices=["2ghz", "5ghz"])
        p.add_argument("--id", required=True, type=int, choices=[1, 2, 3])
        p.set_defaults(func=cmd_guest_toggle, action=action)

    # -- wireless security -------------------------------------------------
    wifi = noun(
        "wifi", "radio, WPA mode, MFP, country code, WPS", cmd_wifi_show
    )

    wps = wifi.add_parser("wps", help="Wi-Fi Protected Setup").add_subparsers(
        dest="wps_command", required=True
    )
    for action in ("enable", "disable"):
        p = mutation(wps.add_parser(action, help=f"{action} WPS on all bands"))
        p.set_defaults(func=cmd_wifi_wps, action=action)

    p = mutation(wifi.add_parser(
        "set-security", help="WPA mode and frame protection", aliases=["security"]
    ))
    p.add_argument("--band", default="both", choices=["2ghz", "5ghz", "both"])
    p.add_argument("--mode", required=True, choices=sorted(WPA_MODES))
    p.add_argument(
        "--mfp",
        choices=sorted(MFP_VALUES),
        help="802.11w level; defaults to what the mode needs",
    )
    p.set_defaults(func=cmd_wifi_security)

    p = mutation(wifi.add_parser(
        "set-country", help="regulatory country code", aliases=["country"]
    ))
    p.add_argument("--band", default="both", choices=["2ghz", "5ghz", "both"])
    p.add_argument("--code", required=True, help="two-letter code, e.g. AU")
    p.set_defaults(func=cmd_wifi_country)

    # -- firmware ----------------------------------------------------------
    firmware = noun(
        "firmware", "installed version and what ASUS is offering",
        cmd_firmware_show, read_aliases=["info"], opts=flags(fw_read),
    )

    p = mutation(firmware.add_parser("upgrade", help="download and flash firmware"))
    p.add_argument("--to", help="version to install; required with --yes when "
                               "there is no terminal to confirm at")
    p.add_argument("--beta", action="store_true", help="target the beta channel")
    p.add_argument("--wait", type=float, default=FIRMWARE_CHECK_SECONDS)
    p.set_defaults(func=cmd_firmware_upgrade)

    # -- raw / system ------------------------------------------------------
    p = sub.add_parser("nvram", help="read raw nvram variables (read-only)")
    p.add_argument("names", nargs="+", metavar="get NAME [NAME ...]",
                   help="variable names, optionally after the verb `get`")
    p.set_defaults(func=cmd_nvram)

    p = mutation(sub.add_parser("reboot", help="reboot the router"))
    p.set_defaults(func=cmd_reboot)

    # -- names from before the tree was regularised ------------------------
    p = sub.add_parser("info")
    p.set_defaults(func=cmd_system_show)

    p = sub.add_parser("status", parents=[flags(cpu_sample)])
    p.set_defaults(func=cmd_system_health)

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
