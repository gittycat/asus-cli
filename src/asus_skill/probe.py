"""Feasibility probe: connect to an ASUS router and read basic information.

Run:  uv run probe
      uv run probe --raw           # full JSON dump of everything fetched
      uv run probe --only cpu,wan  # limit to specific data types
"""

from __future__ import annotations

import argparse
import asyncio
import dataclasses
import json
import sys
import time
from enum import Enum
from typing import Any

import aiohttp

from asusrouter import AsusData, AsusRouter, AsusRouterError

from asus_skill.router import ConfigError, load_config

# Data types worth probing for a "does this work at all" test.
# Order matters only for readability of the output.
PROBES: list[AsusData] = [
    AsusData.SYSTEM,
    AsusData.CPU,
    AsusData.RAM,
    AsusData.BOOTTIME,
    AsusData.WAN,
    AsusData.NETWORK,
    AsusData.CLIENTS,
    AsusData.WLAN,
    AsusData.GWLAN,
    AsusData.PORT_FORWARDING,
    AsusData.PARENTAL_CONTROL,
    AsusData.LED,
    AsusData.PORTS,
    AsusData.TEMPERATURE,
    AsusData.FIRMWARE,
    AsusData.AIMESH,
]


def jsonable(value: Any) -> Any:
    """Convert library objects into something json.dumps can handle."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {k: jsonable(v) for k, v in dataclasses.asdict(value).items()}
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def preview(value: Any, width: int = 88) -> str:
    """One-line preview of a fetched payload."""
    data = jsonable(value)
    if isinstance(data, dict):
        head = ", ".join(list(data)[:6])
        more = "" if len(data) <= 6 else f", +{len(data) - 6} more"
        return f"dict[{len(data)}] {{{head}{more}}}"[:width]
    if isinstance(data, list):
        return f"list[{len(data)}] {json.dumps(data[:1])}"[:width]
    return json.dumps(data)[:width]


def enum_name(value: Any) -> str:
    """Render an IntEnum as its name rather than a bare number."""
    return value.name if isinstance(value, Enum) else str(value)


def highlights(results: dict[AsusData, Any]) -> list[str]:
    """Pull the handful of numbers a human actually wants to see.

    Field names below are taken from the library's own parsers
    (modules/endpoint/hook.py), not guessed.
    """
    out: list[str] = []

    def dig(datatype: AsusData, *path: Any) -> Any:
        node = results.get(datatype)
        for key in path:
            if not isinstance(node, dict):
                return None
            node = node.get(key)
        return node

    uptime = dig(AsusData.BOOTTIME, "uptime")
    if uptime is not None:
        hours = int(uptime) // 3600
        out.append(f"Uptime          {hours // 24} d {hours % 24} h")

    # `usage` is a delta between two samples, so it only exists on a re-fetch.
    cpu_total = dig(AsusData.CPU, "total", "usage")
    cores = results.get(AsusData.CPU)
    if cpu_total is not None:
        n_cores = len([k for k in cores if k != "total"]) if isinstance(cores, dict) else 0
        out.append(f"CPU usage       {cpu_total:.1f}% across {n_cores} cores")

    ram = results.get(AsusData.RAM)
    if isinstance(ram, dict) and ram.get("usage") is not None:
        used_mb = (ram.get("used") or 0) / 1024
        total_mb = (ram.get("total") or 0) / 1024
        out.append(f"RAM usage       {ram['usage']:.1f}%  ({used_mb:.0f} / {total_mb:.0f} MB)")

    # WAN is nested: general state under "internet", per-port under 0 and 1.
    internet = dig(AsusData.WAN, "internet")
    if isinstance(internet, dict):
        unit = internet.get("unit")
        link = enum_name(internet.get("link"))
        ip = internet.get("ip_address")
        out.append(f"WAN             link={link}  ip={ip}  (unit {unit})")
        unit_state = dig(AsusData.WAN, unit, "state")
        if unit_state is not None:
            out.append(f"WAN port state  {enum_name(unit_state)}")

    # Clients are AsusClient dataclasses; online lives on .connection.online
    clients = results.get(AsusData.CLIENTS)
    if isinstance(clients, dict):
        online = [
            c for c in clients.values() if getattr(getattr(c, "connection", None), "online", False)
        ]
        out.append(f"Clients         {len(clients)} known, {len(online)} online")
        for client in online[:5]:
            desc = getattr(client, "description", None)
            conn = getattr(client, "connection", None)
            name = getattr(desc, "name", None) or getattr(desc, "mac", "?")
            out.append(
                f"                - {name:<22} {getattr(conn, 'ip_address', '?'):<15}"
                f" {enum_name(getattr(conn, 'type', None))}"
            )
        if len(online) > 5:
            out.append(f"                  ... +{len(online) - 5} more")

    # "rules" is absent entirely when the rule list is empty.
    pfw = results.get(AsusData.PORT_FORWARDING)
    if isinstance(pfw, dict):
        rules = pfw.get("rules") or []
        out.append(f"Port forwards   {enum_name(pfw.get('state'))}, {len(rules)} rule(s)")
        for rule in rules[:5]:
            out.append(
                f"                - {rule.name:<18} :{rule.port_external} -> "
                f"{rule.ip_address}:{rule.port} {rule.protocol}"
            )

    pc = results.get(AsusData.PARENTAL_CONTROL)
    if isinstance(pc, dict):
        out.append(
            f"Parental ctrl   {enum_name(pc.get('state'))}, "
            f"{len(pc.get('rules') or [])} rule(s)"
        )

    return out


async def probe(args: argparse.Namespace) -> int:
    try:
        config = load_config()
    except ConfigError as err:
        print(str(err), file=sys.stderr)
        return 2

    wanted = PROBES
    if args.only:
        names = {n.strip().lower() for n in args.only.split(",")}
        wanted = [d for d in PROBES if d.value in names]
        if not wanted:
            print(f"No data types matched --only {args.only!r}", file=sys.stderr)
            return 2

    print(f"Connecting to {config.url} as {config.username} ...")

    async with aiohttp.ClientSession() as session:
        router = AsusRouter(
            hostname=config.host,
            username=config.username,
            password=config.password,
            port=config.port,
            use_ssl=config.use_ssl,
            session=session,
        )

        try:
            connected = await router.async_connect()
        except AsusRouterError as err:
            print(f"Connection failed: {err}", file=sys.stderr)
            return 1
        if not connected:
            print("Connection refused (check credentials).", file=sys.stderr)
            return 1

        try:
            identity = await router.async_get_identity()
            print("\n--- Identity ---")
            print(f"Model           {identity.model} ({identity.product_id})")
            print(f"Firmware        {identity.firmware}  merlin={identity.merlin}")
            print(f"MAC             {identity.mac}")
            print(f"Serial          {identity.serial}")
            print(f"AiMesh          {identity.aimesh}")
            print(f"Services        {len(identity.services or [])} available")

            print(f"\n--- Probing {len(wanted)} data types ---")
            results: dict[AsusData, Any] = {}
            failures: list[tuple[AsusData, str]] = []
            empties: list[AsusData] = []

            for datatype in wanted:
                started = time.perf_counter()
                try:
                    data = await router.async_get_data(datatype)
                    # CPU usage is computed against the previous sample, so a
                    # single fetch always yields usage=None. Take a second one.
                    if datatype is AsusData.CPU:
                        await asyncio.sleep(args.cpu_sample)
                        data = await router.async_get_data(datatype, force=True)
                except Exception as err:  # noqa: BLE001 - probing, report and continue
                    failures.append((datatype, f"{type(err).__name__}: {err}"))
                    print(f"  FAIL  {datatype.value:<16} {type(err).__name__}")
                    continue
                elapsed = (time.perf_counter() - started) * 1000
                if data is None or data == {} or data == []:
                    empties.append(datatype)
                    print(f"  EMPTY {datatype.value:<16} ({elapsed:.0f} ms)")
                    continue
                results[datatype] = data
                print(f"  OK    {datatype.value:<16} ({elapsed:.0f} ms)  {preview(data)}")

            lines = highlights(results)
            if lines:
                print("\n--- Highlights ---")
                for line in lines:
                    print(f"  {line}")

            print(
                f"\n--- Verdict ---\n  {len(results)}/{len(wanted)} data types "
                f"returned data, {len(failures)} failed."
            )
            for datatype, reason in failures:
                print(f"  {datatype.value}: {reason}")
            if empties:
                print(
                    "  Empty (endpoint answered, model has no such data): "
                    + ", ".join(d.value for d in empties)
                )

            if args.raw:
                print("\n--- Raw ---")
                print(
                    json.dumps(
                        {d.value: jsonable(v) for d, v in results.items()},
                        indent=2,
                        default=str,
                    )
                )
        finally:
            await router.async_disconnect()

    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="ASUS router feasibility probe")
    parser.add_argument("--raw", action="store_true", help="dump full JSON payloads")
    parser.add_argument("--only", help="comma-separated data types, e.g. cpu,wan,clients")
    parser.add_argument(
        "--cpu-sample",
        type=float,
        default=2.0,
        help="seconds between the two CPU samples needed to compute usage (default: 2)",
    )
    sys.exit(asyncio.run(probe(parser.parse_args())))


if __name__ == "__main__":
    main()
