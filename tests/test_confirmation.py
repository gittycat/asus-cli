"""Consent: when the tool acts, when it asks, and when it refuses.

The property the whole tool rests on is that it never acts without being told
to. There are three ways to be told: --yes, a person answering the prompt, or
nothing — and nothing must never mean yes.
"""

from __future__ import annotations

import builtins
import sys
from types import SimpleNamespace

import pytest

from asusrouter.modules.port_forwarding import AsusPortForwarding

from asuswrt import cli
from helpers import FakeRouter, invoke

# A mutation that is cheap to observe: it records exactly one state.
ARGV = ("pf", "enable")


@pytest.fixture
def terminal(monkeypatch):
    """Pretend a person is sitting at a terminal, and script their answer."""

    def answer(text: str | type[EOFError]):
        monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))

        def fake_input():
            if text is EOFError:
                raise EOFError
            return text

        monkeypatch.setattr(builtins, "input", fake_input)

    return answer


@pytest.fixture
def headless(monkeypatch):
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: False))
    # Nothing may read stdin when there is no terminal.
    monkeypatch.setattr(
        builtins, "input", lambda *a: pytest.fail("prompted with no terminal")
    )


# -- no terminal -----------------------------------------------------------


def test_no_terminal_and_no_yes_refuses_with_exit_3(headless, router):
    """Silence is not consent. This is the exit code a caller checks."""
    result = invoke(router, *ARGV)

    assert result.code == cli.EXIT_NEEDS_CONFIRM
    assert result.code != cli.EXIT_ERROR
    assert "Re-run with --yes to apply." in result.err
    assert router.states == []


def test_no_terminal_with_yes_acts(headless, router):
    result = invoke(router, *ARGV, "--yes")
    assert result.code == 0
    assert router.states == [(AsusPortForwarding.ON, {})]


# -- at a terminal ---------------------------------------------------------


@pytest.mark.parametrize("answer", ["y", "Y", "yes", "YES", " y "])
def test_terminal_accepts_an_affirmative_answer(terminal, router, answer):
    terminal(answer)
    result = invoke(router, *ARGV)

    assert result.code == 0
    assert router.states == [(AsusPortForwarding.ON, {})]


@pytest.mark.parametrize("answer", ["n", "no", "", "maybe", "yeah"])
def test_terminal_treats_anything_else_as_no(terminal, router, answer):
    terminal(answer)
    result = invoke(router, *ARGV)

    assert result.code == cli.EXIT_NEEDS_CONFIRM
    assert "Cancelled." in result.err
    assert router.states == []


def test_terminal_end_of_input_is_a_no(terminal, router):
    terminal(EOFError)
    result = invoke(router, *ARGV)

    assert result.code == cli.EXIT_NEEDS_CONFIRM
    assert router.states == []


def test_terminal_is_told_what_it_is_agreeing_to(terminal, router):
    terminal("y")
    result = invoke(router, *ARGV)
    assert "Would turn port forwarding ON globally" in result.err
    assert "Proceed? [y/N]" in result.err


def test_yes_skips_the_prompt_entirely(monkeypatch, router):
    """--yes must not consult stdin even when a terminal is present."""
    monkeypatch.setattr(sys, "stdin", SimpleNamespace(isatty=lambda: True))
    monkeypatch.setattr(
        builtins, "input", lambda *a: pytest.fail("prompted despite --yes")
    )

    result = invoke(router, *ARGV, "--yes")
    assert result.code == 0
    assert router.states == [(AsusPortForwarding.ON, {})]


# -- the flag itself -------------------------------------------------------


def test_short_form_y_works(headless, router):
    invoke(router, *ARGV, "-y")
    assert router.states == [(AsusPortForwarding.ON, {})]


def test_confirm_still_works_as_an_undocumented_alias(headless, router):
    """Kept so existing scripts and muscle memory do not break."""
    invoke(router, *ARGV, "--confirm")
    assert router.states == [(AsusPortForwarding.ON, {})]


def test_confirm_is_not_advertised(capsys):
    """It still works, but --yes is the name people should learn."""
    with pytest.raises(SystemExit):
        cli.build_parser().parse_args(["pf", "enable", "--help"])

    help_text = capsys.readouterr().out
    assert "--yes" in help_text
    assert "--confirm" not in help_text


def test_read_commands_never_prompt(terminal, router):
    """main() fills in yes=True for commands that have no flag."""
    terminal(EOFError)
    for argv in (("info",), ("firewall",), ("wifi", "show")):
        assert invoke(router, *argv).code == 0
