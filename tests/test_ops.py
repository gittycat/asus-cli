"""ops.py: every domain operation against FakeRouter.

Each function is exercised once, mostly just enough to prove the payload
comes back with the keys the CLI (and later the MCP boundary) rely on, and
that it survives `jsonable()` + `json.dumps` even though `ops` itself never
calls `jsonable` — the payload contract is that the *caller* converts.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from asusrouter import AsusData
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule

from asuswrt import ops
from asuswrt.router import jsonable
from helpers import FakeRouter, default_data

OFFERED = "3.0.0.4.388.34098_g9b0c9ae"


def run(coro):
    return asyncio.run(coro)


def as_json(payload) -> dict:
    """The payload contract: ops returns raw objects; the caller jsonifies."""
    return json.loads(json.dumps(jsonable(payload), default=str))


def pf_router() -> FakeRouter:
    data = default_data()
    data[AsusData.PORT_FORWARDING] = {
        "state": AsusPortForwarding.ON,
        "rules": [
            PortForwardingRule(
                name="Plex", ip_address="192.168.50.20", port="32400",
                protocol="TCP", ip_external="", port_external="32400",
            ),
            PortForwardingRule(
                name="Web", ip_address="192.168.50.30", port="80",
                protocol="TCP", ip_external="", port_external="8080",
            ),
        ],
    }
    return FakeRouter(data=data)


# -- reads -------------------------------------------------------------------


def test_system():
    payload = run(ops.system(FakeRouter()))
    as_json(payload)
    assert set(payload) == {
        "model", "product_id", "firmware", "merlin", "mac", "serial",
        "aimesh", "services",
    }


def test_health():
    payload = run(ops.health(FakeRouter(), 0))
    as_json(payload)
    assert set(payload) == {
        "uptime_hours", "cpu_usage", "cpu_cores", "ram", "wan_link", "wan_ip",
    }


def test_wan():
    payload = run(ops.wan(FakeRouter()))
    as_json(payload)
    assert "internet" in payload


def test_clients():
    rows = run(ops.clients(FakeRouter()))
    as_json(rows)
    assert rows
    for row in rows:
        assert set(row) == {"mac", "name", "vendor", "ip", "type", "guest", "online"}


def test_clients_online_only():
    all_rows = run(ops.clients(FakeRouter()))
    online_rows = run(ops.clients(FakeRouter(), online_only=True))
    assert len(online_rows) < len(all_rows)
    assert all(r["online"] for r in online_rows)


def test_firewall():
    payload = run(ops.firewall(FakeRouter()))
    as_json(payload)
    assert set(payload) == {"nvram", "parental_control"}


def test_parental():
    payload = run(ops.parental(FakeRouter()))
    as_json(payload)
    assert {"state", "block_all", "rules"} <= set(payload)


def test_port_forwarding():
    payload = run(ops.port_forwarding(pf_router()))
    as_json(payload)
    assert set(payload) == {"state", "rules"}
    assert [r.name for r in payload["rules"]] == ["Plex", "Web"]


def test_guest():
    payload = run(ops.guest(FakeRouter()))
    as_json(payload)
    assert payload


def test_wifi():
    payload = run(ops.wifi(FakeRouter()))
    as_json(payload)
    assert "wl0_mfp" in payload


def test_firmware():
    payload = run(ops.firmware(FakeRouter(), 0))
    as_json(payload)
    assert payload["status"] == "update"
    assert payload["latest"] == OFFERED


def test_nvram():
    payload = run(ops.nvram(FakeRouter(), ["wl0_mfp", "wl1_mfp"]))
    as_json(payload)
    assert payload == {"wl0_mfp": "0", "wl1_mfp": "0"}


def test_overview():
    payload = run(ops.overview(FakeRouter(), 0, False, 0))
    as_json(payload)
    assert set(payload) == {
        "system", "health", "wan", "clients", "firewall", "parental",
        "port_forwarding", "guest", "wifi",
    }
    assert set(payload["clients"]) == {"online", "known"}


def test_overview_with_firmware():
    payload = run(ops.overview(FakeRouter(), 0, True, 0))
    as_json(payload)
    assert "firmware" in payload


# -- writes --------------------------------------------------------------


def test_port_forward_add():
    router = pf_router()
    rule = PortForwardingRule(
        name="Game", ip_address="192.168.50.40", port="27015",
        protocol="TCP", ip_external="", port_external="27015",
    )
    result = run(ops.port_forward_add(router, rule))
    as_json(result)
    assert set(result) == {"applied", "rule", "clash", "global_state"}
    assert result["applied"] is True
    assert [r.name for r in router.applied_pf_rules] == ["Plex", "Web", "Game"]


def test_port_forward_add_refuses_a_clash():
    router = pf_router()
    rule = PortForwardingRule(
        name="Plex2", ip_address="192.168.50.99", port="32400",
        protocol="TCP", ip_external="", port_external="32400",
    )
    with pytest.raises(ValueError, match="already"):
        run(ops.port_forward_add(router, rule))
    assert router.applied_pf_rules is None


def test_port_forward_remove():
    router = pf_router()
    result = run(ops.port_forward_remove(router, name="Plex"))
    as_json(result)
    assert set(result) == {"applied", "removed"}
    assert [r.name for r in router.applied_pf_rules] == ["Web"]


def test_port_forward_remove_refuses_no_match():
    with pytest.raises(ValueError, match="No matching rule"):
        run(ops.port_forward_remove(FakeRouter(), name="Nope"))


def test_set_port_forwarding():
    router = FakeRouter()
    result = run(ops.set_port_forwarding(router, True))
    as_json(result)
    assert result == {"applied": True}
    assert router.states == [(AsusPortForwarding.ON, {})]


def test_set_parental_control():
    router = FakeRouter()
    result = run(ops.set_parental_control(router, False))
    as_json(result)
    assert result == {"applied": True}


def test_set_guest_network():
    router = FakeRouter()
    result = run(ops.set_guest_network(router, "5ghz", 1, True))
    as_json(result)
    assert result == {"applied": True}
    state, kwargs = router.states[0]
    assert kwargs == {"api_type": "gwlan", "api_id": "1.1"}


def test_set_wps():
    router = FakeRouter()
    result = run(ops.set_wps(router, False))
    as_json(result)
    assert set(result) == {"ok", "before", "after", "unchanged"}
    assert router.services == [
        ("restart_wireless", {"wps_enable": "0", "wps_enable_x": "0", "wps_multiband": "0"})
    ]


def test_set_wifi_security():
    router = FakeRouter()
    result = run(ops.set_wifi_security(router, "both", "wpa2wpa3"))
    as_json(result)
    assert set(result) == {"ok", "before", "after", "unchanged"}
    assert router.services[0][1]["wl0_auth_mode_x"] == "psk2sae"


def test_set_wifi_country():
    router = FakeRouter()
    result = run(ops.set_wifi_country(router, "5ghz", "AU"))
    as_json(result)
    assert router.services == [("restart_wireless", {"wl1_country_code": "AU"})]


def test_reboot():
    router = FakeRouter()
    result = run(ops.reboot(router))
    as_json(result)
    assert result == {"requested": True}
    assert router.states == [(ops.AsusSystem.REBOOT, {})]


def test_firmware_upgrade():
    router = FakeRouter()
    result = run(ops.firmware_upgrade(router, 0, OFFERED))
    as_json(result)
    assert set(result) == {"requested", "current", "latest"}
    assert result["latest"] == OFFERED
    from asusrouter.modules.system import AsusSystem
    assert AsusSystem.FIRMWARE_UPGRADE in [s for s, _ in router.states]


def test_firmware_upgrade_refuses_a_mismatched_to():
    with pytest.raises(ValueError, match="does not match"):
        run(ops.firmware_upgrade(FakeRouter(), 0, "9.9.9"))


def test_firmware_upgrade_refuses_when_up_to_date():
    data = default_data()
    data[AsusData.FIRMWARE] = {**data[AsusData.FIRMWARE], "state": False, "available": None}
    with pytest.raises(ValueError, match="up to date"):
        run(ops.firmware_upgrade(FakeRouter(data=data), 0, None))


# -- dns -------------------------------------------------------------------


def test_dns_read_reports_the_unit_and_both_sides():
    payload = as_json(run(ops.dns(FakeRouter())))
    assert payload["unit"] == 0
    raw = payload["nvram"]
    assert raw["wan0_dns1_x"] == "1.1.1.1"
    assert raw["wan0_dnsenable_x"] == "0"
    # The LAN-side and validation settings come back in the same read.
    assert set(ops.DNS_VARS) <= set(raw)


def test_dns_read_follows_the_active_wan_unit():
    """wan1_* after a failover, not wan0_* — the names are keyed by unit."""
    data = default_data()
    data[AsusData.WAN] = {**data[AsusData.WAN], "internet": {"unit": 1}}
    router = FakeRouter(data=data)
    router.nvram["wan1_dns1_x"] = "9.9.9.9"

    payload = run(ops.dns(router))
    assert payload["unit"] == 1
    assert payload["nvram"]["wan1_dns1_x"] == "9.9.9.9"


def test_dns_read_defaults_to_unit_0_when_the_router_says_nothing():
    data = default_data()
    data[AsusData.WAN] = {}
    assert run(ops.dns(FakeRouter(data=data)))["unit"] == 0


def test_set_dns_writes_manual_servers_and_restarts_wan_dns():
    router = FakeRouter()
    result = run(ops.set_dns(router, "8.8.8.8", "8.8.4.4"))
    as_json(result)

    assert result["unit"] == 0 and result["automatic"] is False
    assert not result["unchanged"]
    assert router.services == [
        (
            "restart_wan_dns 0",
            {
                "wan0_dnsenable_x": "0",
                "wan0_dns1_x": "8.8.8.8",
                "wan0_dns2_x": "8.8.4.4",
            },
        )
    ]


def test_set_dns_clears_the_second_server_when_only_one_is_given():
    router = FakeRouter()
    run(ops.set_dns(router, "8.8.8.8"))
    assert router.services[0][1]["wan0_dns2_x"] == ""


def test_set_dns_automatic_touches_only_the_enable_flag():
    """The stored pair survives, the way the web UI leaves it."""
    router = FakeRouter()
    run(ops.set_dns(router, automatic=True))

    assert router.services == [("restart_wan_dns 0", {"wan0_dnsenable_x": "1"})]
    assert router.nvram["wan0_dns1_x"] == "1.1.1.1"


def test_set_dns_writes_the_active_unit_not_wan0():
    data = default_data()
    data[AsusData.WAN] = {**data[AsusData.WAN], "internet": {"unit": 1}}
    router = FakeRouter(data=data)

    run(ops.set_dns(router, "8.8.8.8"))
    service, arguments = router.services[0]
    # The unit is part of the service string too, not only the variable names.
    assert service == "restart_wan_dns 1"
    assert set(arguments) == {"wan1_dnsenable_x", "wan1_dns1_x", "wan1_dns2_x"}


def test_set_dns_refuses_ipv6_and_names_the_field_it_belongs_in():
    with pytest.raises(ValueError, match="ipv6_dns1_x"):
        run(ops.set_dns(FakeRouter(), "2001:4860:4860::8888"))


def test_set_dns_refuses_a_non_address():
    with pytest.raises(ValueError, match="not an IP address"):
        run(ops.set_dns(FakeRouter(), "dns.google"))


def test_set_dns_refuses_automatic_together_with_servers():
    with pytest.raises(ValueError, match="not both"):
        run(ops.set_dns(FakeRouter(), "8.8.8.8", automatic=True))


def test_set_dns_refuses_neither_automatic_nor_a_server():
    with pytest.raises(ValueError, match="automatic"):
        run(ops.set_dns(FakeRouter()))


def test_set_dns_refuses_a_second_server_without_a_first():
    with pytest.raises(ValueError, match="Give a first DNS server"):
        run(ops.set_dns(FakeRouter(), server2="8.8.4.4"))


def test_set_dns_reports_a_write_the_firmware_ignored():
    router = FakeRouter(apply_writes=False)
    result = run(ops.set_dns(router, "8.8.8.8"))
    assert "wan0_dns1_x" in result["unchanged"]


# -- led -------------------------------------------------------------------


def test_led_read():
    assert run(ops.led(FakeRouter()))["led_val"] == "1"


def test_set_led_off_writes_led_val_through_start_ctrl_led():
    router = FakeRouter()
    result = run(ops.set_led(router, False))
    as_json(result)

    assert result["ok"] and not result["unchanged"]
    assert router.services == [("start_ctrl_led", {"led_val": "0"})]


def test_set_led_succeeds_against_a_service_that_reports_no_modify_flag():
    """The reason apply_nvram takes expect_modify.

    start_ctrl_led returns no `modify`, which the library reads as False. With
    the default expect_modify=True a perfectly good write would report FAILED.
    """
    router = FakeRouter(returns_modify=False)
    assert run(ops.set_led(router, False))["ok"] is True

    # And the contrast: a write that does expect the flag sees the refusal.
    assert run(ops.set_wps(FakeRouter(returns_modify=False), False))["ok"] is False


def test_set_led_reports_a_write_the_firmware_ignored():
    router = FakeRouter(apply_writes=False)
    result = run(ops.set_led(router, False))
    assert result["unchanged"] == ["led_val"]


# -- upnp ------------------------------------------------------------------


def test_upnp_read_is_off_when_every_switch_is_off():
    payload = as_json(run(ops.upnp(FakeRouter())))
    assert payload["enabled"] is False
    assert payload["unit"] == 0


def test_upnp_read_is_on_when_any_single_switch_is_on():
    """One `1` anywhere means miniupnpd is listening, so the summary must not
    be cheerier than the raw values."""
    for name in ("upnp_enable", "wan_upnp_enable", "wan0_upnp_enable"):
        router = FakeRouter()
        router.nvram[name] = "1"
        assert run(ops.upnp(router))["enabled"] is True, name


def test_set_upnp_disable_writes_all_three_switches():
    router = FakeRouter()
    router.nvram.update({"upnp_enable": "1", "wan_upnp_enable": "1", "wan0_upnp_enable": "1"})

    result = run(ops.set_upnp(router, False))
    as_json(result)

    assert not result["unchanged"]
    assert router.services == [
        (
            "restart_upnp",
            {"upnp_enable": "0", "wan_upnp_enable": "0", "wan0_upnp_enable": "0"},
        )
    ]
    assert run(ops.upnp(router))["enabled"] is False


def test_set_upnp_follows_the_active_wan_unit():
    data = default_data()
    data[AsusData.WAN] = {**data[AsusData.WAN], "internet": {"unit": 1}}
    router = FakeRouter(data=data)

    run(ops.set_upnp(router, False))
    assert "wan1_upnp_enable" in router.services[0][1]
    assert "wan0_upnp_enable" not in router.services[0][1]


def test_set_upnp_reports_a_write_the_firmware_ignored():
    router = FakeRouter(apply_writes=False)
    router.nvram["upnp_enable"] = "1"
    assert "upnp_enable" in run(ops.set_upnp(router, False))["unchanged"]
