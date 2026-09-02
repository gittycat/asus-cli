"""Test doubles and the CLI invocation helper.

The tests drive the CLI end to end — argv through argparse through the command
function to stdout. Only the AsusRouter object is replaced. `read_nvram`,
`apply_nvram`, the formatting helpers and the argument parser all run for
real, so a change to any of them shows up here.

Nothing in this suite touches a real router.
"""

from __future__ import annotations

import asyncio
import contextlib
import io
import re
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any


from asusrouter import AsusData
from asusrouter.modules.connection import ConnectionState, ConnectionType
from asusrouter.modules.firmware import WebsError, WebsUpdate, WebsUpgrade
from asusrouter.modules.parental_control import AsusBlockAll, AsusParentalControl
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule

from asuswrt.cli import main as cli

# What `writers.nvram(names)` produces: "nvram_get(a);nvram_get(b);".
NVRAM_GET = re.compile(r"nvram_get\(([^)]+)\)")

# Values observed on a live RT-AX59U so the fixtures match reality, including
# the awkward ones: fw_log_x is the string "none" rather than 0/1, and the
# 5 GHz country code is the worldwide default "AA".
DEFAULT_NVRAM: dict[str, str] = {
    "fw_enable_x": "1",
    "fw_dos_x": "0",
    "fw_log_x": "none",
    "misc_http_x": "0",
    "vts_enable_x": "0",
    "url_enable_x": "0",
    "url_rulelist": "",
    "keyword_enable_x": "0",
    "keyword_rulelist": "",
    "wps_enable": "1",
    "wps_enable_x": "1",
    "wps_multiband": "1",
    "wps_band_x": "0",
    "wl0_radio": "1",
    "wl0_auth_mode_x": "psk2",
    "wl0_crypto": "aes",
    "wl0_mfp": "0",
    "wl0_country_code": "US",
    "wl1_radio": "1",
    "wl1_auth_mode_x": "psk2",
    "wl1_crypto": "aes",
    "wl1_mfp": "0",
    "wl1_country_code": "AA",
}


def _client(
    name: str,
    ip: str,
    ctype: ConnectionType,
    online: bool,
    vendor: str | None = None,
) -> SimpleNamespace:
    """A stand-in for the library's client object.

    cmd_clients reads these through getattr, and deliberately does not trust
    `client.state` — online lives on `client.connection.online`.
    """
    return SimpleNamespace(
        description=SimpleNamespace(name=name, vendor=vendor),
        connection=SimpleNamespace(
            ip_address=ip, type=ctype, online=online, guest=False
        ),
    )


def default_data() -> dict[Any, Any]:
    """The AsusData payloads, shaped the way a real router returns them."""
    return {
        AsusData.BOOTTIME: {"uptime": 3 * 86400 + 4 * 3600},
        AsusData.CPU: {
            "total": {"usage": 3.5},
            "0": {"usage": 2.0},
            "1": {"usage": 5.0},
        },
        AsusData.RAM: {"usage": 53.0, "used": 271 * 1024, "total": 512 * 1024},
        AsusData.WAN: {
            # WAN is nested: there is no top-level status or ip.
            "internet": {
                "link": ConnectionState.CONNECTED,
                "ip_address": "203.0.113.4",
                "unit": 0,
            },
            0: {
                "state": ConnectionState.CONNECTED,
                "main": {
                    "protocol": "dhcp",
                    "gateway": "203.0.113.1",
                    "dns": ["1.1.1.1", "1.0.0.1"],
                },
            },
        },
        AsusData.CLIENTS: {
            "AA:BB:CC:00:00:01": _client(
                "iPad", "192.168.50.66", ConnectionType.WLAN_5G, True
            ),
            "AA:BB:CC:00:00:02": _client(
                "Brother Printer", "192.168.50.6", ConnectionType.WLAN_2G, True
            ),
            "AA:BB:CC:00:00:03": _client(
                "Old Laptop", "192.168.50.99", ConnectionType.WIRED, False
            ),
        },
        # No "rules" key: the library omits it entirely when vts_rulelist is
        # empty, which is the shape that breaks a naive data["rules"] lookup.
        AsusData.PORT_FORWARDING: {"state": AsusPortForwarding.OFF},
        AsusData.PARENTAL_CONTROL: {
            "state": AsusParentalControl.ON,
            "block_all": AsusBlockAll.OFF,
            "rules": [],
        },
        AsusData.FIRMWARE: {
            "current": "3.0.0.4.388.34011_gfae8cb3",
            "state": True,
            "available": "3.0.0.4.388.34098_g9b0c9ae",
            "state_beta": False,
            "available_beta": None,
            "webs": {
                "update": WebsUpdate.INACTIVE,
                "upgrade": WebsUpgrade.INACTIVE,
                "error": WebsError.NONE,
                "available": "3.0.0.4.388.34098_g9b0c9ae",
                "available_beta": None,
            },
            "release_note": "Security Fixes:\n- Strengthened data handling.",
        },
        AsusData.GWLAN: {
            "2ghz_1": {"bss_enabled": False, "ssid": "ASUS_CC_2G_Guest"},
            "5ghz_1": {"bss_enabled": True, "ssid": "ASUS_CC_5G_Guest"},
        },
    }


def default_identity() -> SimpleNamespace:
    return SimpleNamespace(
        model="RT-AX59U",
        product_id="RT-AX59U",
        firmware="3.0.0.4.388.34011",
        merlin=False,
        mac="BC:FC:E7:00:00:01",
        serial="SERIAL123",
        aimesh=True,
        services=["restart_firewall", "restart_wireless"],
    )


class FakeRouter:
    """Stands in for AsusRouter.

    Records every service call and state change so a test can assert on the
    exact payload, and serves nvram reads from a mutable dict so that a write
    is visible to the read-back inside `apply_nvram`.

    `apply_writes=False` simulates the firmware accepting a write and then
    ignoring it — the country-code case that `apply_nvram` exists to catch.
    """

    def __init__(
        self,
        nvram: dict[str, str] | None = None,
        data: dict[Any, Any] | None = None,
        *,
        apply_writes: bool = True,
        service_ok: bool = True,
    ) -> None:
        self.nvram = dict(DEFAULT_NVRAM if nvram is None else nvram)
        self.data = default_data() if data is None else data
        self.identity = default_identity()
        self.apply_writes = apply_writes
        self.service_ok = service_ok

        self._initial_nvram = dict(self.nvram)
        self.services: list[tuple[str, dict[str, Any]]] = []
        self.states: list[tuple[Any, dict[str, Any]]] = []
        self.applied_pf_rules: list[PortForwardingRule] | None = None

    # -- reads -------------------------------------------------------------

    async def async_api_hook(self, request: str) -> dict[str, Any]:
        return {name: self.nvram.get(name, "") for name in NVRAM_GET.findall(request)}

    async def async_get_identity(self, force: bool = False) -> SimpleNamespace:
        return self.identity

    async def async_get_data(self, datatype: Any, force: bool = False) -> Any:
        return self.data.get(datatype)

    # -- writes ------------------------------------------------------------

    async def async_run_service(
        self,
        service: str | None,
        arguments: dict[str, Any] | None = None,
        apply: bool = False,
        expect_modify: bool = True,
        drop_connection: bool = False,
    ) -> bool:
        self.services.append((service, dict(arguments or {})))
        if self.apply_writes:
            for key, value in (arguments or {}).items():
                self.nvram[key] = str(value)
        return self.service_ok

    async def async_set_state(self, state: Any, **kwargs: Any) -> bool:
        self.states.append((state, kwargs))
        return self.service_ok

    async def async_apply_port_forwarding_rules(
        self, rules: list[PortForwardingRule]
    ) -> bool:
        self.applied_pf_rules = list(rules)
        return self.service_ok

    # -- assertions --------------------------------------------------------

    @property
    def touched(self) -> bool:
        """True if this router was written to in any way."""
        return bool(
            self.services
            or self.states
            or self.applied_pf_rules is not None
            or self.nvram != self._initial_nvram
        )


@dataclass
class Result:
    """What the CLI produced for one invocation."""

    code: int
    out: str
    err: str

    @property
    def lines(self) -> list[str]:
        return self.out.splitlines()


def invoke(router: FakeRouter, *argv: str) -> Result:
    """Run the CLI end to end against `router`, capturing output.

    Mirrors main(): parse argv, default `confirm` to True for the read-only
    commands that have no --confirm flag, then run the coroutine.
    """
    args = cli.build_parser().parse_args(list(argv))
    if not hasattr(args, "yes"):
        args.yes = True

    @contextlib.asynccontextmanager
    async def fake_connect(config: Any = None):
        yield router

    out, err = io.StringIO(), io.StringIO()
    original = cli.connect
    cli.connect = fake_connect
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = asyncio.run(args.func(args))
    finally:
        cli.connect = original
    return Result(code, out.getvalue(), err.getvalue())
