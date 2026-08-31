"""The read commands: correct numbers, correct shapes, no writes."""

from __future__ import annotations

import json

import pytest

from asusrouter import AsusData

from helpers import DEFAULT_NVRAM, FakeRouter, default_data, invoke

# Every reading, under its canonical name. `firmware` is absent on purpose:
# it is the one read that has to poke the router (it makes it query ASUS), so
# it cannot assert "wrote nothing" and lives in test_firmware.py instead.
READ_COMMANDS = [
    ("show", "--cpu-sample", "0"),
    ("system",),
    ("system", "show"),
    ("system", "health", "--cpu-sample", "0"),
    ("clients",),
    ("clients", "show"),
    ("clients", "--online"),
    ("wan",),
    ("wan", "show"),
    ("firewall",),
    ("firewall", "show"),
    ("parental",),
    ("parental", "show"),
    ("portforward",),
    ("portforward", "show"),
    ("guest",),
    ("guest", "show"),
    ("wifi",),
    ("wifi", "show"),
    ("nvram", "get", "wl0_radio"),
]

# The names that existed before the tree was regularised. They are hidden from
# --help but must keep producing the same reading.
LEGACY_COMMANDS = [
    ("info",),
    ("status", "--cpu-sample", "0"),
    ("pf", "list"),
    ("guest", "list"),
    ("nvram", "wl0_radio"),
]


@pytest.mark.parametrize("argv", READ_COMMANDS, ids=lambda a: " ".join(a))
def test_read_commands_succeed_and_write_nothing(router, argv):
    result = invoke(router, *argv)
    assert result.code == 0
    assert result.out.strip()
    assert not router.touched


@pytest.mark.parametrize("argv", READ_COMMANDS, ids=lambda a: " ".join(a))
def test_read_commands_emit_valid_json(router, argv):
    result = invoke(router, "--json", *argv)
    assert result.code == 0
    json.loads(result.out)


@pytest.mark.parametrize("argv", LEGACY_COMMANDS, ids=lambda a: " ".join(a))
def test_legacy_names_still_read(router, argv):
    result = invoke(router, *argv)
    assert result.code == 0
    assert result.out.strip()
    assert not router.touched


# -- info / status ---------------------------------------------------------


def test_system_show_reports_identity(router):
    lines = invoke(router, "system", "show").lines
    assert "RT-AX59U" in lines[0]
    assert "3.0.0.4.388.34011" in lines[1]
    assert "merlin=False" in lines[1]


def test_system_show_holds_nothing_that_moves(router):
    """`show` is what does not change until a reboot; live values are `health`."""
    out = invoke(router, "system", "show").out
    assert "Uptime" not in out
    assert "CPU" not in out
    assert "RAM" not in out


def test_system_health_reports_uptime(router):
    # 3 d 4 h of uptime seconds in the fixture.
    lines = invoke(router, "system", "health", "--cpu-sample", "0").lines
    assert "3 d 4 h" in [line for line in lines if line.startswith("Uptime")][0]


def test_system_health_reports_cpu_ram_and_wan(router):
    out = invoke(router, "system", "health", "--cpu-sample", "0").out
    assert "3.5% over 2 cores" in out
    assert "53.0%" in out
    assert "(271 / 512 MB)" in out
    assert "CONNECTED  ip=203.0.113.4" in out


def test_status_samples_cpu_twice(router):
    """Usage is a delta, so a single fetch would always report None."""
    calls: list[tuple] = []
    original = router.async_get_data

    async def counting(datatype, force=False):
        calls.append((datatype, force))
        return await original(datatype, force)

    router.async_get_data = counting
    invoke(router, "status", "--cpu-sample", "0")
    assert [c for c in calls if c[0] is AsusData.CPU] == [
        (AsusData.CPU, False),
        (AsusData.CPU, True),
    ]


def test_status_survives_a_router_that_reports_no_cpu_usage():
    data = default_data()
    data[AsusData.CPU] = {"total": {"usage": None}}
    result = invoke(FakeRouter(data=data), "status", "--cpu-sample", "0")
    assert result.code == 0
    assert "CPU        unavailable" in result.out


# -- clients ---------------------------------------------------------------


def test_clients_lists_everything_with_online_last(router):
    result = invoke(router, "clients")
    assert "2 online / 3 listed" in result.out
    # Offline devices sort after online ones.
    names = [line.split()[0] for line in result.lines[1:] if line.strip()]
    assert names.index("Old") > names.index("iPad")


def test_clients_online_filter_drops_the_offline_device(router):
    result = invoke(router, "clients", "--online")
    assert "Old Laptop" not in result.out
    assert "2 online / 2 listed" in result.out


def test_clients_json_exposes_the_fields_an_agent_filters_on(router):
    rows = json.loads(invoke(router, "--json", "clients").out)
    assert {r["name"] for r in rows} == {"iPad", "Brother Printer", "Old Laptop"}
    for row in rows:
        assert set(row) >= {"mac", "name", "vendor", "ip", "type", "guest", "online"}
    ipad = next(r for r in rows if r["name"] == "iPad")
    assert ipad["online"] is True
    assert ipad["ip"] == "192.168.50.66"


# -- wan -------------------------------------------------------------------


def test_wan_reads_the_nested_structure(router):
    out = invoke(router, "wan").out
    assert "Link       CONNECTED" in out
    assert "IP         203.0.113.4" in out
    assert "Gateway    203.0.113.1" in out
    assert "1.1.1.1" in out


# -- firewall --------------------------------------------------------------


def test_firewall_renders_flags_and_counts(router):
    out = invoke(router, "firewall").out
    assert "Firewall          ON" in out
    assert "DoS protection    OFF" in out
    assert "WAN web access    OFF" in out
    assert "URL filter        OFF (0 entries)" in out
    assert "Parental control  ON (0 rules, block_all=OFF)" in out


def test_firewall_shows_the_raw_value_when_it_is_not_a_boolean(router):
    """fw_log_x is the string "none" on real hardware, not 0 or 1."""
    assert "Logging           ? ('none')" in invoke(router, "firewall").out


def test_firewall_counts_filter_entries():
    nvram = dict(DEFAULT_NVRAM)
    nvram["url_enable_x"] = "1"
    nvram["url_rulelist"] = "&#60example.com&#60tracker.net"
    out = invoke(FakeRouter(nvram=nvram), "firewall").out
    assert "URL filter        ON (2 entries)" in out


# -- port forwarding -------------------------------------------------------


def test_pf_list_handles_a_router_with_no_rules_key(router):
    """The library omits "rules" entirely when the list is empty."""
    result = invoke(router, "pf", "list")
    assert result.code == 0
    assert "Port forwarding is OFF (0 rule(s))" in result.out


def test_pf_list_renders_rules(pf_router):
    out = invoke(pf_router, "pf", "list").out
    assert "Port forwarding is ON (2 rule(s))" in out
    assert "Plex" in out
    assert "192.168.50.20:32400" in out
    assert "192.168.50.30:80" in out


def test_pf_list_json_serialises_the_rule_dataclass(pf_router):
    payload = json.loads(invoke(pf_router, "--json", "pf", "list").out)
    assert payload["state"] == "ON"
    assert payload["rules"][0]["name"] == "Plex"
    assert payload["rules"][0]["port_external"] == "32400"


# -- guest -----------------------------------------------------------------


def test_guest_list_shows_state_and_ssid(router):
    out = invoke(router, "guest", "list").out
    assert "2ghz_1       OFF      ASUS_CC_2G_Guest" in out
    assert "5ghz_1       ON       ASUS_CC_5G_Guest" in out


# -- wifi show -------------------------------------------------------------


def test_wifi_show_reports_wps_and_both_bands(router):
    out = invoke(router, "wifi", "show").out
    assert "WPS               ON" in out
    assert "wps_enable='1'" in out
    assert "multiband='1'" in out
    assert "2ghz     ON      psk2       aes      disabled   US" in out
    assert "5ghz     ON      psk2       aes      disabled   AA" in out


def test_wifi_show_names_the_mfp_level():
    nvram = dict(DEFAULT_NVRAM)
    nvram["wl0_mfp"] = "1"
    nvram["wl1_mfp"] = "2"
    out = invoke(FakeRouter(nvram=nvram), "wifi", "show").out
    assert "capable" in out
    assert "required" in out


def test_wifi_show_keeps_an_unknown_mfp_value_visible():
    nvram = dict(DEFAULT_NVRAM)
    nvram["wl0_mfp"] = "7"
    assert " 7 " in invoke(FakeRouter(nvram=nvram), "wifi", "show").out


# -- nvram -----------------------------------------------------------------


def test_nvram_reads_the_names_it_was_given(router):
    out = invoke(router, "nvram", "wl0_country_code", "wl1_country_code").out
    assert "wl0_country_code" in out
    assert "'US'" in out
    assert "'AA'" in out
    assert "wl0_radio" not in out


def test_nvram_json_is_a_flat_mapping(router):
    payload = json.loads(invoke(router, "--json", "nvram", "wl0_mfp").out)
    assert payload == {"wl0_mfp": "0"}
