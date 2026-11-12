"""Export-only safe text: neutralise spreadsheet formula prefixes without touching stored notes."""

import unicodedata

FORMULA_TRIGGERS = frozenset("=+-@")
MARKER = "'"


def _is_skippable(char: str) -> bool:
    return char.isspace() or unicodedata.category(char) == "Cc"


def needs_marker(cell: str) -> bool:
    """True when the first char after leading whitespace/control characters is a formula trigger."""
    for char in cell:
        if _is_skippable(char):
            continue
        return char in FORMULA_TRIGGERS
    return False


def safe_cell(cell: str) -> str:
    """Prefix one apostrophe to formula-like cells; return other cells unchanged."""
    return MARKER + cell if needs_marker(cell) else cell
