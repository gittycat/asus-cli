"""Mutations with --confirm: the exact payload sent, and the exit code."""

from __future__ import annotations

import json

import pytest

from asusrouter.modules.parental_control import AsusParentalControl
from asusrouter.modules.port_forwarding import AsusPortForwarding
from asusrouter.modules.system import AsusSystem
from asusrouter.modules.wlan import AsusWLAN

from asus_cli import cli
from helpers import FakeRouter, invoke


def only_service(router: FakeRouter) -> tuple[str, dict]:
    assert len(router.services) == 1, router.services
    return router.services[0]


# -- wifi wps --------------------------------------------------------------


def test_wps_disable_writes_all_three_flags(router):
    result = invoke(router, "wifi", "wps", "disable", "--yes")

    assert result.code == 0
    service, arguments = only_service(router)
    assert service == "restart_wireless"
    assert arguments == {
        "wps_enable": "0",
        "wps_enable_x": "0",
        "wps_multiband": "0",
    }


def test_wps_enable_writes_ones(router):
    router.nvram.update({"wps_enable": "0", "wps_enable_x": "0", "wps_multiband": "0"})
    invoke(router, "wifi", "wps", "enable", "--yes")
    assert only_service(router)[1] == {
        "wps_enable": "1",
        "wps_enable_x": "1",
        "wps_multiband": "1",
    }


def test_wps_disable_reports_before_and_after(router):
    out = invoke(router, "wifi", "wps", "disable", "--yes").out
    assert "Applied: turn WPS OFF on all bands" in out
    assert "wps_enable             '1' -> '0'" in out
    assert "wps_enable_x           '1' -> '0'" in out
    assert "wps_multiband          '1' -> '0'" in out


def test_wps_disable_leaves_the_router_with_wps_off(router):
    invoke(router, "wifi", "wps", "disable", "--yes")
    assert invoke(router, "wifi", "show").out.startswith("WPS               OFF")


# -- wifi security ---------------------------------------------------------


@pytest.mark.parametrize(
    ("mode", "auth", "mfp"),
    [("wpa2", "psk2", "0"), ("wpa2wpa3", "psk2sae", "1"), ("wpa3", "sae", "2")],
)
def test_security_modes_map_to_auth_and_frame_protection(router, mode, auth, mfp):
    invoke(router, "wifi", "security", "--mode", mode, "--yes")

    service, arguments = only_service(router)
    assert service == "restart_wireless"
    assert arguments == {
        "wl0_auth_mode_x": auth,
        "wl0_crypto": "aes",
        "wl0_mfp": mfp,
        "wl1_auth_mode_x": auth,
        "wl1_crypto": "aes",
        "wl1_mfp": mfp,
    }


@pytest.mark.parametrize(("band", "index"), [("2ghz", 0), ("5ghz", 1)])
def test_security_can_target_one_band(router, band, index):
    invoke(router, "wifi", "security", "--band", band, "--mode", "wpa3", "--yes")

    arguments = only_service(router)[1]
    other = 1 - index
    assert f"wl{index}_auth_mode_x" in arguments
    assert f"wl{other}_auth_mode_x" not in arguments


def test_security_mfp_override_beats_the_mode_default(router):
    invoke(
        router,
        "wifi", "security", "--band", "2ghz", "--mode", "wpa3",
        "--mfp", "disabled", "--yes",
    )
    assert only_service(router)[1]["wl0_mfp"] == "0"


def test_security_always_sets_an_aes_cipher(router):
    invoke(router, "wifi", "security", "--mode", "wpa2", "--yes")
    arguments = only_service(router)[1]
    assert arguments["wl0_crypto"] == "aes"
    assert arguments["wl1_crypto"] == "aes"


# -- wifi country ----------------------------------------------------------

def test_country_writes_only_the_named_band(router):
    invoke(router, "wifi", "country", "--band", "5ghz", "--code", "AU", "--yes")
    assert only_service(router)[1] == {"wl1_country_code": "AU"}


def test_country_code_is_upper_cased(router):
    invoke(router, "wifi", "country", "--band", "5ghz", "--code", "au", "--yes")
    assert only_service(router)[1] == {"wl1_country_code": "AU"}


def test_country_write_that_does_not_stick_is_a_failure():
    """Stock firmware accepts the write and ignores it. That is not success."""
    router = FakeRouter(apply_writes=False)
    result = invoke(
        router, "wifi", "country", "--band", "5ghz", "--code", "AU", "--yes"
    )

    assert result.code == cli.EXIT_ERROR
    assert "Did not take the requested value: wl1_country_code" in result.out
    assert "locked to the hardware SKU" in result.err


def test_a_value_that_was_already_correct_reads_as_already_set(router):
    """crypto is normally already aes; that is a success, not a refusal."""
    result = invoke(router, "wifi", "security", "--mode", "wpa2wpa3", "--yes")

    assert result.code == 0
    assert "wl0_crypto             'aes' -> 'aes'  (already set)" in result.out
    assert "REFUSED" not in result.out


def test_country_write_that_sticks_is_a_success(router):
    result = invoke(
        router, "wifi", "country", "--band", "5ghz", "--code", "AU", "--yes"
    )
    assert result.code == 0
    assert "'AA' -> 'AU'" in result.out
    assert result.err == ""


def test_a_refused_wifi_write_is_reported_even_when_the_service_ran():
    """async_run_service returning True only means the request was accepted."""
    router = FakeRouter(apply_writes=False, service_ok=True)
    result = invoke(router, "wifi", "wps", "disable", "--yes")

    assert result.code == cli.EXIT_ERROR
    assert "(REFUSED)" in result.out
    assert "(already set)" not in result.out  # refused is not "already correct"
    assert "The firmware is refusing the write" in result.out


def test_wifi_write_json_carries_before_after_and_unchanged():
    router = FakeRouter(apply_writes=False)
    payload = json.loads(
        invoke(router, "--json", "wifi", "wps", "disable", "--yes").out
    )
    assert payload["ok"] is True
    assert payload["before"]["wps_enable"] == "1"
    assert payload["after"]["wps_enable"] == "1"
    assert set(payload["unchanged"]) == {
        "wps_enable",
        "wps_enable_x",
        "wps_multiband",
    }


# -- port forwarding -------------------------------------------------------


def test_pf_add_appends_to_the_existing_rules(pf_router):
    result = invoke(
        pf_router,
        "pf", "add", "--name", "Game", "--port", "27015",
        "--to-ip", "192.168.50.40", "--yes",
    )

    assert result.code == 0
    assert [r.name for r in pf_router.applied_pf_rules] == ["Plex", "Web", "Game"]
    added = pf_router.applied_pf_rules[-1]
    assert added.port_external == "27015"
    assert added.port == "27015"  # internal defaults to the external port
    assert added.protocol == "TCP"


def test_pf_add_uses_a_distinct_internal_port_when_given(pf_router):
    invoke(
        pf_router,
        "pf", "add", "--name", "Alt", "--port", "8443",
        "--to-ip", "192.168.50.40", "--to-port", "443", "--yes",
    )
    added = pf_router.applied_pf_rules[-1]
    assert (added.port_external, added.port) == ("8443", "443")


def test_pf_add_refuses_a_duplicate_external_port(pf_router):
    result = invoke(
        pf_router,
        "pf", "add", "--name", "Plex2", "--port", "32400",
        "--to-ip", "192.168.50.99", "--yes",
    )

    assert result.code == cli.EXIT_ERROR
    assert "already" in result.err
    assert pf_router.applied_pf_rules is None


def test_pf_add_force_allows_the_duplicate(pf_router):
    result = invoke(
        pf_router,
        "pf", "add", "--name", "Plex2", "--port", "32400",
        "--to-ip", "192.168.50.99", "--force", "--yes",
    )
    assert result.code == 0
    assert len(pf_router.applied_pf_rules) == 3


def test_pf_add_warns_when_the_global_switch_is_off(router):
    """A rule on a router with forwarding OFF exists but does nothing."""
    result = invoke(
        router,
        "pf", "add", "--name", "Plex", "--port", "32400",
        "--to-ip", "192.168.50.20", "--yes",
    )
    assert result.code == 0
    assert "port forwarding is globally OFF" in result.out


def test_pf_remove_by_name_keeps_the_others(pf_router):
    result = invoke(pf_router, "pf", "remove", "--name", "Plex", "--yes")
    assert result.code == 0
    assert [r.name for r in pf_router.applied_pf_rules] == ["Web"]


def test_pf_remove_by_external_port(pf_router):
    invoke(pf_router, "pf", "remove", "--port", "8080", "--yes")
    assert [r.name for r in pf_router.applied_pf_rules] == ["Plex"]


@pytest.mark.parametrize(
    ("action", "expected"),
    [("enable", AsusPortForwarding.ON), ("disable", AsusPortForwarding.OFF)],
)
def test_pf_global_switch(router, action, expected):
    result = invoke(router, "pf", action, "--yes")
    assert result.code == 0
    assert router.states == [(expected, {})]


# -- guest / parental / reboot ---------------------------------------------


@pytest.mark.parametrize(
    ("band", "guest_id", "api_id"),
    [("2ghz", 1, "0.1"), ("5ghz", 3, "1.3")],
)
def test_guest_enable_targets_the_right_bss(router, band, guest_id, api_id):
    result = invoke(
        router, "guest", "enable", "--band", band, "--id", str(guest_id), "--yes"
    )

    assert result.code == 0
    state, kwargs = router.states[0]
    assert state is AsusWLAN.ON
    assert kwargs == {"api_type": "gwlan", "api_id": api_id}


def test_guest_disable_sends_off(router):
    invoke(router, "guest", "disable", "--band", "5ghz", "--id", "1", "--yes")
    assert router.states[0][0] is AsusWLAN.OFF


@pytest.mark.parametrize(
    ("action", "expected"),
    [("enable", AsusParentalControl.ON), ("disable", AsusParentalControl.OFF)],
)
def test_parental_switch(router, action, expected):
    result = invoke(router, "parental", action, "--yes")
    assert result.code == 0
    assert router.states == [(expected, {})]


def test_reboot_asks_for_the_reboot_state(router):
    result = invoke(router, "reboot", "--yes")
    assert result.code == 0
    assert router.states == [(AsusSystem.REBOOT, {})]
    assert "Reboot requested" in result.out


# -- failure propagation ---------------------------------------------------


@pytest.mark.parametrize(
    "argv",
    [
        ("pf", "enable", "--yes"),
        ("parental", "enable", "--yes"),
        ("guest", "enable", "--band", "2ghz", "--id", "1", "--yes"),
        ("reboot", "--yes"),
    ],
    ids=lambda a: " ".join(a),
)
def test_a_refused_service_call_exits_nonzero(argv):
    router = FakeRouter(service_ok=False)
    result = invoke(router, *argv)
    assert result.code == cli.EXIT_ERROR
    assert "FAILED" in result.out
