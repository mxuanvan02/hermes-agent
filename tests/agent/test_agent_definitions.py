"""Tests for installed Hermes agent definitions."""

from pathlib import Path

import pytest

from agent import agent_definitions


def _write_definition(root: Path, name: str = "planner") -> str:
    raw = (
        "---\n"
        f"name: {name}\n"
        "description: Planning specialist\n"
        "tools: Read, Grep, Glob\n"
        "model: opus\n"
        "---\n\n"
        "## Your Role\n\nCreate an implementation plan.\n"
    )
    root.mkdir(parents=True, exist_ok=True)
    (root / f"{name}.md").write_text(raw, encoding="utf-8")
    return raw


def test_load_agent_definition_metadata_preserves_complete_definition(tmp_path, monkeypatch):
    definitions = tmp_path / "agents"
    raw = _write_definition(definitions)
    monkeypatch.setattr(agent_definitions, "get_agent_definitions_dir", lambda: definitions)

    definition = agent_definitions.load_agent_definition_metadata("planner")

    assert definition is not None
    assert definition.name == "planner"
    assert definition.description == "Planning specialist"
    assert definition.tools == ("Read", "Grep", "Glob")
    assert definition.model == "opus"
    assert definition.raw == raw
    assert "## Your Role" in definition.raw


@pytest.mark.parametrize("name", ["../planner", "planner.md", "Planner!"])
def test_load_agent_definition_rejects_invalid_names(tmp_path, monkeypatch, name):
    monkeypatch.setattr(
        agent_definitions,
        "get_agent_definitions_dir",
        lambda: tmp_path / "agents",
    )

    with pytest.raises(ValueError, match="Invalid agent_name"):
        agent_definitions.load_agent_definition(name)


def test_load_agent_definition_reports_unknown_name(tmp_path, monkeypatch):
    definitions = tmp_path / "agents"
    definitions.mkdir()
    monkeypatch.setattr(agent_definitions, "get_agent_definitions_dir", lambda: definitions)

    with pytest.raises(ValueError, match="Unknown agent definition 'planner'"):
        agent_definitions.load_agent_definition("planner")
