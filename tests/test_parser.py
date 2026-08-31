"""The argument parser: what exists, what is required, what is refused."""

from __future__ import annotations

import pytest

from asus_cli import cli


def parse(*argv: str):
    return cli.build_parser().parse_args(list(argv))


def test_every_subcommand_resolves_to_a_command_function():
    cases = {
        ("info",): cli.cmd_info,
        ("status",): cli.cmd_status,
        ("clients",): cli.cmd_clients,
        ("wan",): cli.cmd_wan,
        ("firewall",): cli.cmd_firewall,
        ("pf", "list"): cli.cmd_pf_list,
        ("pf", "enable"): cli.cmd_pf_toggle,
        ("pf", "disable"): cli.cmd_pf_toggle,
        ("parental", "enable"): cli.cmd_parental,
        ("guest", "list"): cli.cmd_guest_list,
        ("guest", "enable", "--band", "2ghz", "--id", "1"): cli.cmd_guest_toggle,
        ("wifi", "show"): cli.cmd_wifi_show,
        ("wifi", "wps", "enable"): cli.cmd_wifi_wps,
        ("wifi", "wps", "disable"): cli.cmd_wifi_wps,
        ("wifi", "security", "--mode", "wpa3"): cli.cmd_wifi_security,
        ("wifi", "country", "--code", "AU"): cli.cmd_wifi_country,
        ("nvram", "wl0_radio"): cli.cmd_nvram,
        ("reboot",): cli.cmd_reboot,
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
        ("wifi", "security", "--mode", "wpa2"),
        ("wifi", "country", "--code", "AU"),
        ("reboot",),
    ],
)
def test_mutations_carry_a_confirm_flag(argv):
    assert parse(*argv).yes is False


@pytest.mark.parametrize(
    "argv",
    [
        ("info",),
        ("status",),
        ("clients",),
        ("wan",),
        ("firewall",),
        ("pf", "list"),
        ("guest", "list"),
        ("wifi", "show"),
        ("nvram", "wl0_radio"),
    ],
)
def test_read_commands_have_no_confirm_flag(argv):
    """main() supplies confirm=True for these; the flag must not exist here."""
    assert not hasattr(parse(*argv), "yes")


@pytest.mark.parametrize(
    "argv",
    [
        ("wifi",),  # subcommand required
        ("wifi", "wps"),  # enable/disable required
        ("wifi", "security"),  # --mode required
        ("wifi", "country"),  # --code required
        ("wifi", "security", "--mode", "wpa4"),  # not a mode
        ("wifi", "security", "--mode", "wpa3", "--mfp", "maybe"),  # not an mfp level
        ("wifi", "security", "--mode", "wpa3", "--band", "6ghz"),  # not a band
        ("wifi", "country", "--code", "AU", "--band", "6ghz"),
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
    assert parse("wifi", "security", "--mode", "wpa3").band == "both"
    assert parse("wifi", "country", "--code", "AU").band == "both"


def test_mfp_defaults_to_unset_so_the_mode_decides():
    assert parse("wifi", "security", "--mode", "wpa3").mfp is None


def test_json_is_a_global_flag_not_a_subcommand_flag():
    """`asus --json nvram X` works; `asus nvram X --json` does not."""
    assert parse("--json", "nvram", "wl0_radio").json is True
    with pytest.raises(SystemExit):
        parse("nvram", "wl0_radio", "--json")


def test_pf_add_defaults():
    args = parse("pf", "add", "--name", "X", "--port", "80", "--to-ip", "10.0.0.1")
    assert args.proto == "TCP"
    assert args.to_port is None
    assert args.from_ip == ""
    assert args.force is False
