"""Firmware: version reporting and the flash guards.

`firmware upgrade` is the most destructive command in the tool — it writes
flash and reboots — so most of what is asserted here is what it refuses to do.
"""

from __future__ import annotations

import json

import pytest

from asusrouter import AsusData
from asusrouter.modules.firmware import WebsError
from asusrouter.modules.system import AsusSystem

from asus_cli import cli
from helpers import FakeRouter, default_data, invoke

OFFERED = "3.0.0.4.388.34098_g9b0c9ae"
CURRENT = "3.0.0.4.388.34011_gfae8cb3"
BETA = "3.0.0.6.102_beta1"

# Every firmware command polls after asking the router to query ASUS.
NOWAIT = ("--wait", "0")


def firmware_router(**overrides) -> FakeRouter:
    data = default_data()
    data[AsusData.FIRMWARE] = {**data[AsusData.FIRMWARE], **overrides}
    return FakeRouter(data=data)


def up_to_date() -> FakeRouter:
    """webs.available still holds a version — it just equals current."""
    return firmware_router(state=False, available=None)


def unreachable() -> FakeRouter:
    """The router got no answer from ASUS, so webs.available is empty."""
    return firmware_router(
        state=False,
        available=None,
        webs={"update": None, "upgrade": None, "error": WebsError.NONE,
              "available": None, "available_beta": None},
    )


def download_error() -> FakeRouter:
    return firmware_router(
        state=False,
        available=None,
        webs={"update": None, "upgrade": None, "error": WebsError.DOWNLOAD_ERROR,
              "available": OFFERED, "available_beta": None},
    )


def with_beta() -> FakeRouter:
    return firmware_router(state_beta=True, available_beta=BETA)


# -- info ------------------------------------------------------------------


def test_info_checks_online_before_reporting(router):
    """The cached value is refreshed every time; a stale version is useless."""
    result = invoke(router, "firmware", "info", *NOWAIT)

    assert router.states == [(AsusSystem.FIRMWARE_CHECK, {})]
    assert f"Current    {CURRENT}" in result.out
    assert f"Latest     {OFFERED}   ** update available **" in result.out


def test_info_cached_skips_the_online_check(router):
    result = invoke(router, "firmware", "info", "--cached")

    assert router.states == []
    assert "(cached; not checked online just now)" in result.out


def test_info_reports_being_up_to_date():
    out = invoke(up_to_date(), "firmware", "info", *NOWAIT).out
    assert "(up to date)" in out
    assert "** update available **" not in out


def test_info_says_it_could_not_verify_when_asus_gave_no_answer():
    """Not knowing is different from knowing there is nothing to install."""
    out = invoke(unreachable(), "firmware", "info", *NOWAIT).out
    assert "could not verify" in out
    assert "up to date" not in out


def test_info_treats_a_download_error_as_unverified():
    out = invoke(download_error(), "firmware", "info", *NOWAIT).out
    assert "could not verify" in out


def test_info_hides_the_release_note_behind_a_flag(router):
    without = invoke(router, "firmware", "info", *NOWAIT).out
    assert "Run `asus firmware info --notes`" in without
    assert "Strengthened data handling" not in without

    with_notes = invoke(router, "firmware", "info", "--notes", *NOWAIT).out
    assert "Release note:" in with_notes
    assert "Strengthened data handling" in with_notes


def test_info_shows_the_beta_channel_only_when_one_is_offered():
    assert f"Beta       {BETA}" in invoke(with_beta(), "firmware", "info", *NOWAIT).out
    assert "Beta" not in invoke(up_to_date(), "firmware", "info", *NOWAIT).out


def test_info_json_carries_the_verdict(router):
    payload = json.loads(invoke(router, "--json", "firmware", "info", *NOWAIT).out)
    assert payload["current"] == CURRENT
    assert payload["status"] == "update"
    assert payload["latest"] == OFFERED


def test_info_json_says_unknown_rather_than_guessing():
    payload = json.loads(
        invoke(unreachable(), "--json", "firmware", "info", *NOWAIT).out
    )
    assert payload["status"] == "unknown"
    assert payload["latest"] is None


def test_info_never_flashes(router):
    invoke(router, "firmware", "info", "--notes", *NOWAIT)
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


# -- upgrade: the refusals -------------------------------------------------


def test_upgrade_refuses_when_already_up_to_date():
    router = up_to_date()
    result = invoke(router, "firmware", "upgrade", "--yes", *NOWAIT)

    assert result.code == cli.EXIT_ERROR
    assert "Already up to date" in result.err
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


def test_upgrade_refuses_when_the_latest_version_is_unknown():
    """Flashing on an unverified version is the one thing never to guess at."""
    router = unreachable()
    result = invoke(router, "firmware", "upgrade", "--yes", *NOWAIT)

    assert result.code == cli.EXIT_ERROR
    assert "Cannot verify the latest firmware version" in result.err
    assert "Refusing to flash" in result.err
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


def test_upgrade_refuses_beta_when_no_beta_is_offered(router):
    result = invoke(router, "firmware", "upgrade", "--beta", "--yes", *NOWAIT)
    assert result.code == cli.EXIT_ERROR
    assert "No beta update is available" in result.err


def test_upgrade_unattended_refuses_without_to(router):
    """With --yes and no terminal, nobody read the version. Make it explicit."""
    result = invoke(router, "firmware", "upgrade", "--yes", *NOWAIT)

    assert result.code == cli.EXIT_ERROR
    assert "Refusing to flash unattended without --to" in result.err
    assert OFFERED in result.err
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


def test_upgrade_unattended_refuses_a_mismatched_to(router):
    result = invoke(router, "firmware", "upgrade", "--yes", "--to", "9.9.9", *NOWAIT)

    assert result.code == cli.EXIT_ERROR
    assert "does not match what the router is offering" in result.err
    assert "9.9.9" in result.err and OFFERED in result.err
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


def test_upgrade_dry_run_spells_out_the_consequences(router):
    result = invoke(router, "firmware", "upgrade", *NOWAIT)

    assert result.code == cli.EXIT_NEEDS_CONFIRM
    assert f"FLASH firmware {OFFERED} over {CURRENT}" in result.err
    assert "brick the router" in result.err
    assert AsusSystem.FIRMWARE_UPGRADE not in [s for s, _ in router.states]


def test_upgrade_dry_run_needs_no_to(router):
    """--to is only for the unattended path; a dry run names the version itself."""
    result = invoke(router, "firmware", "upgrade", *NOWAIT)
    assert OFFERED in result.err


# -- upgrade: the one path that acts ---------------------------------------


def test_upgrade_unattended_with_the_right_version_flashes(router):
    result = invoke(router, "firmware", "upgrade", "--yes", "--to", OFFERED, *NOWAIT)

    assert result.code == 0
    assert (AsusSystem.FIRMWARE_UPGRADE, {}) in router.states


def test_upgrade_does_not_claim_the_upgrade_finished(router):
    """The API acknowledges the request and reports nothing after that."""
    out = invoke(router, "firmware", "upgrade", "--yes", "--to", OFFERED, *NOWAIT).out

    assert "requested" in out
    assert "reports no progress" in out
    assert "asus info" in out
    for word in ("Upgraded", "completed", "success"):
        assert word not in out


def test_upgrade_targets_the_beta_channel_when_asked():
    router = with_beta()
    result = invoke(
        router, "firmware", "upgrade", "--beta", "--yes", "--to", BETA, *NOWAIT
    )
    assert result.code == 0
    assert (AsusSystem.FIRMWARE_UPGRADE, {}) in router.states


def test_upgrade_that_the_router_refuses_exits_nonzero():
    data = default_data()
    router = FakeRouter(data=data, service_ok=False)
    result = invoke(router, "firmware", "upgrade", "--yes", "--to", OFFERED, *NOWAIT)
    assert result.code == cli.EXIT_ERROR
    assert "refused the upgrade request" in result.err


# -- progress indicator ----------------------------------------------------


def test_the_check_is_silent_when_stderr_is_not_a_terminal(router):
    """Piped and captured output must stay exactly what it was."""
    result = invoke(router, "firmware", "info", *NOWAIT)
    assert result.err == ""
    assert "\r" not in result.out


def test_the_spinner_runs_and_cleans_up_at_a_terminal(monkeypatch, capsys):
    """It draws frames on stderr, then erases the line it drew."""
    import asyncio

    monkeypatch.setattr(cli.sys.stderr, "isatty", lambda: True, raising=False)

    async def scenario():
        async with cli.progress("Working"):
            await asyncio.sleep(0.25)

    asyncio.run(scenario())

    err = capsys.readouterr().err
    assert "Working" in err
    assert any(frame in err for frame in cli.SPINNER_FRAMES)
    assert err.endswith("\r")  # the line was wiped, not left on screen


def test_cached_produces_no_progress_output(router):
    """--cached does no slow call, so there is nothing to report on."""
    result = invoke(router, "firmware", "info", "--cached")
    assert result.err == ""
