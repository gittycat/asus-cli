"""Golden snapshot of CLI output, guarding the render/ops extraction.

One case per canonical read command, plus one per mutation as a dry run and
again with --yes. Each case runs through the same `invoke()` helper the rest
of the suite uses and compares (exit code, stdout, stderr,
router.services, router.states, router.applied_pf_rules) against
tests/golden.json.

The rest of the suite mostly asserts substrings, which is exactly why a line
of drift in the extraction could sail through it unnoticed. This test
compares full output, byte for byte.

Do NOT regenerate tests/golden.json after it is committed. If this test
fails, the extraction changed something — fix the code, not the fixture.
The generator that produced golden.json is a throwaway script, not part of
this repo, precisely so nothing here can quietly "fix" a failure by
re-snapshotting it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from asusrouter import AsusData
from asusrouter.modules.port_forwarding import AsusPortForwarding, PortForwardingRule

from asuswrt.router import jsonable
from helpers import FakeRouter, default_data, invoke

GOLDEN_PATH = Path(__file__).parent / "golden.json"

# The version the fixture's FIRMWARE data offers (see helpers.default_data).
OFFERED = "3.0.0.4.388.34098_g9b0c9ae"


def _pf_data() -> dict[Any, Any]:
    """A router with two existing port-forwarding rules to add to / remove from."""
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
    return data


def make_router(kind: str) -> FakeRouter:
    """"plain" is the vanilla fixture; "pf" pre-seeds two forwarding rules."""
    return FakeRouter(data=_pf_data()) if kind == "pf" else FakeRouter()


# -- canonical read commands, one per noun -----------------------------------
# (name, router kind, argv). --cpu-sample/--wait 0 keep these instant and
# deterministic; nothing here depends on a wall clock.

READ_CASES: list[tuple[str, str, tuple[str, ...]]] = [
    ("show", "plain", ("show", "--cpu-sample", "0")),
    ("system_show", "plain", ("system", "show")),
    ("system_health", "plain", ("system", "health", "--cpu-sample", "0")),
    ("clients", "plain", ("clients",)),
    ("clients_online", "plain", ("clients", "--online")),
    ("wan", "plain", ("wan",)),
    ("dns_show", "plain", ("dns",)),
    ("led_show", "plain", ("led",)),
    ("upnp_show", "plain", ("upnp",)),
    ("firewall", "plain", ("firewall",)),
    ("parental_show", "plain", ("parental",)),
    ("portforward_show", "pf", ("portforward", "show")),
    ("guest_show", "plain", ("guest",)),
    ("wifi_show", "plain", ("wifi",)),
    ("nvram", "plain", ("nvram", "get", "wl0_country_code", "wl1_country_code")),
    ("firmware_show", "plain", ("firmware", "show", "--wait", "0")),
]

# -- one canonical mutation per verb ------------------------------------------
# (name, router kind, argv without --yes, extra args added only when confirming)

MUTATION_CASES: list[tuple[str, str, tuple[str, ...], tuple[str, ...]]] = [
    (
        "pf_add", "pf",
        ("pf", "add", "--name", "Game", "--port", "27015", "--to-ip", "192.168.50.40"),
        (),
    ),
    ("pf_remove", "pf", ("pf", "remove", "--name", "Plex"), ()),
    ("pf_enable", "plain", ("pf", "enable"), ()),
    ("pf_disable", "plain", ("pf", "disable"), ()),
    ("guest_enable", "plain", ("guest", "enable", "--band", "2ghz", "--id", "1"), ()),
    ("guest_disable", "plain", ("guest", "disable", "--band", "5ghz", "--id", "1"), ()),
    ("parental_enable", "plain", ("parental", "enable"), ()),
    ("parental_disable", "plain", ("parental", "disable"), ()),
    ("wps_enable", "plain", ("wifi", "wps", "enable"), ()),
    ("wps_disable", "plain", ("wifi", "wps", "disable"), ()),
    ("wifi_security", "plain", ("wifi", "security", "--mode", "wpa2wpa3"), ()),
    ("wifi_country", "plain", ("wifi", "country", "--band", "5ghz", "--code", "AU"), ()),
    (
        "dns_set", "plain",
        ("dns", "set", "--server1", "8.8.8.8", "--server2", "8.8.4.4"),
        (),
    ),
    ("dns_auto", "plain", ("dns", "auto"), ()),
    ("upnp_enable", "plain", ("upnp", "enable"), ()),
    ("upnp_disable", "plain", ("upnp", "disable"), ()),
    ("led_on", "plain", ("led", "on"), ()),
    ("led_off", "plain", ("led", "off"), ()),
    (
        "firmware_upgrade", "plain",
        ("firmware", "upgrade", "--wait", "0"),
        ("--to", OFFERED),
    ),
    ("reboot", "plain", ("reboot",), ()),
]


def all_cases() -> dict[str, tuple[str, tuple[str, ...]]]:
    """Every (command, confirmed?) case this test covers, keyed by name.

    Shared with the (out-of-repo) generator so the snapshot and the test can
    never drift apart on what "the canonical command" means.
    """
    cases: dict[str, tuple[str, tuple[str, ...]]] = {}
    for name, kind, argv in READ_CASES:
        cases[f"read:{name}"] = (kind, argv)
    for name, kind, argv, confirm_extra in MUTATION_CASES:
        cases[f"mutate:{name}:dry"] = (kind, argv)
        cases[f"mutate:{name}:yes"] = (kind, (*argv, *confirm_extra, "--yes"))
    return cases


def run_case(kind: str, argv: tuple[str, ...]) -> dict[str, Any]:
    """Run one case and capture the slice of state the plan calls out."""
    router = make_router(kind)
    result = invoke(router, *argv)
    return {
        "exit_code": result.code,
        "stdout": result.out,
        "stderr": result.err,
        "services": jsonable(router.services),
        "states": jsonable(router.states),
        "applied_pf_rules": jsonable(router.applied_pf_rules),
    }


CASES = all_cases()
_golden_cache: dict[str, Any] | None = None


def _golden() -> dict[str, Any]:
    global _golden_cache
    if _golden_cache is None:
        _golden_cache = json.loads(GOLDEN_PATH.read_text())
    return _golden_cache


@pytest.mark.parametrize("key", list(CASES), ids=list(CASES))
def test_golden(key):
    kind, argv = CASES[key]
    actual = run_case(kind, argv)
    expected = _golden().get(key)
    assert expected is not None, f"{key!r} is missing from golden.json"
    assert actual == expected


def test_golden_has_no_stale_entries():
    """Catches a case renamed or removed here without updating golden.json."""
    assert set(_golden()) == set(CASES)
