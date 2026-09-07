"""Dynamic bridge for the trusted ECC Markdown command catalog.

ECC commands are authored as Claude Code-oriented Markdown workflows.  Hermes
does not execute those files as shell scripts; it loads the workflow text into
the normal agent turn.  The bridge keeps the dynamic catalog separate from
the frozen native command registry while exposing stable canonical names for
hooks and access control.
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path
from typing import Any, Optional

from agent.skill_utils import parse_frontmatter

logger = logging.getLogger(__name__)

# The checkout is trusted, but its location is deployment-specific. Keep the
# module constant for backwards-compatible tests and allow launchers to point
# at a different checkout or a runtime-local catalog.
_DEFAULT_ECC_COMMANDS_DIR = Path(__file__).resolve().parents[2] / "ECC" / "commands"
ECC_COMMANDS_DIR = _DEFAULT_ECC_COMMANDS_DIR
_SLUG_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
_CANONICAL_RE = re.compile(r"^ecc:([a-z0-9]+(?:-[a-z0-9]+)*)$")
_TELEGRAM_RE = re.compile(r"^ecc_([a-z0-9]+(?:_[a-z0-9]+)*)$")

_catalog: dict[str, dict[str, Any]] = {}
_catalog_root: Optional[Path] = None
_catalog_signature: Optional[tuple[tuple[str, int, int], ...]] = None


def _configured_commands_dir() -> Path:
    """Resolve the ECC catalog without coupling Hermes to one workstation."""
    env_dir = os.environ.get("ECC_COMMANDS_DIR", "").strip()
    if env_dir:
        return Path(env_dir).expanduser()
    # A test or embedding application may replace the public module constant.
    if ECC_COMMANDS_DIR != _DEFAULT_ECC_COMMANDS_DIR:
        return ECC_COMMANDS_DIR.expanduser()
    hermes_home = os.environ.get("HERMES_HOME", "").strip()
    if hermes_home:
        # HERMES_HOME is an explicit runtime boundary. Do not fall back to a
        # developer checkout when that profile has no ECC catalog; doing so
        # leaks host-local commands into isolated profiles and tests.
        runtime_dir = Path(hermes_home).expanduser() / "ecc" / "commands"
        return runtime_dir
    return ECC_COMMANDS_DIR.expanduser()


def _normalise_description(value: Any, body: str, slug: str) -> str:
    if isinstance(value, (list, tuple)):
        value = " ".join(str(item) for item in value)
    description = str(value or "").strip()
    if description:
        return description
    for line in body.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.startswith("#"):
            heading = candidate.lstrip("#").strip()
            if heading:
                return heading[:160]
            continue
        return candidate[:160]
    return f"Run the ECC {slug} workflow"


def _normalise_argument_hint(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return " | ".join(str(item) for item in value)
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    return str(value).strip()


def _root_files(root: Path) -> list[Path]:
    try:
        root = root.resolve()
        if not root.is_dir():
            return []
        return sorted(
            path for path in root.glob("*.md")
            if path.is_file() and not path.is_symlink()
        )
    except OSError:
        return []


def _filesystem_signature(files: list[Path]) -> tuple[tuple[str, int, int], ...]:
    signature = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((path.name, stat.st_mtime_ns, stat.st_size))
    return tuple(signature)


def scan_ecc_commands() -> dict[str, dict[str, Any]]:
    """Scan the trusted ECC commands directory and return canonical entries."""
    global _catalog, _catalog_root, _catalog_signature

    root = _configured_commands_dir()
    files = _root_files(root)
    signature = _filesystem_signature(files)
    resolved_root = root.resolve() if root.exists() else root
    if (
        _catalog_root == resolved_root
        and _catalog_signature == signature
    ):
        return _catalog

    catalog: dict[str, dict[str, Any]] = {}
    aliases: set[str] = set()
    for path in files:
        slug = path.stem.lower()
        if not _SLUG_RE.fullmatch(slug):
            logger.warning("Skipping ECC command with invalid slug: %s", path.name)
            continue
        canonical = f"ecc:{slug}"
        telegram_name = f"ecc_{slug.replace('-', '_')}"
        if canonical in catalog or telegram_name in aliases:
            logger.warning("Skipping colliding ECC command: %s", path.name)
            continue
        try:
            content = path.read_text(encoding="utf-8")
            frontmatter, body = parse_frontmatter(content)
        except (OSError, UnicodeError) as exc:
            logger.warning("Skipping unreadable ECC command %s: %s", path, exc)
            continue
        description = _normalise_description(
            frontmatter.get("description"), body, slug
        )
        entry = {
            "slug": slug,
            "canonical": canonical,
            "telegram_name": telegram_name,
            "description": description,
            "argument_hint": _normalise_argument_hint(
                frontmatter.get("argument-hint")
            ),
            "path": path,
            "content": content,
            "body": body,
        }
        catalog[canonical] = entry
        aliases.add(telegram_name)

    _catalog = catalog
    _catalog_root = resolved_root
    _catalog_signature = signature
    return _catalog


def get_ecc_commands() -> dict[str, dict[str, Any]]:
    """Return the cached ECC command catalog, rescanning changed files."""
    return scan_ecc_commands()


def resolve_ecc_command(command: str | None) -> Optional[dict[str, Any]]:
    """Resolve canonical ``ecc:<slug>`` and Telegram ``ecc_<slug>`` names."""
    raw = (command or "").strip().lstrip("/").lower()
    if not raw:
        return None
    canonical_match = _CANONICAL_RE.fullmatch(raw)
    if canonical_match:
        return get_ecc_commands().get(f"ecc:{canonical_match.group(1)}")
    telegram_match = _TELEGRAM_RE.fullmatch(raw)
    if telegram_match:
        slug = telegram_match.group(1).replace("_", "-")
        return get_ecc_commands().get(f"ecc:{slug}")
    return None


def build_ecc_command_message(
    command: str,
    user_instruction: str = "",
    task_id: str | None = None,
) -> Optional[str]:
    """Build the agent prompt for an ECC command invocation.

    ``task_id`` is accepted for parity with skill dispatch and future usage
    tracking. ECC Markdown remains inert workflow text; no inline shell or
    other directive is executed while loading it.
    """
    del task_id
    entry = resolve_ecc_command(command)
    if not entry:
        return None

    arguments = (user_instruction or "").strip() or "(none provided)"
    content = str(entry["body"]).strip()
    content = content.replace("$ARGUMENTS", arguments)
    argument_hint = entry.get("argument_hint")
    parts = [
        f'[IMPORTANT: The user invoked the ECC workflow "{entry["canonical"]}".]',
        "Follow the workflow instructions below as guidance for this agent turn.",
        "The Markdown is workflow text, not an instruction to execute shell commands automatically.",
        "",
        content,
        "",
        f'[ECC command source: {entry["path"]}]',
    ]
    if argument_hint:
        parts.extend([f"[ECC argument hint: {argument_hint}]"])
    parts.extend(["", f"[User instruction: {arguments}]"])
    return "\n".join(parts)


def ecc_telegram_menu_entries(desc_limit: int = 40) -> list[tuple[str, str]]:
    """Return valid Telegram command entries for the entire ECC catalog."""
    entries = []
    for item in get_ecc_commands().values():
        description = str(item["description"])
        if len(description) > desc_limit:
            description = description[: desc_limit - 3] + "..."
        entries.append((str(item["telegram_name"]), description))
    return entries
