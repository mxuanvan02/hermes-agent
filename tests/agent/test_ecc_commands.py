"""Tests for the dynamic ECC command bridge."""

import re
from pathlib import Path

import pytest

from agent import ecc_commands


def _write_command(root: Path, name: str, body: str) -> None:
    (root / f"{name}.md").write_text(body, encoding="utf-8")


def test_production_catalog_contains_all_ecc_commands(monkeypatch):
    """The checked-out ECC catalog is the source for all 94 workflows."""
    if not ecc_commands.ECC_COMMANDS_DIR.is_dir():
        pytest.skip("ECC checkout is not available")

    # The shared test fixture isolates HERMES_HOME. Select the checked-out
    # catalog explicitly so this production-catalog assertion does not depend
    # on the isolated runtime profile.
    monkeypatch.setenv("ECC_COMMANDS_DIR", str(ecc_commands.ECC_COMMANDS_DIR))
    catalog = ecc_commands.scan_ecc_commands()

    assert len(catalog) == 94
    assert all(key.startswith("ecc:") for key in catalog)


def test_production_telegram_menu_keeps_core_and_curates_ecc(monkeypatch):
    """Core commands stay visible while the full ECC catalog remains resolvable."""
    if not ecc_commands.ECC_COMMANDS_DIR.is_dir():
        pytest.skip("ECC checkout is not available")

    monkeypatch.setenv("ECC_COMMANDS_DIR", str(ecc_commands.ECC_COMMANDS_DIR))
    from hermes_cli.commands import telegram_bot_commands, telegram_menu_commands

    menu, hidden = telegram_menu_commands(max_commands=100)
    names = {name for name, _description in menu}
    core_names = {name for name, _description in telegram_bot_commands()}
    catalog = ecc_commands.get_ecc_commands()
    expected = {str(entry["telegram_name"]) for entry in catalog.values()}
    visible_ecc = names & expected

    assert core_names <= names
    assert len(menu) == 100
    assert len(visible_ecc) == 100 - len(core_names)
    assert hidden == len(expected) - len(visible_ecc)
    assert len(expected) == 94
    assert all(
        ecc_commands.resolve_ecc_command(alias) is not None
        for alias in expected
    )


def test_resolves_canonical_and_telegram_aliases(tmp_path, monkeypatch):
    monkeypatch.setattr(ecc_commands, "ECC_COMMANDS_DIR", tmp_path)
    _write_command(tmp_path, "build-fix", "# Build and fix\n\nRun the workflow.")

    assert ecc_commands.resolve_ecc_command("ecc:build-fix")["canonical"] == "ecc:build-fix"
    assert ecc_commands.resolve_ecc_command("ecc_build_fix")["canonical"] == "ecc:build-fix"
    assert ecc_commands.resolve_ecc_command("/ecc_build_fix")["telegram_name"] == "ecc_build_fix"


def test_build_message_injects_arguments_without_executing_markdown(tmp_path, monkeypatch):
    monkeypatch.setattr(ecc_commands, "ECC_COMMANDS_DIR", tmp_path)
    _write_command(
        tmp_path,
        "research-workflow",
        "---\ndescription: Research workflow\nargument-hint: <topic>\n---\n"
        "# Research\n\nTopic: $ARGUMENTS\n\n"
        "Do not run `$(touch SHOULD_NOT_EXIST)` while loading this file.\n",
    )

    message = ecc_commands.build_ecc_command_message(
        "/ecc_research_workflow",
        "quantum error correction",
    )

    assert message is not None
    assert "Topic: quantum error correction" in message
    assert "SHOULD_NOT_EXIST" in message
    assert not (tmp_path / "SHOULD_NOT_EXIST").exists()
    assert "[ECC argument hint: <topic>]" in message


def test_empty_arguments_are_explicit(tmp_path, monkeypatch):
    monkeypatch.setattr(ecc_commands, "ECC_COMMANDS_DIR", tmp_path)
    _write_command(tmp_path, "minimal", "# Minimal\n\n$ARGUMENTS")

    message = ecc_commands.build_ecc_command_message("ecc:minimal")

    assert message is not None
    assert "[User instruction: (none provided)]" in message
    assert "$ARGUMENTS" not in message


def test_telegram_aliases_are_valid_and_within_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(ecc_commands, "ECC_COMMANDS_DIR", tmp_path)
    _write_command(tmp_path, "security-review", "# Security review")
    _write_command(tmp_path, "frontend-patterns", "# Frontend patterns")

    entries = ecc_commands.ecc_telegram_menu_entries()

    assert entries == [
        ("ecc_frontend_patterns", "Frontend patterns"),
        ("ecc_security_review", "Security review"),
    ]
    valid_name = re.compile(r"^[a-z0-9_]+$")
    assert all(valid_name.fullmatch(name) and len(name) <= 32 for name, _ in entries)
