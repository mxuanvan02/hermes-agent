"""Load Hermes subagent definitions installed under ``HERMES_HOME``.

Agent definitions are Markdown files with YAML frontmatter.  The loader keeps
the definition intact because the frontmatter and prompt body together form
the agent contract authored by ECC.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

from agent.skill_utils import parse_frontmatter
from hermes_constants import get_hermes_home


_AGENT_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_MAX_DEFINITION_BYTES = 512 * 1024


@dataclass(frozen=True)
class AgentDefinition:
    """Validated ECC definition plus the runtime metadata Hermes can honor."""

    name: str
    description: str
    tools: tuple[str, ...]
    model: Optional[str]
    raw: str


def get_agent_definitions_dir() -> Path:
    """Return the active Hermes agent-definition directory."""
    return get_hermes_home() / "agents"


def list_agent_definitions() -> list[str]:
    """Return installed definition names in deterministic order."""
    root = get_agent_definitions_dir()
    try:
        return sorted(
            path.stem
            for path in root.glob("*.md")
            if path.is_file() and not path.is_symlink()
            and _AGENT_NAME_RE.fullmatch(path.stem)
        )
    except OSError:
        return []


def load_agent_definition(agent_name: Optional[str]) -> Optional[str]:
    """Load one complete definition, or return ``None`` when unspecified.

    Names are constrained before they are used to construct a path.  Symlinked
    definitions are rejected so an agent request cannot escape the installed
    definitions directory.
    """
    if agent_name is None or not str(agent_name).strip():
        return None

    name = str(agent_name).strip().lower()
    if not _AGENT_NAME_RE.fullmatch(name):
        raise ValueError(
            f"Invalid agent_name {agent_name!r}; use an installed name such as 'planner'."
        )

    root = get_agent_definitions_dir()
    path = root / f"{name}.md"
    try:
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(path)
        if path.stat().st_size > _MAX_DEFINITION_BYTES:
            raise ValueError(
                f"Agent definition '{name}' is too large to load "
                f"(limit: {_MAX_DEFINITION_BYTES} bytes)."
            )
        return path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise ValueError(
            f"Unknown agent definition '{name}'. Installed definitions: "
            f"{', '.join(list_agent_definitions()) or '(none)'}"
        ) from exc
    except UnicodeError as exc:
        raise ValueError(f"Agent definition '{name}' is not valid UTF-8.") from exc


def load_agent_definition_metadata(
    agent_name: Optional[str],
) -> Optional[AgentDefinition]:
    """Load a complete definition and expose its safe frontmatter metadata."""
    raw = load_agent_definition(agent_name)
    if raw is None:
        return None

    name = str(agent_name).strip().lower()
    frontmatter, _ = parse_frontmatter(raw)
    description = frontmatter.get("description", "")
    model = frontmatter.get("model")
    tools_value: Any = frontmatter.get("tools", ())

    if isinstance(tools_value, str):
        tools = tuple(
            item.strip()
            for item in tools_value.split(",")
            if item.strip()
        )
    elif isinstance(tools_value, (list, tuple)):
        tools = tuple(
            str(item).strip()
            for item in tools_value
            if str(item).strip()
        )
    else:
        tools = ()

    return AgentDefinition(
        name=name,
        description=str(description).strip() if description is not None else "",
        tools=tools,
        model=str(model).strip() if model is not None and str(model).strip() else None,
        raw=raw,
    )


__all__ = [
    "get_agent_definitions_dir",
    "list_agent_definitions",
    "load_agent_definition",
    "load_agent_definition_metadata",
    "AgentDefinition",
]
