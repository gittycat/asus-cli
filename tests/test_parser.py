"""The argument parser: what exists, what is required, what is refused."""

from __future__ import annotations

import pytest

from asuswrt import cli


def parse(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def test_every_subcommand_resolves_to_a_command_function():
    cases = {
        ("show",): cli.cmd_show,
        ("system", "show"): cli.cmd_system_show,
        ("system", "health"): cli.cmd_system_health,
        ("clients", "show"): cli.cmd_clients,
        ("wan", "show"): cli.cmd_wan,
        ("firewall", "show"): cli.cmd_firewall_show,
        ("parental", "show"): cli.cmd_parental_show,
        ("parental", "enable"): cli.cmd_parental,
        ("portforward", "show"): cli.cmd_pf_show,
        ("portforward", "enable"): cli.cmd_pf_toggle,
        ("portforward", "disable"): cli.cmd_pf_toggle,
        ("guest", "show"): cli.cmd_guest_show,
        ("guest", "enable", "--band", "2ghz", "--id", "1"): cli.cmd_guest_toggle,
        ("wifi", "show"): cli.cmd_wifi_show,
        ("wifi", "wps", "enable"): cli.cmd_wifi_wps,
        ("wifi", "wps", "disable"): cli.cmd_wifi_wps,
        ("wifi", "set-security", "--mode", "wpa3"): cli.cmd_wifi_security,
        ("wifi", "set-country", "--code", "AU"): cli.cmd_wifi_country,
        ("firmware", "show"): cli.cmd_firmware_show,
        ("firmware", "upgrade"): cli.cmd_firmware_upgrade,
        ("nvram", "get", "wl0_radio"): cli.cmd_nvram,
        ("reboot",): cli.cmd_reboot,
    }
    for argv, func in cases.items():
        assert parse(*argv).func is func, argv


def test_a_bare_noun_means_show():
    """The rule that lets an agent reach any reading without a lookup table."""
    cases = {
        ("system",): cli.cmd_system_show,
        ("wan",): cli.cmd_wan,
        ("clients",): cli.cmd_clients,
        ("firewall",): cli.cmd_firewall_show,
        ("parental",): cli.cmd_parental_show,
        ("portforward",): cli.cmd_pf_show,
        ("guest",): cli.cmd_guest_show,
        ("wifi",): cli.cmd_wifi_show,
        ("firmware",): cli.cmd_firmware_show,
    }
    for argv, func in cases.items():
        assert parse(*argv).func is func, argv


def test_names_from_before_the_rename_still_work():
    """Renames are additive: a name an agent learned is a contract."""
    cases = {
        ("info",): cli.cmd_system_show,
        ("status",): cli.cmd_system_health,
        ("pf", "list"): cli.cmd_pf_show,
        ("pf", "add", "--name", "X", "--port", "80", "--to-ip", "10.0.0.1"): cli.cmd_pf_add,
        ("guest", "list"): cli.cmd_guest_show,
        ("wifi", "security", "--mode", "wpa3"): cli.cmd_wifi_security,
        ("wifi", "country", "--code", "AU"): cli.cmd_wifi_country,
        ("firmware", "info"): cli.cmd_firmware_show,
        ("nvram", "wl0_radio"): cli.cmd_nvram,
    }
    for argv, func in cases.items():
        assert parse(*argv).func is func, argv


@pytest.mark.parametrize(
    "argv",
    [
        ("pf", "add", "--name", "X", "--port", "80", "--to-ip", "10.0.0.1"),
        ("pf", "remove", "--name", "X"),
        ("pf", "enable"),
        ("pf", "disable"),
        ("guest", "enable", "--band", "2ghz", "--id", "1"),
        ("parental", "enable"),
        ("wifi", "wps", "disable"),
        ("wifi", "set-security", "--mode", "wpa2"),
        ("wifi", "set-country", "--code", "AU"),
        ("firmware", "upgrade"),
        ("reboot",),
    ],
)
def test_mutations_carry_a_confirm_flag(argv):
    assert parse(*argv).yes is False


@pytest.mark.parametrize(
    "argv",
    [
        ("show",),
        ("system", "show"),
        ("system", "health"),
        ("clients",),
        ("wan",),
        ("firewall",),
        ("parental", "show"),
        ("portforward", "show"),
        ("guest", "show"),
        ("wifi", "show"),
        ("firmware", "show"),
        ("nvram", "get", "wl0_radio"),
    ],
)
def test_read_commands_have_no_confirm_flag(argv):
    """main() supplies confirm=True for these; the flag must not exist here."""
    assert not hasattr(parse(*argv), "yes")


@pytest.mark.parametrize(
    "argv",
    [
        ("wifi", "wps"),  # enable/disable required
        ("wifi", "set-security"),  # --mode required
        ("wifi", "set-country"),  # --code required
        ("wifi", "set-security", "--mode", "wpa4"),  # not a mode
        ("wifi", "set-security", "--mode", "wpa3", "--mfp", "maybe"),  # not an mfp level
        ("wifi", "set-security", "--mode", "wpa3", "--band", "6ghz"),  # not a band
        ("wifi", "set-country", "--code", "AU", "--band", "6ghz"),
        ("guest", "enable", "--band", "2ghz", "--id", "4"),  # only 1-3 exist
        ("pf", "add", "--name", "X", "--port", "80"),  # --to-ip required
        ("nvram",),  # at least one variable name
        ("nope",),
    ],
)
def test_invalid_invocations_are_refused(argv):
    with pytest.raises(SystemExit) as exc:
        parse(*argv)
    assert exc.value.code == 2


def test_band_defaults_to_both_for_wifi_writes():
    assert parse("wifi", "set-security", "--mode", "wpa3").band == "both"
    assert parse("wifi", "set-country", "--code", "AU").band == "both"


def test_mfp_defaults_to_unset_so_the_mode_decides():
    assert parse("wifi", "set-security", "--mode", "wpa3").mfp is None


def test_json_is_a_global_flag_not_a_subcommand_flag():
    """`asuswrt --json nvram X` works; `asuswrt nvram X --json` does not."""
    assert parse("--json", "nvram", "get", "wl0_radio").json is True
    with pytest.raises(SystemExit):
        parse("nvram", "get", "wl0_radio", "--json")


def test_read_options_reach_both_the_noun_and_its_show():
    assert parse("clients", "--online").online is True
    assert parse("clients", "show", "--online").online is True
    assert parse("firmware", "--notes").notes is True
    assert parse("firmware", "show", "--notes").notes is True


def test_pf_add_defaults():
    args = parse("portforward", "add", "--name", "X", "--port", "80", "--to-ip", "10.0.0.1")
    assert args.proto == "TCP"
    assert args.to_port is None
    assert args.from_ip == ""
    assert args.force is False
