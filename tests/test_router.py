"""The router module: config loading, nvram read/write, serialisation."""

from __future__ import annotations

import asyncio

import pytest

from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule

from asus_skill import cli
from asus_skill.router import (
    ConfigError,
    RouterConfig,
    apply_nvram,
    config_paths,
    enum_name,
    jsonable,
    load_config,
    read_nvram,
)
from helpers import FakeRouter


def run(coro):
    return asyncio.run(coro)


def _empty_env(tmp_path):
    """An env file that exists but sets nothing.

    load_config stops at the first path that exists, so this keeps a real
    ./.env or ~/.config/asus-skill/.env out of the test.
    """
    path = tmp_path / "empty.env"
    path.write_text("")
    return path


# -- configuration ---------------------------------------------------------


def test_url_is_built_from_scheme_host_and_port():
    assert RouterConfig("192.168.50.1", "admin", "x", False, None).url == (
        "http://192.168.50.1"
    )
    assert RouterConfig("10.0.0.1", "admin", "x", True, 8443).url == (
        "https://10.0.0.1:8443"
    )


def test_config_paths_puts_the_override_first(monkeypatch, tmp_path):
    monkeypatch.setenv("ASUS_ENV_FILE", str(tmp_path / "custom.env"))
    assert config_paths()[0] == tmp_path / "custom.env"


def test_config_paths_without_an_override_starts_at_the_working_directory(monkeypatch):
    monkeypatch.delenv("ASUS_ENV_FILE", raising=False)
    assert config_paths()[0].name == ".env"


def test_missing_password_names_every_path_it_searched(monkeypatch, tmp_path):
    """Never ask for the password in chat — the error is the instructions."""
    env = tmp_path / "empty.env"
    env.write_text("ROUTER_HOST=192.168.50.1\n")
    monkeypatch.setenv("ASUS_ENV_FILE", str(env))
    monkeypatch.delenv("ROUTER_PASS", raising=False)

    with pytest.raises(ConfigError) as exc:
        load_config()

    message = str(exc.value)
    assert "ROUTER_PASS is not set" in message
    assert str(env) in message
    assert "env.example" in message


def test_config_defaults_fill_in_around_the_password(monkeypatch, tmp_path):
    monkeypatch.setenv("ASUS_ENV_FILE", str(_empty_env(tmp_path)))
    monkeypatch.setenv("ROUTER_PASS", "secret")
    for name in ("ROUTER_HOST", "ROUTER_USER", "ROUTER_SSL", "ROUTER_PORT"):
        monkeypatch.delenv(name, raising=False)

    config = load_config()
    assert (config.host, config.username, config.use_ssl, config.port) == (
        "192.168.50.1",
        "admin",
        False,
        None,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [("true", True), ("TRUE", True), ("1", True), ("yes", True),
     ("false", False), ("0", False), ("", False)],
)
def test_router_ssl_parsing(monkeypatch, tmp_path, value, expected):
    monkeypatch.setenv("ASUS_ENV_FILE", str(_empty_env(tmp_path)))
    monkeypatch.setenv("ROUTER_PASS", "secret")
    monkeypatch.setenv("ROUTER_SSL", value)
    assert load_config().use_ssl is expected


# -- nvram reads -----------------------------------------------------------


def test_read_nvram_returns_only_the_requested_names():
    router = FakeRouter()
    assert run(read_nvram(router, ["wl0_mfp", "wl1_mfp"])) == {
        "wl0_mfp": "0",
        "wl1_mfp": "0",
    }


def test_read_nvram_of_nothing_makes_no_request():
    """writers.nvram([]) is falsy; the request must be skipped, not sent empty."""
    router = FakeRouter()
    calls = []
    router.async_api_hook = lambda request: calls.append(request)  # would fail if awaited
    assert run(read_nvram(router, [])) == {}
    assert calls == []


# -- nvram writes ----------------------------------------------------------


def test_apply_nvram_writes_restarts_and_reads_back():
    router = FakeRouter()
    result = run(apply_nvram(router, {"wl1_mfp": "2"}, "restart_wireless"))

    assert router.services == [("restart_wireless", {"wl1_mfp": "2"})]
    assert result["ok"] is True
    assert result["before"] == {"wl1_mfp": "0"}
    assert result["after"] == {"wl1_mfp": "2"}
    assert result["unchanged"] == []


def test_apply_nvram_flags_a_value_the_firmware_ignored():
    router = FakeRouter(apply_writes=False)
    result = run(apply_nvram(router, {"wl1_country_code": "AU"}, "restart_wireless"))

    assert result["ok"] is True  # the service ran
    assert result["unchanged"] == ["wl1_country_code"]  # but nothing changed


def test_apply_nvram_reads_before_it_writes():
    """The before/after report is worthless if both samples are post-write."""
    router = FakeRouter()
    result = run(apply_nvram(router, {"wps_enable": "0"}, "restart_wireless"))
    assert result["before"]["wps_enable"] == "1"
    assert result["after"]["wps_enable"] == "0"


def test_apply_nvram_reports_a_failed_service():
    router = FakeRouter(service_ok=False, apply_writes=False)
    assert run(apply_nvram(router, {"wps_enable": "0"}, "restart_wireless"))["ok"] is False


# -- serialisation helpers -------------------------------------------------


def test_jsonable_unpacks_a_frozen_dataclass():
    rule = PortForwardingRule(name="Plex", ip_address="10.0.0.1", port="32400")
    assert jsonable(rule)["name"] == "Plex"
    assert jsonable(rule)["ip_address"] == "10.0.0.1"


def test_jsonable_renders_enums_by_value():
    assert jsonable(AsusPortForwarding.ON) == 1


def test_jsonable_recurses_through_containers():
    payload = {"rules": [PortForwardingRule(name="A")], "state": AsusPortForwarding.OFF}
    out = jsonable(payload)
    assert out["rules"][0]["name"] == "A"
    assert out["state"] == 0


def test_jsonable_stringifies_anything_it_does_not_understand():
    assert jsonable(object()).startswith("<object")


def test_jsonable_passes_scalars_through():
    assert jsonable([1, "a", True, None]) == [1, "a", True, None]


def test_enum_name_prefers_the_name_over_the_number():
    assert enum_name(AsusPortForwarding.ON) == "ON"
    assert enum_name(None) == "None"
    assert enum_name("wired") == "wired"


# -- CLI-level helpers -----------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [("1", "ON"), ("0", "OFF"), (1, "ON"), ("none", "? ('none')"), (None, "? (None)")],
)
def test_onoff_keeps_unexpected_values_visible(value, expected):
    assert cli._onoff(value) == expected


@pytest.mark.parametrize(
    ("selection", "expected"),
    [("2ghz", [0]), ("5ghz", [1]), ("both", [0, 1])],
)
def test_bands_maps_to_nvram_indexes(selection, expected):
    assert cli._bands(selection) == expected


def test_split_rulelist_handles_the_escaped_delimiter():
    assert cli._split_rulelist("&#60a&#60b") == ["a", "b"]
    assert cli._split_rulelist("") == []
    assert cli._split_rulelist(None) == []


def test_wpa_modes_and_mfp_tables_agree():
    """Every mode's default mfp must be a value the --mfp flag also accepts."""
    for _mode, (_auth, mfp) in cli.WPA_MODES.items():
        assert mfp in cli.MFP_NAMES
    assert set(cli.MFP_NAMES) == set(cli.MFP_VALUES.values())


def test_wifi_vars_covers_both_bands_and_wps():
    for name in ("wps_enable", "wps_enable_x", "wps_multiband"):
        assert name in cli.WIFI_VARS
    for index in (0, 1):
        for suffix in ("radio", "auth_mode_x", "crypto", "mfp", "country_code"):
            assert f"wl{index}_{suffix}" in cli.WIFI_VARS
