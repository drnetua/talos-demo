import pytest

from notes.safe_text import needs_marker, safe_cell

PREFIXES = ["", " ", "\t", "\r", "\n", "\x00", "\x1f", "\x7f", "\x85", " ", " \t\r\n"]


@pytest.mark.parametrize("prefix", PREFIXES)
@pytest.mark.parametrize("trigger", ["=", "+", "-", "@"])
def test_formula_like_values_are_marked(prefix: str, trigger: str) -> None:
    value = f"{prefix}{trigger}1+1"
    assert needs_marker(value)
    assert safe_cell(value) == "'" + value
    assert safe_cell(value)[1:] == value


@pytest.mark.parametrize(
    "value", ["", "Meeting", "\tindented", "\nMeeting", "  ", "'=1", "a=1", "\t\n", "1+1"]
)
def test_ordinary_values_are_unmarked(value: str) -> None:
    assert not needs_marker(value)
    assert safe_cell(value) == value
