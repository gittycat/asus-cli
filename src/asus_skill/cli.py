"""asus — command line control for an ASUS router over its HTTP API.

Read commands print a human-readable summary, or JSON with --json.
Every command that changes the router requires an explicit --confirm;
without it the command prints what it would do and exits 3.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from asusrouter import AsusData, AsusRouterError
from asusrouter.modules.parental_control import AsusParentalControl
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule
from asusrouter.modules.system import AsusSystem
from asusrouter.modules.wlan import AsusWLAN

from asus_skill.router import (
    ConfigError,
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


def needs_confirm(args: argparse.Namespace, description: str) -> bool:
    """Refuse a mutation unless --confirm was passed. Returns True if refused."""
    if args.confirm:
        return False
    print(f"Would {description}\nRe-run with --confirm to apply.", file=sys.stderr)
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
            print("Note: port forwarding is globally OFF. Run: asus pf enable --confirm")
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
            value = raw.get(name)
            return {"1": "ON", "0": "OFF"}.get(str(value), f"? ({value!r})")

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
        prog="asus", description="Control an ASUS router over its HTTP API."
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    sub = parser.add_subparsers(dest="command", required=True)

    def mutation(sp: argparse.ArgumentParser) -> argparse.ArgumentParser:
        sp.add_argument("--confirm", action="store_true", help="actually apply the change")
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

    # -- raw / system ------------------------------------------------------
    p = sub.add_parser("nvram", help="read raw nvram variables (read-only)")
    p.add_argument("names", nargs="+", help="variable names")
    p.set_defaults(func=cmd_nvram)

    p = mutation(sub.add_parser("reboot", help="reboot the router"))
    p.set_defaults(func=cmd_reboot)

    return parser


def main() -> None:
    args = build_parser().parse_args()
    if not hasattr(args, "confirm"):
        args.confirm = True  # read-only commands never need confirmation

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
