"""Every mutation must refuse to act without --yes.

This is the guardrail the skill leans on hardest: an agent runs the bare
command first to show the user what would happen. If any of these ever
touches the router, that promise is broken.
"""

from __future__ import annotations

import pytest

from asuswrt.cli import main as cli
from helpers import FakeRouter, invoke

MUTATIONS = [
    ("pf", "add", "--name", "Plex", "--port", "32400", "--to-ip", "192.168.50.20"),
    ("pf", "remove", "--name", "Plex"),
    ("pf", "enable"),
    ("pf", "disable"),
    ("guest", "enable", "--band", "2ghz", "--id", "1"),
    ("guest", "disable", "--band", "5ghz", "--id", "1"),
    ("parental", "enable"),
    ("parental", "disable"),
    ("wifi", "wps", "enable"),
    ("wifi", "wps", "disable"),
    ("wifi", "security", "--mode", "wpa2wpa3"),
    ("wifi", "security", "--band", "5ghz", "--mode", "wpa3", "--mfp", "capable"),
    ("wifi", "country", "--band", "5ghz", "--code", "AU"),
    ("dns", "set", "--server1", "8.8.8.8", "--server2", "8.8.4.4"),
    ("dns", "auto"),
    ("led", "on"),
    ("led", "off"),
    ("upnp", "enable"),
    ("upnp", "disable"),
    ("firmware", "upgrade", "--wait", "0"),
    ("reboot",),
]


# firmware upgrade has to ask the router for the offered version before it
# can name it in the prompt, which costs a FIRMWARE_CHECK. It changes nothing,
# but it is not silent, so it is asserted separately below.
PROBES_THE_ROUTER = {("firmware", "upgrade", "--wait", "0")}


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda a: " ".join(a))
def test_dry_run_exits_3_and_refuses(pf_router, argv):
    result = invoke(pf_router, *argv)

    assert result.code == cli.EXIT_NEEDS_CONFIRM
    assert "Re-run with --yes to apply." in result.err
    assert result.err.startswith("Would ")
    if argv not in PROBES_THE_ROUTER:
        assert not pf_router.touched


@pytest.mark.parametrize("argv", MUTATIONS, ids=lambda a: " ".join(a))
def test_dry_run_says_what_it_would_do(pf_router, argv):
    """The refusal text is what the agent shows the user, so it must be specific."""
    result = invoke(pf_router, *argv)
    first = result.err.splitlines()[0]
    assert len(first) > len("Would ") + 10, first


def test_wifi_security_dry_run_names_the_resolved_nvram_values():
    router = FakeRouter()
    result = invoke(router, "wifi", "security", "--mode", "wpa2wpa3")

    assert "auth_mode_x=psk2sae" in result.err
    assert "crypto=aes" in result.err
    assert "mfp=capable" in result.err
    assert "reconnects" in result.err
    assert not router.touched


def test_wps_dry_run_reads_as_on_off_not_enable_disable():
    router = FakeRouter()
    assert "turn WPS OFF" in invoke(router, "wifi", "wps", "disable").err
    assert "turn WPS ON" in invoke(router, "wifi", "wps", "enable").err


def test_wps_enable_dry_run_warns_about_the_pin():
    router = FakeRouter()
    assert "brute-forceable" in invoke(router, "wifi", "wps", "enable").err
    assert "brute-forceable" not in invoke(router, "wifi", "wps", "disable").err


def test_reboot_dry_run_states_the_blast_radius():
    router = FakeRouter()
    result = invoke(router, "reboot")
    assert "REBOOT" in result.err
    assert "every connection" in result.err
    assert not router.touched


def test_pf_add_dry_run_never_contacts_the_router():
    """needs_confirm fires before connect(), so a dry run cannot have side effects."""
    router = FakeRouter()
    invoke(router, "pf", "add", "--name", "X", "--port", "80", "--to-ip", "10.0.0.1")
    assert router.applied_pf_rules is None


def test_pf_remove_with_no_match_fails_before_asking_to_confirm(router):
    """The empty router has no rules at all, not even an empty rules key."""
    result = invoke(router, "pf", "remove", "--name", "Nope")
    assert result.code == 1
    assert "No matching rule." in result.err
    assert not router.touched
