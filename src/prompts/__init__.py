"""Versioned prompt loader for the extraction graph.

Usage::

    from src.prompts import load_prompt

    text = load_prompt("classify_layout", version=1)
"""

from __future__ import annotations

from pathlib import Path

_PROMPTS_DIR = Path(__file__).parent


def _parse_version(frontmatter: str) -> int:
    """Extract the integer ``version:`` value from a YAML frontmatter block."""
    for line in frontmatter.splitlines():
        stripped = line.strip()
        if stripped.startswith("version:"):
            value = stripped.split(":", 1)[1].strip()
            return int(value)
    raise ValueError("frontmatter missing 'version:' field")


def load_prompt(name: str, version: int = 1) -> str:
    """Return the body of ``src/prompts/{name}.md`` after frontmatter validation.

    The file must start with a YAML frontmatter block delimited by ``---``.
    The ``version:`` field inside the frontmatter must match *version*.

    Raises
    ------
    FileNotFoundError
        When the prompt file does not exist.
    ValueError
        When the frontmatter is missing, malformed, or the declared version
        does not match *version*.
    """
    path = _PROMPTS_DIR / f"{name}.md"
    raw = path.read_text(encoding="utf-8")
    if not raw.startswith("---\n"):
        raise ValueError(
            f"{path}: expected YAML frontmatter delimited by '---\\n' at the start of the file"
        )
    parts = raw.split("---\n", 2)
    if len(parts) < 3:
        raise ValueError(f"{path}: frontmatter block is not properly closed with '---'")
    _, frontmatter, body = parts
    declared = _parse_version(frontmatter)
    if declared != version:
        raise ValueError(f"{path}: frontmatter version={declared} but caller requested v{version}")
    return body.strip()
