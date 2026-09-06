"""Tests for the Discord bot-to-bot chain breaker.

Two agents that @mention each other keep answering forever.  The existing
rate limit only throttles that exchange — once its window slides past, both
sides resume.  The chain guard counts *consecutive* bot messages with no human
in between and stops answering, staying silent until a person posts.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
import sys

import pytest

from gateway.config import PlatformConfig


def _ensure_discord_mock():
    """Install a mock discord module when discord.py isn't available."""
    if "discord" in sys.modules and hasattr(sys.modules["discord"], "__file__"):
        return

    discord_mod = MagicMock()
    discord_mod.Intents.default.return_value = MagicMock()
    discord_mod.Client = MagicMock
    discord_mod.File = MagicMock
    discord_mod.DMChannel = type("DMChannel", (), {})
    discord_mod.Thread = type("Thread", (), {})
    discord_mod.ForumChannel = type("ForumChannel", (), {})
    discord_mod.ui = SimpleNamespace(View=object, button=lambda *a, **k: (lambda fn: fn), Button=object)
    discord_mod.ButtonStyle = SimpleNamespace(
        success=1, primary=2, secondary=2, danger=3, green=1, grey=2, blurple=2, red=3
    )
    discord_mod.Color = SimpleNamespace(
        orange=lambda: 1, green=lambda: 2, blue=lambda: 3, red=lambda: 4, purple=lambda: 5
    )
    discord_mod.Interaction = object
    discord_mod.Embed = MagicMock
    discord_mod.app_commands = SimpleNamespace(
        describe=lambda **kwargs: (lambda fn: fn),
        choices=lambda **kwargs: (lambda fn: fn),
        Choice=lambda **kwargs: SimpleNamespace(**kwargs),
    )

    ext_mod = MagicMock()
    commands_mod = MagicMock()
    commands_mod.Bot = MagicMock
    ext_mod.commands = commands_mod

    sys.modules.setdefault("discord", discord_mod)
    sys.modules.setdefault("discord.ext", ext_mod)
    sys.modules.setdefault("discord.ext.commands", commands_mod)


_ensure_discord_mock()

from plugins.platforms.discord.adapter import DiscordAdapter  # noqa: E402


@pytest.fixture
def adapter(monkeypatch):
    for var in ("DISCORD_BOT_CHAIN_LIMIT", "DISCORD_ALLOW_BOTS"):
        monkeypatch.delenv(var, raising=False)
    return DiscordAdapter(PlatformConfig(enabled=True, token="fake-token", extra={}))


def test_chain_guard_stops_after_limit(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "3")

    verdicts = [adapter._discord_bot_chain_allowed("10") for _ in range(5)]

    assert verdicts == [True, True, True, False, False]


def test_chain_guard_default_limit_is_four(adapter):
    verdicts = [adapter._discord_bot_chain_allowed("10") for _ in range(6)]

    assert verdicts == [True, True, True, True, False, False]


def test_chain_guard_stays_closed_without_a_human(adapter, monkeypatch):
    """Unlike the rate limit, waiting does not reopen the exchange."""
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "1")

    assert adapter._discord_bot_chain_allowed("10") is True
    assert adapter._discord_bot_chain_allowed("10") is False
    # No human message, any amount of time later → still closed.
    assert adapter._discord_bot_chain_allowed("10") is False


def test_human_message_reopens_the_exchange(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "2")

    assert adapter._discord_bot_chain_allowed("10") is True
    assert adapter._discord_bot_chain_allowed("10") is True
    assert adapter._discord_bot_chain_allowed("10") is False

    adapter._discord_note_human_message("10")

    assert adapter._discord_bot_chain_allowed("10") is True


def test_chain_guard_is_per_channel(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "1")

    assert adapter._discord_bot_chain_allowed("10") is True
    assert adapter._discord_bot_chain_allowed("10") is False
    assert adapter._discord_bot_chain_allowed("11") is True


def test_human_message_in_one_channel_does_not_reopen_another(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "1")

    adapter._discord_bot_chain_allowed("10")
    assert adapter._discord_bot_chain_allowed("10") is False

    adapter._discord_note_human_message("11")

    assert adapter._discord_bot_chain_allowed("10") is False


def test_chain_guard_disabled_by_zero_limit(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "0")

    assert adapter._discord_bot_chain_allowed("10") is False


def test_chain_guard_falls_back_on_unparseable_limit(adapter, monkeypatch):
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "not-a-number")

    verdicts = [adapter._discord_bot_chain_allowed("10") for _ in range(6)]

    assert verdicts == [True, True, True, True, False, False]


def test_warning_is_reported_once_per_runaway_exchange(adapter, monkeypatch):
    """The report flag latches so the log gets one warning, not one per message."""
    monkeypatch.setenv("DISCORD_BOT_CHAIN_LIMIT", "1")

    adapter._discord_bot_chain_allowed("10")
    assert adapter._discord_bot_chain_allowed("10") is False

    adapter._bot_chain_reported.add("10")
    assert adapter._discord_bot_chain_allowed("10") is False
    assert "10" in adapter._bot_chain_reported

    # A human resets both the counter and the report latch.
    adapter._discord_note_human_message("10")
    assert "10" not in adapter._bot_chain_reported
