"""9Router web search + fetch provider.

Bridges Hermes' WebSearchProvider contract to the local 9Router proxy:

- POST /v1/search for search-capable providers such as Tavily and Exa.
- POST /v1/web/fetch for fetch-capable providers such as Jina Reader,
  Firecrawl, Tavily, and Exa.

9Router owns the upstream API keys and routing. Hermes only needs
NINEROUTER_API_KEY and NINEROUTER_ENDPOINT.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from agent.web_search_provider import WebSearchProvider

logger = logging.getLogger(__name__)


DEFAULT_ENDPOINT = "http://host.docker.internal:20128/v1"
DEFAULT_SEARCH_PROVIDERS = ("tavily", "exa")
DEFAULT_FETCH_PROVIDERS = ("jina-reader", "firecrawl", "tavily", "exa")


def _split_providers(value: str, default: Iterable[str]) -> List[str]:
    providers = [item.strip() for item in value.split(",") if item.strip()]
    return providers or list(default)


def _endpoint() -> str:
    endpoint = os.getenv("NINEROUTER_ENDPOINT", DEFAULT_ENDPOINT).strip().rstrip("/")
    if endpoint and not Path("/.dockerenv").exists():
        endpoint = endpoint.replace("host.docker.internal", "127.0.0.1")
    return endpoint


def _api_key() -> str:
    return os.getenv("NINEROUTER_API_KEY", "").strip()


def _post(path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    import httpx

    key = _api_key()
    if not key:
        raise ValueError("NINEROUTER_API_KEY environment variable not set")

    url = f"{_endpoint()}/{path.lstrip('/')}"
    response = httpx.post(
        url,
        json=payload,
        headers={"Authorization": f"Bearer {key}"},
        timeout=60,
    )
    response.raise_for_status()
    return response.json()


def _normalize_search(raw: Dict[str, Any]) -> Dict[str, Any]:
    web_results = []
    for index, result in enumerate(raw.get("results", [])):
        if not isinstance(result, dict):
            continue
        web_results.append(
            {
                "title": result.get("title", "") or "",
                "url": result.get("url", "") or "",
                "description": (
                    result.get("snippet")
                    or result.get("description")
                    or result.get("content")
                    or ""
                ),
                "position": result.get("position") or index + 1,
            }
        )
    return {"success": True, "data": {"web": web_results}}


def _content_text(content: Any) -> str:
    if isinstance(content, dict):
        return content.get("text", "") or ""
    if isinstance(content, str):
        return content
    return ""


def _normalize_document(raw: Dict[str, Any], fallback_url: str) -> Dict[str, Any]:
    url = raw.get("url") or fallback_url
    title = raw.get("title") or ""
    content = _content_text(raw.get("content"))
    metadata = raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {}
    metadata = {**metadata, "sourceURL": url, "title": title}
    return {
        "url": url,
        "title": title,
        "content": content,
        "raw_content": content,
        "metadata": metadata,
    }


class NineRouterWebSearchProvider(WebSearchProvider):
    """9Router search + fetch provider."""

    @property
    def name(self) -> str:
        return "9router"

    @property
    def display_name(self) -> str:
        return "9Router"

    def is_available(self) -> bool:
        return bool(_api_key() and _endpoint())

    def supports_search(self) -> bool:
        return True

    def supports_extract(self) -> bool:
        return True

    def _search_providers(self) -> List[str]:
        return _split_providers(
            os.getenv("NINEROUTER_SEARCH_PROVIDERS", ""),
            DEFAULT_SEARCH_PROVIDERS,
        )

    def _fetch_providers(self) -> List[str]:
        return _split_providers(
            os.getenv("NINEROUTER_FETCH_PROVIDERS", ""),
            DEFAULT_FETCH_PROVIDERS,
        )

    def search(self, query: str, limit: int = 5) -> Dict[str, Any]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return {"success": False, "error": "Interrupted"}

            last_error: Optional[str] = None
            for provider in self._search_providers():
                try:
                    raw = _post(
                        "search",
                        {"provider": provider, "query": query, "limit": limit},
                    )
                    return _normalize_search(raw)
                except Exception as exc:  # noqa: BLE001
                    last_error = f"{provider}: {exc}"
                    logger.warning("9Router search via %s failed: %s", provider, exc)
            return {"success": False, "error": f"9Router search failed: {last_error}"}
        except ValueError as exc:
            return {"success": False, "error": str(exc)}

    def extract(self, urls: List[str], **kwargs: Any) -> List[Dict[str, Any]]:
        try:
            from tools.interrupt import is_interrupted

            if is_interrupted():
                return [
                    {"url": url, "title": "", "content": "", "error": "Interrupted"}
                    for url in urls
                ]

            results: List[Dict[str, Any]] = []
            for url in urls:
                results.append(self._fetch_one(url))
            return results
        except ValueError as exc:
            return [
                {"url": url, "title": "", "content": "", "error": str(exc)}
                for url in urls
            ]

    def _fetch_one(self, url: str) -> Dict[str, Any]:
        last_error: Optional[str] = None
        for provider in self._fetch_providers():
            try:
                raw = _post("web/fetch", {"provider": provider, "url": url})
                return _normalize_document(raw, fallback_url=url)
            except Exception as exc:  # noqa: BLE001
                last_error = f"{provider}: {exc}"
                logger.warning("9Router fetch via %s failed: %s", provider, exc)
        return {
            "url": url,
            "title": "",
            "content": "",
            "raw_content": "",
            "error": f"9Router fetch failed: {last_error}",
            "metadata": {"sourceURL": url},
        }

    def get_setup_schema(self) -> Dict[str, Any]:
        return {
            "name": "9Router",
            "badge": "local proxy",
            "tag": "Routes web search/fetch through local 9Router providers.",
            "env_vars": [
                {
                    "key": "NINEROUTER_API_KEY",
                    "prompt": "9Router API key",
                    "url": "http://127.0.0.1:20128",
                },
                {
                    "key": "NINEROUTER_ENDPOINT",
                    "prompt": "9Router endpoint",
                    "url": "http://127.0.0.1:20128/v1",
                },
            ],
        }
