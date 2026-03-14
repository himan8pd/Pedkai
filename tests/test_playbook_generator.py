import os
os.environ.setdefault("SECRET_KEY", "test-secret")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_stub.db")

import asyncio
import pytest
from backend.app.services.playbook_generator import (
    PlaybookGenerator,
    Playbook,
    PlaybookStep,
    get_playbook_generator,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously."""
    return asyncio.run(coro)


@pytest.fixture
def generator():
    return PlaybookGenerator()


def _make_sleeping_cell_pattern():
    return {
        "fault_pattern": "sleeping_cell",
        "avg_confidence": 0.95,
        "decision_ids": ["d1", "d2", "d3"],
    }


def _make_unknown_pattern():
    return {
        "fault_pattern": "unknown_xyz_pattern",
        "avg_confidence": 0.91,
        "decision_ids": ["d4"],
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_playbook_has_non_empty_title(generator):
    """Playbook has a title attribute that contains text."""
    playbook = run(generator.generate_playbook(_make_sleeping_cell_pattern(), "tenant-1"))
    assert isinstance(playbook.title, str)
    assert len(playbook.title.strip()) > 0


def test_to_markdown_returns_string_with_steps(generator):
    """to_markdown() returns a string containing step information."""
    playbook = run(generator.generate_playbook(_make_sleeping_cell_pattern(), "tenant-1"))
    md = playbook.to_markdown()
    assert isinstance(md, str)
    assert "Step" in md
    assert len(md) > 0


def test_to_dict_has_expected_keys(generator):
    """to_dict() returns a dict with the expected keys."""
    playbook = run(generator.generate_playbook(_make_sleeping_cell_pattern(), "tenant-1"))
    d = playbook.to_dict()
    for key in ("playbook_id", "title", "steps", "fault_pattern", "domain", "confidence"):
        assert key in d, f"Expected key '{key}' in to_dict() result"
    assert isinstance(d["steps"], list)


def test_automated_steps_marked_in_output(generator):
    """Automated steps are marked in the markdown output."""
    playbook = run(generator.generate_playbook(_make_sleeping_cell_pattern(), "tenant-1"))
    automated_steps = [s for s in playbook.steps if s.automated]
    assert len(automated_steps) >= 1, "Expected at least one automated step in sleeping_cell template"
    md = playbook.to_markdown()
    # The implementation tags automated steps with "(Pedk.ai automated)"
    assert "automated" in md.lower() or "Pedk.ai" in md


def test_sleeping_cell_playbook_uses_template_steps(generator):
    """Generating a sleeping_cell playbook uses the template steps (not generic)."""
    playbook = run(generator.generate_playbook(_make_sleeping_cell_pattern(), "tenant-1"))
    # Template title for sleeping_cell
    assert "Sleeping Cell" in playbook.title
    assert playbook.domain == "RAN"
    # Template has exactly 5 steps
    assert len(playbook.steps) == 5


def test_unknown_pattern_returns_generic_playbook(generator):
    """Generating an unknown pattern returns a playbook with generic steps."""
    playbook = run(generator.generate_playbook(_make_unknown_pattern(), "tenant-1"))
    assert playbook is not None
    assert isinstance(playbook, Playbook)
    # Generic title uses the pattern name
    assert playbook.title is not None
    assert len(playbook.steps) > 0


def test_get_playbook_by_fault_pattern_known_returns_non_none(generator):
    """get_playbook_by_fault_pattern for a known pattern returns a non-None Playbook."""
    playbook = run(generator.get_playbook_by_fault_pattern("sleeping_cell"))
    assert playbook is not None
    assert isinstance(playbook, Playbook)
    assert playbook.fault_pattern == "sleeping_cell"


def test_get_playbook_by_fault_pattern_unknown_returns_none(generator):
    """get_playbook_by_fault_pattern for an unknown pattern returns None gracefully."""
    playbook = run(generator.get_playbook_by_fault_pattern("unknown_xyz_pattern_that_has_no_template"))
    assert playbook is None
