"""Terminal display-width helpers with East Asian width awareness."""

from __future__ import annotations

import re
import unicodedata


def cell_width(char: str) -> int:
    """Return the terminal cell width of one character."""

    if not char:
        return 0
    if char in {"\n", "\r"}:
        return 0
    if unicodedata.combining(char):
        return 0
    if unicodedata.east_asian_width(char) in {"W", "F"}:
        return 2
    return 1


def text_width(text: str) -> int:
    """Return the rendered terminal width of a string."""

    return sum(cell_width(char) for char in text)


def clip_text(text: str, width: int) -> str:
    """Clip text to fit a display width, adding ASCII ellipsis when needed."""

    if width <= 0:
        return ""
    if text_width(text) <= width:
        return text

    ellipsis = "..." if width >= 3 else "." * width
    limit = max(0, width - text_width(ellipsis))
    current_width = 0
    clipped: list[str] = []
    for char in text:
        char_width = cell_width(char)
        if current_width + char_width > limit:
            break
        clipped.append(char)
        current_width += char_width
    return "".join(clipped) + ellipsis


def pad_text(text: str, width: int) -> str:
    """Pad text with spaces up to the requested display width."""

    visible = clip_text(text, width)
    return visible + (" " * max(0, width - text_width(visible)))


def wrap_text(text: str, width: int) -> list[str]:
    """Wrap text to a target display width, keeping ASCII words together when possible."""

    if width <= 0:
        return [text]
    if not text:
        return [""]

    tokens = re.findall(r"\S+\s*|\s+", text)
    wrapped: list[str] = []
    current = ""
    current_width = 0

    for token in tokens:
        token_width = text_width(token)
        if current and current_width + token_width > width:
            wrapped.append(current.rstrip())
            current = ""
            current_width = 0

        if token_width <= width:
            if not current and token.isspace():
                continue
            current += token
            current_width += token_width
            continue

        if current:
            wrapped.append(current.rstrip())
            current = ""
            current_width = 0

        chunk = ""
        chunk_width = 0
        for char in token:
            char_width = cell_width(char)
            if chunk and chunk_width + char_width > width:
                wrapped.append(chunk.rstrip())
                chunk = "" if char.isspace() else char
                chunk_width = 0 if char.isspace() else char_width
                continue

            if not chunk and char.isspace():
                continue
            chunk += char
            chunk_width += char_width

        current = chunk.lstrip()
        current_width = text_width(current)

    if current or not wrapped:
        wrapped.append(current.rstrip())

    return wrapped or [""]
