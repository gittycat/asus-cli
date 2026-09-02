"""Domain operations — the payload half of every command.

Every function here takes a connected router (and whatever plain arguments
the operation needs) and returns the payload the CLI's read helpers already
build today, or a small result dict for a mutation. Nothing here prints,
reads argv or stdin, or imports argparse — that all stays in the CLI. The
spinner is a CLI concern too: the one function that is genuinely slow
(`firmware`, via `_latest_firmware`) does its waiting silently; the caller
wraps it in `progress(...)` if it wants to show that on a terminal.

Payloads are returned exactly as the library and these helpers build them —
library enums, `PortForwardingRule` objects, integer WAN unit keys and all.
Nothing here runs a payload through `jsonable()`; the CLI's `emit` and the
MCP boundary each do that themselves. Converting early would silently change
the human-readable output for `wan`, `firewall` and `parental`.

Domain refusals — the router or the requested change cannot proceed — are
raised as `ValueError` carrying the same message the CLI has always printed.
"""

from __future__ import annotations

import asyncio
from typing import Any

from asusrouter import AsusData
from asusrouter.modules.parental_control import AsusParentalControl
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule
from asusrouter.modules.system import AsusSystem
from asusrouter.modules.wlan import AsusWLAN

from asuswrt.router import apply_nvram, enum_name, port_forwarding_rules, read_nvram

# Seconds between the two CPU samples needed to compute a usage delta.
CPU_SAMPLE_SECONDS = 2.0

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

# The router queries ASUS asynchronously and the API gives no completion
# signal, so the result is read back after a pause.
FIRMWARE_CHECK_SECONDS = 5.0


def _bands(selection: str) -> list[int]:
    return [0, 1] if selection == "both" else [BANDS[selection]]


def _split_rulelist(value: Any) -> list[str]:
    """Split an ASUS rule list. Entries are separated by the escaped '<'."""
    if not value or not isinstance(value, str):
        return []
    return [part for part in value.replace("&#60", "<").split("<") if part]


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


async def _latest_firmware(router: Any, wait: float) -> dict[str, Any]:
    """Read firmware state, always refreshing it against ASUS first.

    The router keeps a copy of `available` in nvram, but it is only refreshed
    by the router's own periodic check — which is off by default
    (webs_update_enable), so the stored value is routinely months stale and
    worth nothing. The only number that matters here is what ASUS is offering
    right now, because the sole purpose of reading it is to decide whether to
    upgrade. So the check is run every time and the stored value is ignored.
    """
    if await router.async_set_state(AsusSystem.FIRMWARE_CHECK):
        await asyncio.sleep(wait)
    return await router.async_get_data(AsusData.FIRMWARE, force=True) or {}


def _resolve_upgrade_target(payload: dict[str, Any], beta: bool) -> tuple[str, str]:
    """Given a `firmware()` payload, decide (status, latest) for an upgrade.

    Applies the beta override and raises the refusals that do not depend on
    `to` or on whether anyone is at a terminal.
    """
    current = str(payload.get("current"))
    status, latest = payload["status"], payload["latest"]

    if beta:
        if not payload.get("state_beta") or not payload.get("available_beta"):
            raise ValueError(f"No beta update is available; current version is {current}.")
        status, latest = "update", str(payload["available_beta"])

    if status == "unknown":
        raise ValueError(
            "Cannot verify the latest firmware version — the router got no "
            "answer from ASUS. Refusing to flash on an unverified version."
        )
    if status == "current":
        raise ValueError(f"Already up to date on {current}.")

    return current, latest


def _pf_matches(
    rule: PortForwardingRule, name: str | None, port: int | None, proto: str | None
) -> bool:
    if name and rule.name != name:
        return False
    if port and rule.port_external != str(port):
        return False
    if proto and rule.protocol != proto:
        return False
    return bool(name or port)


# --------------------------------------------------------------------------
# Reads
# --------------------------------------------------------------------------


async def system(router: Any) -> dict[str, Any]:
    """Identity: what the router is. None of it changes until a reboot or a flash."""
    identity = await router.async_get_identity()
    return {
        "model": identity.model,
        "product_id": identity.product_id,
        "firmware": str(identity.firmware),
        "merlin": identity.merlin,
        "mac": identity.mac,
        "serial": identity.serial,
        "aimesh": identity.aimesh,
        "services": len(identity.services or []),
    }


async def health(router: Any, cpu_sample: float) -> dict[str, Any]:
    """Live load: everything that moves while the router is running."""
    # CPU usage is a delta between two samples, so one fetch always
    # yields usage=None (hook.py::process_cpu). Take a second sample.
    await router.async_get_data(AsusData.CPU)
    await asyncio.sleep(cpu_sample)
    cpu = await router.async_get_data(AsusData.CPU, force=True) or {}
    ram = await router.async_get_data(AsusData.RAM) or {}
    wan_data = await router.async_get_data(AsusData.WAN) or {}
    boottime = await router.async_get_data(AsusData.BOOTTIME) or {}

    internet = wan_data.get("internet", {}) if isinstance(wan_data, dict) else {}
    hours = int(boottime.get("uptime", 0)) // 3600
    cpu_total = (cpu.get("total") or {}).get("usage")
    cores = {k: (v or {}).get("usage") for k, v in cpu.items() if k != "total"}

    return {
        "uptime_hours": hours,
        "cpu_usage": cpu_total,
        "cpu_cores": cores,
        "ram": ram,
        "wan_link": enum_name(internet.get("link")),
        "wan_ip": internet.get("ip_address"),
    }


async def wan(router: Any) -> dict[str, Any]:
    return await router.async_get_data(AsusData.WAN) or {}


async def clients(router: Any, online_only: bool = False) -> list[dict[str, Any]]:
    data = await router.async_get_data(AsusData.CLIENTS) or {}
    rows = []
    for mac, client in data.items():
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


async def firewall(router: Any) -> dict[str, Any]:
    raw = await read_nvram(router, FIREWALL_VARS)
    pc = await router.async_get_data(AsusData.PARENTAL_CONTROL) or {}
    return {"nvram": raw, "parental_control": pc}


async def parental(router: Any) -> dict[str, Any]:
    return await router.async_get_data(AsusData.PARENTAL_CONTROL) or {}


async def port_forwarding(router: Any) -> dict[str, Any]:
    data = await router.async_get_data(AsusData.PORT_FORWARDING) or {}
    rules = await port_forwarding_rules(router)
    return {"state": enum_name(data.get("state")), "rules": rules}


async def guest(router: Any) -> dict[str, Any]:
    return await router.async_get_data(AsusData.GWLAN) or {}


async def wifi(router: Any) -> dict[str, Any]:
    return await read_nvram(router, WIFI_VARS)


async def firmware(router: Any, wait: float) -> dict[str, Any]:
    firmware_data = await _latest_firmware(router, wait)
    status, latest = _update_status(firmware_data)
    return {**firmware_data, "status": status, "latest": latest}


async def nvram(router: Any, names: list[str]) -> dict[str, Any]:
    return await read_nvram(router, names)


async def overview(
    router: Any, cpu_sample: float, include_firmware: bool, wait: float
) -> dict[str, Any]:
    """Every read in one connection — the payload half of `show`."""
    result: dict[str, Any] = {}
    result["system"] = await system(router)
    result["health"] = await health(router, cpu_sample)
    result["wan"] = await wan(router)
    rows = await clients(router)
    result["clients"] = {
        "online": sum(r["online"] for r in rows),
        "known": len(rows),
    }
    result["firewall"] = await firewall(router)
    result["parental"] = await parental(router)
    result["port_forwarding"] = await port_forwarding(router)
    result["guest"] = await guest(router)
    result["wifi"] = await wifi(router)
    if include_firmware:
        result["firmware"] = await firmware(router, wait)
    return result


# --------------------------------------------------------------------------
# Writes
# --------------------------------------------------------------------------


async def port_forward_add(
    router: Any, rule: PortForwardingRule, force: bool = False
) -> dict[str, Any]:
    current = await port_forwarding_rules(router)
    clash = [
        r
        for r in current
        if r.port_external == rule.port_external and r.protocol == rule.protocol
    ]
    if clash and not force:
        raise ValueError(
            f"External port {rule.port_external}/{rule.protocol} is already "
            f"forwarded to {clash[0].ip_address}:{clash[0].port}. "
            "Use --force to add anyway."
        )

    # Build the full list ourselves and apply it in one write. The whole
    # rule list is a single nvram string, so this is read-modify-write.
    applied = await router.async_apply_port_forwarding_rules([*current, rule])
    data = await router.async_get_data(AsusData.PORT_FORWARDING, force=True) or {}
    return {
        "applied": applied,
        "rule": rule,
        "clash": clash,
        "global_state": data.get("state"),
    }


async def port_forward_remove(
    router: Any,
    name: str | None = None,
    port: int | None = None,
    proto: str | None = None,
) -> dict[str, Any]:
    current = await port_forwarding_rules(router)
    doomed = [r for r in current if _pf_matches(r, name, port, proto)]
    if not doomed:
        raise ValueError("No matching rule.")

    keep = [r for r in current if r not in doomed]
    applied = await router.async_apply_port_forwarding_rules(keep)
    return {"applied": applied, "removed": doomed}


async def set_port_forwarding(router: Any, enabled: bool) -> dict[str, Any]:
    target = AsusPortForwarding.ON if enabled else AsusPortForwarding.OFF
    applied = await router.async_set_state(target)
    return {"applied": applied}


async def set_parental_control(router: Any, enabled: bool) -> dict[str, Any]:
    target = AsusParentalControl.ON if enabled else AsusParentalControl.OFF
    applied = await router.async_set_state(target)
    return {"applied": applied}


async def set_guest_network(router: Any, band: str, index: int, enabled: bool) -> dict[str, Any]:
    # api_id is "<band index>.<guest index>" and becomes wl<api_id>_bss_enabled
    # (asusrouter/modules/wlan.py::set_state).
    api_id = f"{BANDS[band]}.{index}"
    target = AsusWLAN.ON if enabled else AsusWLAN.OFF
    applied = await router.async_set_state(target, api_type="gwlan", api_id=api_id)
    return {"applied": applied}


async def set_wps(router: Any, enabled: bool) -> dict[str, Any]:
    value = "1" if enabled else "0"
    # wps_enable_x is what the web UI writes and wps_enable is the runtime
    # flag; both are present on RT-AX59U and both are set here so the UI
    # and the radio agree afterwards.
    return await apply_nvram(
        router,
        {"wps_enable": value, "wps_enable_x": value, "wps_multiband": value},
        "restart_wireless",
    )


async def set_wifi_security(
    router: Any, band: str, mode: str, mfp: str | None = None
) -> dict[str, Any]:
    auth, default_mfp = WPA_MODES[mode]
    mfp_value = MFP_VALUES[mfp] if mfp else default_mfp

    values: dict[str, str] = {}
    for i in _bands(band):
        values[f"wl{i}_auth_mode_x"] = auth
        values[f"wl{i}_crypto"] = "aes"
        values[f"wl{i}_mfp"] = mfp_value

    return await apply_nvram(router, values, "restart_wireless")


async def set_wifi_country(router: Any, band: str, code: str) -> dict[str, Any]:
    values = {f"wl{i}_country_code": code for i in _bands(band)}
    return await apply_nvram(router, values, "restart_wireless")


async def reboot(router: Any) -> dict[str, Any]:
    applied = await router.async_set_state(AsusSystem.REBOOT)
    return {"requested": applied}


async def _apply_firmware_upgrade(router: Any) -> None:
    """Ask the router to flash whatever it already agreed is on offer.

    async_set_state only reports whether the request was accepted, never
    whether the download or the flash itself succeeds.
    """
    if not await router.async_set_state(AsusSystem.FIRMWARE_UPGRADE):
        raise ValueError("FAILED: the router refused the upgrade request")


async def firmware_upgrade(
    router: Any, wait: float, to: str | None, beta: bool = False
) -> dict[str, Any]:
    """Download and flash a new firmware. Self-contained: one fetch, then apply.

    `to` is the exact version the caller expects to be offered; when given
    and it does not match, this refuses rather than flash a surprise version.
    """
    payload = await firmware(router, wait)
    current, latest = _resolve_upgrade_target(payload, beta)

    if to is not None and to != latest:
        raise ValueError(
            "--to does not match what the router is offering.\n"
            f"  requested  {to}\n"
            f"  offered    {latest}"
        )

    await _apply_firmware_upgrade(router)
    return {"requested": True, "current": current, "latest": latest}
