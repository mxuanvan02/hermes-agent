"""9Router web search + fetch plugin — bundled, auto-loaded."""

from __future__ import annotations

from .provider import NineRouterWebSearchProvider


def register(ctx) -> None:
    """Register the 9Router provider with the plugin context."""
    ctx.register_web_search_provider(NineRouterWebSearchProvider())
