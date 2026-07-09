"""Tests for TelegramAdapter._edit_overflow_split rich rendering.

Long (>4096 UTF-16) finalized edits are delivered by splitting into a
first-chunk edit + continuation sends. Before the fix that path used only
MarkdownV2/plain, which downgraded ## headings and broke $...$ formulas on
every long reply, while short replies (which take the rich edit_message path)
rendered fine.

These tests pin the fix:
  1. finalize=True first chunk edits via editMessageText + rich_message.
  2. finalize=True continuation chunks send via sendRichMessage.
  3. When the rich attempts raise, both fall back to MarkdownV2/plain.
  4. Streaming (finalize=False) stays plain — no rich churn mid-stream.
"""

from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from gateway.config import PlatformConfig


def _install_fake_telegram(monkeypatch):
    """Stub python-telegram-bot so TelegramAdapter imports without the dep."""
    fake_telegram = types.ModuleType("telegram")
    fake_telegram.Update = SimpleNamespace(ALL_TYPES=())
    fake_telegram.Bot = object
    fake_telegram.Message = object
    fake_telegram.InlineKeyboardButton = object
    fake_telegram.InlineKeyboardMarkup = object

    fake_error = types.ModuleType("telegram.error")
    fake_error.NetworkError = type("NetworkError", (Exception,), {})
    fake_error.BadRequest = type("BadRequest", (Exception,), {})
    fake_error.TimedOut = type("TimedOut", (Exception,), {})
    fake_telegram.error = fake_error

    fake_constants = types.ModuleType("telegram.constants")
    fake_constants.ParseMode = SimpleNamespace(MARKDOWN_V2="MarkdownV2")
    fake_constants.ChatType = SimpleNamespace(
        GROUP="group", SUPERGROUP="supergroup",
        CHANNEL="channel", PRIVATE="private",
    )
    fake_telegram.constants = fake_constants

    fake_ext = types.ModuleType("telegram.ext")
    fake_ext.Application = object
    fake_ext.CommandHandler = object
    fake_ext.CallbackQueryHandler = object
    fake_ext.MessageHandler = object
    fake_ext.ContextTypes = SimpleNamespace(DEFAULT_TYPE=object)
    fake_ext.filters = object

    fake_request = types.ModuleType("telegram.request")
    fake_request.HTTPXRequest = object

    monkeypatch.setitem(sys.modules, "telegram", fake_telegram)
    monkeypatch.setitem(sys.modules, "telegram.error", fake_error)
    monkeypatch.setitem(sys.modules, "telegram.constants", fake_constants)
    monkeypatch.setitem(sys.modules, "telegram.ext", fake_ext)
    monkeypatch.setitem(sys.modules, "telegram.request", fake_request)


# Content guaranteed to exceed 4096 UTF-16 units → splits into ≥2 chunks.
# Formula-laden so a regression (MarkdownV2/plain) would visibly break it.
_OVERFLOW = "\n".join(
    f"Line {i}: energy $E=mc^2$ with $H_0$ and $$\\frac{{-b}}{{2a}}$$ ## heading"
    for i in range(120)
)


@pytest.fixture
def adapter(monkeypatch):
    _install_fake_telegram(monkeypatch)
    from gateway.platforms.telegram import TelegramAdapter

    a = TelegramAdapter(PlatformConfig(enabled=True, token="fake-token"))
    a._bot = MagicMock()
    a._bot._post = AsyncMock(return_value={"message_id": 999})
    a._bot.edit_message_text = AsyncMock()
    a._bot.send_message = AsyncMock(
        return_value=SimpleNamespace(message_id=1000)
    )
    # Neutralise threading/preview/notification plumbing for a focused test.
    a._metadata_thread_id = MagicMock(return_value=None)
    a._thread_kwargs_for_send = MagicMock(return_value={})
    a._link_preview_kwargs = MagicMock(return_value={})
    a._notification_kwargs = MagicMock(return_value={})
    return a


@pytest.mark.asyncio
async def test_overflow_content_actually_splits(adapter):
    """Sanity: the fixture content really does split into ≥2 chunks."""
    from gateway.platforms.base import utf16_len

    chunks = adapter.truncate_message(
        _OVERFLOW, adapter.MAX_MESSAGE_LENGTH, len_fn=utf16_len,
    )
    assert len(chunks) >= 2


@pytest.mark.asyncio
async def test_finalize_first_chunk_uses_rich_edit(adapter):
    """First chunk must edit via editMessageText + rich_message."""
    await adapter._edit_overflow_split(
        "12345", "500", _OVERFLOW, finalize=True,
    )

    edit_posts = [
        c for c in adapter._bot._post.await_args_list
        if c.args and c.args[0] == "editMessageText"
    ]
    assert len(edit_posts) == 1
    data = edit_posts[0].kwargs["data"]
    assert "rich_message" in data
    assert "markdown" in data["rich_message"]
    # No MarkdownV2 edit fallback should fire when rich succeeds.
    adapter._bot.edit_message_text.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_continuation_uses_send_rich(adapter):
    """Continuation chunks must go through sendRichMessage."""
    await adapter._edit_overflow_split(
        "12345", "500", _OVERFLOW, finalize=True,
    )

    rich_sends = [
        c for c in adapter._bot._post.await_args_list
        if c.args and c.args[0] == "sendRichMessage"
    ]
    assert len(rich_sends) >= 1
    # Rich path handled every continuation → no MarkdownV2/plain send_message.
    adapter._bot.send_message.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_falls_back_when_rich_fails(adapter):
    """When rich raises, both chunks must fall back to MarkdownV2/plain."""
    adapter._bot._post = AsyncMock(side_effect=RuntimeError("no rich here"))

    result = await adapter._edit_overflow_split(
        "12345", "500", _OVERFLOW, finalize=True,
    )

    assert result.success is True
    # First-chunk fallback edits; continuations fall back to send_message.
    adapter._bot.edit_message_text.assert_awaited()
    adapter._bot.send_message.assert_awaited()


@pytest.mark.asyncio
async def test_streaming_stays_plain(adapter):
    """finalize=False must not touch rich endpoints (no mid-stream churn)."""
    await adapter._edit_overflow_split(
        "12345", "500", _OVERFLOW, finalize=False,
    )

    rich_calls = [
        c for c in adapter._bot._post.await_args_list
        if c.args and c.args[0] in ("editMessageText", "sendRichMessage")
    ]
    assert rich_calls == []
