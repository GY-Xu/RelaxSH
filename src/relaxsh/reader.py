"""Core TXT reader logic for RelaxSH."""

from __future__ import annotations

import os
import re
import select
import shutil
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from relaxsh.display import clip_text, text_width, wrap_text
from relaxsh.i18n import tr


DEFAULT_ENCODINGS = ("utf-8-sig", "utf-8", "gb18030")
FALLBACK_TERMINAL_SIZE = os.terminal_size((88, 28))
MIN_WIDTH = 20
MIN_LINES = 3
ESCAPE_INITIAL_TIMEOUT = 0.60
ESCAPE_CHUNK_TIMEOUT = 0.12
ANSI_REDRAW_PREFIX = "\x1b[H\x1b[J"
_WINDOWS_VT_REDRAW_ENABLED: bool | None = None
CHAPTER_PATTERNS = (
    re.compile(r"^\s*第[\d零〇一二两三四五六七八九十百千万]+[章节卷回集部篇][^\n]{0,48}$"),
    re.compile(r"^\s*(chapter|chap\.)\s+[\divxlcdm]+[^\n]{0,48}$", re.IGNORECASE),
    re.compile(r"^\s*(prologue|epilogue|preface)\b[^\n]{0,48}$", re.IGNORECASE),
)


class ReaderError(Exception):
    """Base error raised for reader-related failures."""


@dataclass
class DisplayLine:
    """One wrapped display line and the source offsets it covers."""

    text: str
    start_offset: int
    end_offset: int


@dataclass
class Page:
    """One rendered page."""

    lines: list[str]
    start_offset: int
    end_offset: int


@dataclass
class Chapter:
    """Detected chapter heading within the source text."""

    title: str
    start_offset: int


@dataclass
class BookmarkEntry:
    """One bookmark displayed inside the reader."""

    id: str
    offset: int
    created_at: str
    excerpt: str
    note: str = ""


def decode_posix_escape_sequence(sequence: str) -> str:
    """Decode a POSIX escape sequence into a navigation command."""

    if not sequence:
        return "escape"

    arrow_map = {
        "A": "up",
        "B": "down",
        "C": "right",
        "D": "left",
        "H": "g",
        "F": "G",
    }
    prefix = sequence[0]
    final = sequence[-1]

    if prefix == "O":
        return arrow_map.get(final, "escape")

    if prefix != "[":
        return "escape"

    if final in arrow_map:
        return arrow_map[final]

    if final == "~":
        digits = "".join(character for character in sequence[1:-1] if character.isdigit())
        return {
            "1": "g",
            "4": "G",
            "7": "g",
            "8": "G",
        }.get(digits, "escape")

    return "escape"


def clear_screen() -> None:
    """Clear the active terminal screen."""

    os.system("cls" if os.name == "nt" else "clear")


def _enable_windows_virtual_terminal() -> bool:
    """Enable ANSI escape handling on Windows consoles when available."""

    global _WINDOWS_VT_REDRAW_ENABLED

    if _WINDOWS_VT_REDRAW_ENABLED is not None:
        return _WINDOWS_VT_REDRAW_ENABLED

    try:
        import ctypes

        kernel32 = ctypes.windll.kernel32
        handle = kernel32.GetStdHandle(-11)
        if handle in (0, -1):
            _WINDOWS_VT_REDRAW_ENABLED = False
            return False

        mode = ctypes.c_uint()
        if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            _WINDOWS_VT_REDRAW_ENABLED = False
            return False

        vt_mode = mode.value | 0x0004
        if mode.value == vt_mode:
            _WINDOWS_VT_REDRAW_ENABLED = True
            return True

        _WINDOWS_VT_REDRAW_ENABLED = bool(kernel32.SetConsoleMode(handle, vt_mode))
        return _WINDOWS_VT_REDRAW_ENABLED
    except Exception:
        _WINDOWS_VT_REDRAW_ENABLED = False
        return False


def _supports_ansi_screen_redraw() -> bool:
    """Return whether the current terminal supports cursor-home redraws."""

    if not sys.stdout.isatty():
        return False

    if os.name == "nt":
        return _enable_windows_virtual_terminal()

    term = os.environ.get("TERM", "")
    return term.lower() != "dumb"


def render_screen(screen: str) -> None:
    """Render one full-screen frame with minimal flicker when possible."""

    if _supports_ansi_screen_redraw():
        sys.stdout.write(ANSI_REDRAW_PREFIX)
        sys.stdout.write(screen)
        sys.stdout.flush()
        return

    clear_screen()
    print(screen, end="", flush=True)


def normalize_text(text: str) -> str:
    """Normalize line endings and trim trailing whitespace."""

    normalized = text.replace("\r\n", "\n").replace("\r", "\n").replace("\t", "    ")
    return "\n".join(line.rstrip() for line in normalized.split("\n"))


def resolve_content_width(width: int | None) -> int:
    """Resolve the display width used for pagination."""

    if width is not None:
        if width < MIN_WIDTH:
            raise ReaderError(f"--width must be at least {MIN_WIDTH}.")
        return width

    terminal_width = shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).columns
    return max(MIN_WIDTH, terminal_width - 6)


def resolve_lines_per_page(lines_per_page: int | None) -> int:
    """Resolve how many content lines should appear on each page."""

    if lines_per_page is not None:
        if lines_per_page < MIN_LINES:
            raise ReaderError(f"--lines must be at least {MIN_LINES}.")
        return lines_per_page

    terminal_height = shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).lines
    return max(MIN_LINES, terminal_height - 7)


def load_text_with_encoding(path: Path, encoding: str | None = None) -> tuple[str, str]:
    """Load a text file and return both content and the encoding that succeeded."""

    if not path.exists():
        raise ReaderError(f"File not found: {path}")
    if not path.is_file():
        raise ReaderError(f"Expected a file path, got: {path}")

    if encoding:
        try:
            return path.read_text(encoding=encoding), encoding
        except LookupError as exc:
            raise ReaderError(f"Unknown encoding: {encoding}") from exc
        except UnicodeDecodeError as exc:
            raise ReaderError(f"Failed to decode {path} with {encoding}.") from exc

    decode_errors: list[str] = []
    for candidate in DEFAULT_ENCODINGS:
        try:
            return path.read_text(encoding=candidate), candidate
        except UnicodeDecodeError:
            decode_errors.append(candidate)

    tried = ", ".join(decode_errors) if decode_errors else ", ".join(DEFAULT_ENCODINGS)
    raise ReaderError(f"Unable to decode {path}. Tried: {tried}.")


def load_text(path: Path, encoding: str | None = None) -> str:
    """Load a text file with lightweight encoding fallback."""

    text, _ = load_text_with_encoding(path, encoding=encoding)
    return text


def load_demo_text() -> str:
    """Load the bundled demo text."""

    demo_path = Path(__file__).resolve().parent / "data" / "demo.txt"
    return demo_path.read_text(encoding="utf-8")


def build_display_lines(text: str, width: int) -> tuple[str, list[DisplayLine]]:
    """Wrap normalized text into display lines while keeping source offsets."""

    normalized = normalize_text(text)
    display_lines: list[DisplayLine] = []
    raw_lines = normalized.split("\n")
    cursor = 0

    for index, raw_line in enumerate(raw_lines):
        if raw_line:
            wrapped = wrap_text(raw_line, width) or [""]
            consumed = 0
            for chunk in wrapped:
                start_offset = cursor + consumed
                consumed += len(chunk)
                end_offset = cursor + consumed
                display_lines.append(DisplayLine(chunk, start_offset, end_offset))
        else:
            display_lines.append(DisplayLine("", cursor, cursor))

        cursor += len(raw_line)
        if index < len(raw_lines) - 1:
            cursor += 1

    return normalized, display_lines or [DisplayLine("", 0, 0)]


def paginate_lines(lines: list[DisplayLine], lines_per_page: int) -> list[Page]:
    """Split wrapped lines into pages with offset metadata."""

    pages: list[Page] = []
    for index in range(0, len(lines), lines_per_page):
        chunk = lines[index : index + lines_per_page]
        start_offset = chunk[0].start_offset
        end_offset = max(line.end_offset for line in chunk)
        pages.append(
            Page(
                lines=[line.text for line in chunk],
                start_offset=start_offset,
                end_offset=end_offset,
            )
        )
    return pages or [Page(lines=[""], start_offset=0, end_offset=0)]


def iter_source_lines(normalized_text: str) -> list[tuple[int, str]]:
    """Split normalized text into source lines with their starting offsets."""

    source_lines: list[tuple[int, str]] = []
    cursor = 0
    raw_lines = normalized_text.split("\n")
    for index, raw_line in enumerate(raw_lines):
        source_lines.append((cursor, raw_line))
        cursor += len(raw_line)
        if index < len(raw_lines) - 1:
            cursor += 1
    return source_lines


def is_chapter_heading(line: str) -> bool:
    """Heuristically detect whether a source line is a chapter heading."""

    title = line.strip()
    if not title:
        return False
    return any(pattern.match(title) for pattern in CHAPTER_PATTERNS)


def detect_chapters(normalized_text: str) -> list[Chapter]:
    """Detect chapter headings from normalized text."""

    chapters: list[Chapter] = []
    for start_offset, raw_line in iter_source_lines(normalized_text):
        title = raw_line.strip()
        if is_chapter_heading(title):
            chapters.append(Chapter(title=title, start_offset=start_offset))
    return chapters


def _clip_text(text: str, width: int) -> str:
    """Clip metadata text to fit the current page width."""

    return clip_text(text, width)


def resolve_boss_command() -> tuple[list[str], str] | None:
    """Return the platform-native boss key command, if available."""

    if os.name == "nt":
        candidate_paths = []
        for root_name in ("WINDIR", "SystemRoot"):
            root = os.environ.get(root_name)
            if not root:
                continue
            candidate_paths.extend(
                [
                    os.path.join(root, "System32", "Taskmgr.exe"),
                    os.path.join(root, "Sysnative", "Taskmgr.exe"),
                    os.path.join(root, "SysWOW64", "Taskmgr.exe"),
                ]
            )

        seen_paths = set()
        for candidate in candidate_paths:
            if candidate in seen_paths:
                continue
            seen_paths.add(candidate)
            if os.path.isfile(candidate):
                return [candidate], "taskmgr"

        for executable in ("taskmgr.exe", "taskmgr"):
            taskmgr = shutil.which(executable)
            if taskmgr:
                return [taskmgr], "taskmgr"
        return None

    top = shutil.which("top")
    if top:
        return [top], "top"
    return None


@dataclass
class ReaderSession:
    """Interactive page session for one text source."""

    source_name: str
    width: int
    lines_per_page: int
    normalized_text: str
    total_chars: int
    display_lines: list[DisplayLine]
    pages: list[Page]
    chapters: list[Chapter]
    furthest_offset: int = 0
    ui_language: str = "zh"
    requested_width: int | None = None
    requested_lines_per_page: int | None = None

    @classmethod
    def from_text(
        cls,
        text: str,
        source_name: str,
        width: int | None = None,
        lines_per_page: int | None = None,
        furthest_offset: int = 0,
        ui_language: str = "zh",
    ) -> "ReaderSession":
        resolved_width = resolve_content_width(width)
        if lines_per_page is None:
            key = "reader_footer_windows" if os.name == "nt" else "reader_footer_posix"
            compact_key = f"{key}_compact"
            footer = tr(ui_language, key)
            footer_lines = wrap_text(footer, resolved_width) or [""]
            if len(footer_lines) > 3:
                footer = tr(ui_language, compact_key)
                footer_lines = wrap_text(footer, resolved_width) or [""]
            terminal_height = shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).lines
            resolved_lines = max(MIN_LINES, terminal_height - (6 + len(footer_lines)))
        else:
            resolved_lines = resolve_lines_per_page(lines_per_page)
        normalized, wrapped_lines = build_display_lines(text, resolved_width)
        return cls(
            source_name=source_name,
            width=resolved_width,
            lines_per_page=resolved_lines,
            normalized_text=normalized,
            total_chars=len(normalized),
            display_lines=wrapped_lines,
            pages=paginate_lines(wrapped_lines, resolved_lines),
            chapters=detect_chapters(normalized),
            furthest_offset=min(max(furthest_offset, 0), len(normalized)),
            ui_language=ui_language,
            requested_width=width,
            requested_lines_per_page=lines_per_page,
        )

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.ui_language, key, **kwargs)

    def _reader_footer(self) -> str:
        """Return the platform-specific reading footer."""

        key = "reader_footer_windows" if os.name == "nt" else "reader_footer_posix"
        compact_key = f"{key}_compact"
        footer = self._t(key)
        footer_lines = wrap_text(footer, self.width) or [""]
        if len(footer_lines) <= 3:
            return footer
        return self._t(compact_key)

    def _reader_footer_lines(self, width: int | None = None) -> list[str]:
        """Return footer lines that fit the current reading width."""

        target_width = width or self.width
        key = "reader_footer_windows" if os.name == "nt" else "reader_footer_posix"
        compact_key = f"{key}_compact"
        footer = self._t(key)
        footer_lines = wrap_text(footer, target_width) or [""]
        if len(footer_lines) <= 3:
            return footer_lines
        if text_width(footer) > target_width:
            footer = self._t(compact_key)
        return wrap_text(footer, target_width) or [""]

    def _resolve_auto_lines_per_page(self, width: int) -> int:
        """Resolve content height for auto-sized layouts."""

        if self.requested_lines_per_page is not None:
            return resolve_lines_per_page(self.requested_lines_per_page)

        terminal_height = shutil.get_terminal_size(FALLBACK_TERMINAL_SIZE).lines
        footer_lines = len(self._reader_footer_lines(width))
        reserve_lines = 6 + footer_lines
        return max(MIN_LINES, terminal_height - reserve_lines)

    def refresh_layout_for_line_index(self, line_index: int) -> int:
        """Reflow pagination after a terminal resize and preserve the current viewport."""

        if self.requested_width is not None and self.requested_lines_per_page is not None:
            return self.clamp_top_line_index(line_index)

        anchor_offset = self.page_for_line_index(line_index).start_offset
        resolved_width = resolve_content_width(self.requested_width)
        resolved_lines = self._resolve_auto_lines_per_page(resolved_width)
        if resolved_width == self.width and resolved_lines == self.lines_per_page:
            return self.clamp_top_line_index(line_index)

        normalized, wrapped_lines = build_display_lines(self.normalized_text, resolved_width)
        self.normalized_text = normalized
        self.total_chars = len(normalized)
        self.width = resolved_width
        self.lines_per_page = resolved_lines
        self.display_lines = wrapped_lines
        self.pages = paginate_lines(wrapped_lines, resolved_lines)
        self.furthest_offset = min(max(self.furthest_offset, 0), self.total_chars)
        return self.line_index_for_offset(anchor_offset)

    def max_top_line_index(self) -> int:
        """Return the greatest valid starting line for a viewport."""

        return max(0, len(self.display_lines) - self.lines_per_page)

    def clamp_top_line_index(self, line_index: int) -> int:
        """Clamp a viewport starting line into the visible range."""

        return min(max(line_index, 0), self.max_top_line_index())

    def page_for_line_index(self, line_index: int) -> Page:
        """Build the visible page for an arbitrary top line index."""

        top_line_index = self.clamp_top_line_index(line_index)
        chunk = self.display_lines[top_line_index : top_line_index + self.lines_per_page]
        if not chunk:
            chunk = [self.display_lines[-1]]
        return Page(
            lines=[line.text for line in chunk],
            start_offset=chunk[0].start_offset,
            end_offset=max(line.end_offset for line in chunk),
        )

    def logical_page_index_for_line_index(self, line_index: int) -> int:
        """Map a viewport line index back to the paginated page number."""

        if not self.pages:
            return 0
        return min(self.clamp_top_line_index(line_index) // self.lines_per_page, len(self.pages) - 1)

    def line_index_for_page_index(self, page_index: int) -> int:
        """Resolve the top line index for a paginated page."""

        return self.clamp_top_line_index(page_index * self.lines_per_page)

    def chapter_bounds(self, chapter_index: int) -> tuple[int, int]:
        """Return the start/end offsets for a chapter."""

        start = self.chapters[chapter_index].start_offset
        end = (
            self.chapters[chapter_index + 1].start_offset
            if chapter_index + 1 < len(self.chapters)
            else self.total_chars
        )
        return start, end

    def chapter_read_stats(self, chapter_index: int) -> tuple[int, int]:
        """Return read and total characters for one chapter."""

        return self.chapter_read_stats_for_offset(chapter_index, self.furthest_offset)

    def chapter_read_stats_for_offset(self, chapter_index: int, offset: int) -> tuple[int, int]:
        """Return chapter progress for an arbitrary text offset."""

        start, end = self.chapter_bounds(chapter_index)
        total = max(end - start, 0)
        clamped_offset = min(max(offset, 0), self.total_chars)
        read = min(max(clamped_offset - start, 0), total)
        return read, total

    def format_page(self, line_index: int, status_message: str = "") -> str:
        """Render one page into a plain terminal-friendly string."""

        page = self.page_for_line_index(line_index)
        logical_page_index = self.logical_page_index_for_line_index(line_index)
        current_chapter = self.chapter_for_line_index(line_index)
        current_chapter_index = self.chapter_index_for_line_index(line_index)
        current_chapter_progress = (
            self.chapter_read_stats_for_offset(current_chapter_index, page.end_offset)
            if current_chapter_index is not None
            else None
        )
        header = _clip_text(
            self._t(
                "reader_header",
                source_name=self.source_name,
                page=logical_page_index + 1,
                total=len(self.pages),
                percent=self.progress_percent_for_line_index(line_index),
            ),
            self.width,
        )
        chapter_line = (
            _clip_text(
                self._t(
                    "reader_header_chapter_with_progress",
                    title=current_chapter.title,
                    progress=self._t(
                        "reader_chapter_progress",
                        read=current_chapter_progress[0],
                        total=current_chapter_progress[1],
                    ),
                ),
                self.width,
            )
            if current_chapter is not None
            else _clip_text(self._t("reader_header_chapter_missing"), self.width)
        )
        footer_lines = self._reader_footer_lines()
        border = "=" * self.width
        body = "\n".join(page.lines)
        status = _clip_text(status_message, self.width) if status_message else ""

        sections = [border, header, chapter_line, border, body, border, *footer_lines]
        if status:
            sections.append(status)
        return "\n".join(sections)

    def format_boss_screen(self, status_message: str = "") -> str:
        """Render the fake work dashboard used by the boss key."""

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        header = _clip_text(
            self._t("reader_boss_header", timestamp=timestamp),
            self.width,
        )
        border = "=" * self.width
        body_lines = [
            self._t(f"reader_boss_line_{index}")
            for index in range(1, 11)
        ]
        body = "\n".join(_clip_text(line, self.width) for line in body_lines[: self.lines_per_page])
        footer = _clip_text(self._t("reader_boss_footer"), self.width)
        status = _clip_text(status_message, self.width) if status_message else ""
        sections = [border, header, border, body, border, footer]
        if status:
            sections.append(status)
        return "\n".join(sections)

    def trigger_boss_key(self, input_reader: "KeyReader") -> tuple[bool, str]:
        """Launch the platform-native boss key program when possible."""

        resolved = resolve_boss_command()
        if resolved is None:
            return False, ""

        command, label = resolved
        try:
            input_reader.run_external(command)
        except OSError:
            return False, ""
        return True, self._t("reader_boss_returned", app=label)

    def format_bookmark_browser(
        self,
        bookmarks: list[BookmarkEntry],
        browser_page: int,
        current_bookmark_index: int | None,
        status_message: str = "",
    ) -> str:
        """Render the bookmark browser."""

        page_size = self.chapter_browser_page_size()
        start = browser_page * page_size
        end = min(start + page_size, len(bookmarks))
        visible = bookmarks[start:end]
        border = "=" * self.width
        header = _clip_text(
            self._t(
                "reader_bookmarks_title",
                start=start + 1,
                end=end,
                total=len(bookmarks),
            ),
            self.width,
        )
        body_lines: list[str] = []
        for display_index, bookmark in enumerate(visible, start=1):
            actual_index = start + display_index - 1
            marker = ">" if actual_index == current_bookmark_index else " "
            progress = self.percent_for_offset(bookmark.offset)
            label = bookmark.note or bookmark.excerpt
            line = f"{display_index}. {marker} {label} ({progress:5.1f}%)"
            body_lines.append(_clip_text(line, self.width))
        body = "\n".join(body_lines)
        footer = _clip_text(self._t("reader_bookmarks_footer"), self.width)
        status = _clip_text(status_message, self.width) if status_message else ""
        sections = [border, header, border, body, border, footer]
        if status:
            sections.append(status)
        return "\n".join(sections)

    def format_chapter_browser(
        self,
        browser_page: int,
        current_chapter_index: int | None,
        status_message: str = "",
    ) -> str:
        """Render the chapter directory browser."""

        page_size = self.chapter_browser_page_size()
        start = browser_page * page_size
        end = min(start + page_size, len(self.chapters))
        visible = self.chapters[start:end]
        border = "=" * self.width
        header = _clip_text(
            self._t(
                "reader_chapters_title",
                start=start + 1,
                end=end,
                total=len(self.chapters),
            ),
            self.width,
        )
        body_lines: list[str] = []
        for display_index, chapter in enumerate(visible, start=1):
            actual_index = start + display_index - 1
            marker = ">" if actual_index == current_chapter_index else " "
            read_chars, total_chars = self.chapter_read_stats(actual_index)
            progress = self._t(
                "reader_chapter_progress",
                read=read_chars,
                total=total_chars,
            )
            line = f"{display_index}. {marker} {chapter.title} | {progress}"
            body_lines.append(_clip_text(line, self.width))
        body = "\n".join(body_lines)
        footer = _clip_text(self._t("reader_chapters_footer"), self.width)
        status = _clip_text(status_message, self.width) if status_message else ""
        sections = [border, header, border, body, border, footer]
        if status:
            sections.append(status)
        return "\n".join(sections)

    def page_index_for_offset(self, offset: int) -> int:
        """Resolve the closest page index for a saved cursor offset."""

        clamped = min(max(offset, 0), self.total_chars)
        current_index = 0
        for index, page in enumerate(self.pages):
            if page.start_offset <= clamped:
                current_index = index
                continue
            break
        return current_index

    def line_index_for_offset(self, offset: int) -> int:
        """Resolve the closest top line index for a saved cursor offset."""

        clamped = min(max(offset, 0), self.total_chars)
        current_index = 0
        for index, line in enumerate(self.display_lines):
            if line.start_offset <= clamped:
                current_index = index
                continue
            break
        return self.clamp_top_line_index(current_index)

    def progress_percent(self, page_index: int) -> float:
        """Compute read percentage for the visible page."""

        if self.total_chars <= 0:
            return 100.0
        visible_offset = min(self.pages[page_index].end_offset, self.total_chars)
        return round((visible_offset / self.total_chars) * 100, 1)

    def progress_percent_for_line_index(self, line_index: int) -> float:
        """Compute read percentage for an arbitrary viewport."""

        if self.total_chars <= 0:
            return 100.0
        visible_page = self.page_for_line_index(line_index)
        visible_offset = min(visible_page.end_offset, self.total_chars)
        return round((visible_offset / self.total_chars) * 100, 1)

    def percent_for_offset(self, offset: int) -> float:
        """Compute overall progress for a given text offset."""

        if self.total_chars <= 0:
            return 100.0
        visible_offset = min(max(offset, 0), self.total_chars)
        return round((visible_offset / self.total_chars) * 100, 1)

    def chapter_for_page(self, page_index: int) -> Chapter | None:
        """Return the current chapter for a page, if chapter headings were detected."""

        chapter_index = self.chapter_index_for_page(page_index)
        if chapter_index is None:
            return None
        return self.chapters[chapter_index]

    def chapter_for_line_index(self, line_index: int) -> Chapter | None:
        """Return the current chapter for an arbitrary viewport."""

        chapter_index = self.chapter_index_for_line_index(line_index)
        if chapter_index is None:
            return None
        return self.chapters[chapter_index]

    def chapter_index_for_page(self, page_index: int) -> int | None:
        """Resolve the active chapter index for a page."""

        if not self.chapters:
            return None
        current_offset = self.pages[page_index].start_offset
        current_index = None
        for index, chapter in enumerate(self.chapters):
            if chapter.start_offset <= current_offset:
                current_index = index
                continue
            break
        return current_index if current_index is not None else 0

    def chapter_index_for_line_index(self, line_index: int) -> int | None:
        """Resolve the active chapter index for an arbitrary viewport."""

        if not self.chapters:
            return None
        current_offset = self.page_for_line_index(line_index).start_offset
        current_index = None
        for index, chapter in enumerate(self.chapters):
            if chapter.start_offset <= current_offset:
                current_index = index
                continue
            break
        return current_index if current_index is not None else 0

    def chapter_browser_page_size(self) -> int:
        """Return how many chapter rows to show in one browser screen."""

        return min(9, max(4, self.lines_per_page))

    def excerpt_for_page(self, page_index: int, limit: int = 120) -> str:
        """Build a short excerpt from the visible page."""

        page_lines = [line.strip() for line in self.pages[page_index].lines if line.strip()]
        text = " ".join(page_lines) if page_lines else self._t("reader_empty_page_excerpt")
        return text[:limit]

    def excerpt_for_line_index(self, line_index: int, limit: int = 120) -> str:
        """Build a short excerpt from an arbitrary viewport."""

        page = self.page_for_line_index(line_index)
        page_lines = [line.strip() for line in page.lines if line.strip()]
        text = " ".join(page_lines) if page_lines else self._t("reader_empty_page_excerpt")
        return text[:limit]

    def search_page_index(
        self,
        query: str,
        page_index: int,
        *,
        repeat: bool = False,
    ) -> tuple[int | None, str]:
        """Search for text from the current page and return the target page."""

        needle = query.casefold().strip()
        if not needle:
            return None, self._t("reader_search_missing")

        haystack = self.normalized_text.casefold()
        current_page = self.pages[page_index]
        start_offset = current_page.end_offset if repeat else current_page.start_offset + 1
        found_at = haystack.find(needle, min(start_offset, len(haystack)))
        wrapped = False
        if found_at == -1 and start_offset > 0:
            found_at = haystack.find(needle, 0, min(start_offset, len(haystack)))
            wrapped = found_at != -1
        if found_at == -1:
            return None, self._t("reader_search_not_found", query=query)

        target_page = self.page_index_for_offset(found_at)
        if wrapped:
            return target_page, self._t("reader_search_wrapped", query=query)
        return target_page, self._t("reader_search_found", query=query)

    def search_line_index(
        self,
        query: str,
        line_index: int,
        *,
        repeat: bool = False,
    ) -> tuple[int | None, str]:
        """Search for text from an arbitrary viewport and return the target top line."""

        needle = query.casefold().strip()
        if not needle:
            return None, self._t("reader_search_missing")

        haystack = self.normalized_text.casefold()
        current_page = self.page_for_line_index(line_index)
        start_offset = current_page.end_offset if repeat else current_page.start_offset + 1
        found_at = haystack.find(needle, min(start_offset, len(haystack)))
        wrapped = False
        if found_at == -1 and start_offset > 0:
            found_at = haystack.find(needle, 0, min(start_offset, len(haystack)))
            wrapped = found_at != -1
        if found_at == -1:
            return None, self._t("reader_search_not_found", query=query)

        target_line = self.line_index_for_offset(found_at)
        if wrapped:
            return target_line, self._t("reader_search_wrapped", query=query)
        return target_line, self._t("reader_search_found", query=query)

    def adjacent_chapter_page_index(self, page_index: int, step: int) -> int | None:
        """Jump to the previous or next detected chapter."""

        if not self.chapters:
            return None
        current_index = self.chapter_index_for_page(page_index)
        if current_index is None:
            return None
        target_index = current_index + step
        if target_index < 0 or target_index >= len(self.chapters):
            return None
        return self.page_index_for_offset(self.chapters[target_index].start_offset)

    def adjacent_chapter_line_index(self, line_index: int, step: int) -> int | None:
        """Jump to the previous or next detected chapter using the active viewport."""

        if not self.chapters:
            return None
        current_index = self.chapter_index_for_line_index(line_index)
        if current_index is None:
            return None
        target_index = current_index + step
        if target_index < 0 or target_index >= len(self.chapters):
            return None
        return self.line_index_for_offset(self.chapters[target_index].start_offset)

    def browse_chapters(self, line_index: int, input_reader: "KeyReader") -> int | None:
        """Open the interactive chapter directory and return the chosen top line."""

        if not self.chapters:
            return None

        page_size = self.chapter_browser_page_size()
        current_chapter_index = self.chapter_index_for_line_index(line_index)
        browser_page = 0 if current_chapter_index is None else current_chapter_index // page_size
        status_message = ""
        max_browser_page = (len(self.chapters) - 1) // page_size

        while True:
            render_screen(
                self.format_chapter_browser(browser_page, current_chapter_index, status_message)
            )
            status_message = ""
            command = input_reader.read_key()

            if command in {"q", "Q", "escape", "m"}:
                return None

            if command == "d":
                if browser_page < max_browser_page:
                    browser_page += 1
                else:
                    status_message = self._t("reader_last_chapter_page")
                continue

            if command == "a":
                if browser_page > 0:
                    browser_page -= 1
                else:
                    status_message = self._t("reader_first_chapter_page")
                continue

            if command == "g":
                browser_page = 0
                continue

            if command == "G":
                browser_page = max_browser_page
                continue

            if len(command) == 1 and command.isdigit():
                chapter_number = int(command)
                visible = self.chapters[browser_page * page_size : (browser_page + 1) * page_size]
                if 1 <= chapter_number <= len(visible):
                    target_chapter = visible[chapter_number - 1]
                    return self.line_index_for_offset(target_chapter.start_offset)
                status_message = self._t("reader_chapter_number_missing")
                continue

            status_message = self._t("reader_chapter_browser_help")

    def browse_bookmarks(
        self,
        line_index: int,
        bookmarks: list[BookmarkEntry],
        input_reader: "KeyReader",
    ) -> int | None:
        """Open the bookmark browser and return the chosen top line."""

        if not bookmarks:
            return None

        ordered = sorted(bookmarks, key=lambda item: (item.offset, item.created_at))
        page_size = self.chapter_browser_page_size()
        current_index = 0
        for index, bookmark in enumerate(ordered):
            if bookmark.offset <= self.page_for_line_index(line_index).start_offset:
                current_index = index
                continue
            break
        browser_page = current_index // page_size
        status_message = ""
        max_browser_page = (len(ordered) - 1) // page_size

        while True:
            render_screen(
                self.format_bookmark_browser(ordered, browser_page, current_index, status_message)
            )
            status_message = ""
            command = input_reader.read_key()

            if command in {"q", "Q", "escape", "v"}:
                return None

            if command == "d":
                if browser_page < max_browser_page:
                    browser_page += 1
                else:
                    status_message = self._t("reader_last_bookmark_page")
                continue

            if command == "a":
                if browser_page > 0:
                    browser_page -= 1
                else:
                    status_message = self._t("reader_first_bookmark_page")
                continue

            if len(command) == 1 and command.isdigit():
                bookmark_number = int(command)
                visible = ordered[browser_page * page_size : (browser_page + 1) * page_size]
                if 1 <= bookmark_number <= len(visible):
                    target = visible[bookmark_number - 1]
                    return self.line_index_for_offset(target.offset)
                status_message = self._t("reader_bookmark_number_missing")
                continue

            status_message = self._t("reader_bookmark_browser_help")

    def read(
        self,
        start_page: int = 1,
        start_offset: int | None = None,
        progress_callback: Callable[[int, int, int], None] | None = None,
        bookmarks: list[BookmarkEntry] | None = None,
        bookmark_add_callback: Callable[[int, str, str], list[BookmarkEntry]] | None = None,
    ) -> int:
        """Run the interactive reading loop."""

        if start_offset is None and (start_page < 1 or start_page > len(self.pages)):
            raise ReaderError(
                f"--start-page must be between 1 and {len(self.pages)} for this text."
            )

        if not sys.stdin.isatty() or not sys.stdout.isatty():
            sys.stdout.write("\n".join("\n".join(page.lines) for page in self.pages))
            if not sys.stdout.isatty():
                sys.stdout.write("\n")
            return 0

        top_line_index = (
            self.line_index_for_offset(start_offset)
            if start_offset is not None
            else self.line_index_for_page_index(start_page - 1)
        )
        self.furthest_offset = min(max(self.furthest_offset, start_offset or 0), self.total_chars)
        status_message = ""
        boss_mode = False
        last_search_query = ""
        bookmark_entries = list(bookmarks or [])

        def persist_current_view() -> None:
            current_page = self.page_for_line_index(top_line_index)
            self.furthest_offset = min(
                max(self.furthest_offset, current_page.end_offset),
                self.total_chars,
            )
            if progress_callback is None:
                return
            progress_callback(current_page.start_offset, current_page.end_offset, self.total_chars)

        persist_current_view()
        with KeyReader() as input_reader:
            while True:
                top_line_index = self.refresh_layout_for_line_index(top_line_index)
                screen = (
                    self.format_boss_screen(status_message)
                    if boss_mode
                    else self.format_page(top_line_index, status_message)
                )
                render_screen(screen)
                status_message = ""

                try:
                    command = input_reader.read_key()
                except (EOFError, KeyboardInterrupt):
                    persist_current_view()
                    print()
                    return 0

                if boss_mode:
                    if command in {"b", "escape", "q", "Q"}:
                        boss_mode = False
                    continue

                if command == "d":
                    if top_line_index < self.max_top_line_index():
                        top_line_index = min(
                            top_line_index + self.lines_per_page,
                            self.max_top_line_index(),
                        )
                        persist_current_view()
                    else:
                        persist_current_view()
                        return 0
                    continue

                if command == "a":
                    if top_line_index > 0:
                        top_line_index = max(top_line_index - self.lines_per_page, 0)
                        persist_current_view()
                    else:
                        status_message = self._t("reader_first_page")
                    continue

                if command == "s":
                    if top_line_index < self.max_top_line_index():
                        top_line_index += 1
                        persist_current_view()
                    else:
                        status_message = self._t("reader_last_line")
                    continue

                if command == "w":
                    if top_line_index > 0:
                        top_line_index -= 1
                        persist_current_view()
                    else:
                        status_message = self._t("reader_first_line")
                    continue

                if command == "[":
                    target_line = self.adjacent_chapter_line_index(top_line_index, -1)
                    if target_line is None:
                        status_message = self._t("reader_prev_chapter_missing")
                    else:
                        top_line_index = target_line
                        persist_current_view()
                    continue

                if command == "]":
                    target_line = self.adjacent_chapter_line_index(top_line_index, 1)
                    if target_line is None:
                        status_message = self._t("reader_next_chapter_missing")
                    else:
                        top_line_index = target_line
                        persist_current_view()
                    continue

                if command == "g":
                    top_line_index = 0
                    persist_current_view()
                    continue

                if command == "G":
                    top_line_index = self.max_top_line_index()
                    persist_current_view()
                    continue

                if command == "b":
                    launched, boss_status = self.trigger_boss_key(input_reader)
                    if launched:
                        status_message = boss_status
                    else:
                        boss_mode = True
                        status_message = boss_status
                    continue

                if command == "m":
                    if not self.chapters:
                        status_message = self._t("reader_no_chapters")
                    else:
                        selected_line = self.browse_chapters(top_line_index, input_reader)
                        if selected_line is not None:
                            top_line_index = selected_line
                            persist_current_view()
                    continue

                if command == "/":
                    query = input_reader.prompt_line(self._t("reader_search_prompt")).strip()
                    if not query:
                        status_message = self._t("reader_search_cancelled")
                        continue
                    last_search_query = query
                    target_line, search_status = self.search_line_index(query, top_line_index)
                    status_message = search_status
                    if target_line is not None:
                        top_line_index = target_line
                        persist_current_view()
                    continue

                if command == "r":
                    if not last_search_query:
                        status_message = self._t("reader_search_repeat_missing")
                        continue
                    target_line, search_status = self.search_line_index(
                        last_search_query,
                        top_line_index,
                        repeat=True,
                    )
                    status_message = search_status
                    if target_line is not None:
                        top_line_index = target_line
                        persist_current_view()
                    continue

                if command == "k":
                    note = input_reader.prompt_line(self._t("reader_bookmark_prompt")).strip()
                    excerpt = self.excerpt_for_line_index(top_line_index)
                    if bookmark_add_callback is not None:
                        current_page = self.page_for_line_index(top_line_index)
                        bookmark_entries = bookmark_add_callback(
                            current_page.start_offset,
                            excerpt,
                            note,
                        )
                    else:
                        current_page = self.page_for_line_index(top_line_index)
                        bookmark_entries.append(
                            BookmarkEntry(
                                id=f"bookmark-{len(bookmark_entries) + 1}",
                                offset=current_page.start_offset,
                                created_at=datetime.now().isoformat(),
                                excerpt=excerpt,
                                note=note,
                            )
                        )
                    status_message = self._t("reader_bookmark_saved")
                    continue

                if command == "v":
                    if not bookmark_entries:
                        status_message = self._t("reader_bookmark_browser_empty")
                        continue
                    selected_line = self.browse_bookmarks(
                        top_line_index,
                        bookmark_entries,
                        input_reader,
                    )
                    if selected_line is not None:
                        top_line_index = selected_line
                        persist_current_view()
                    continue

                if command in {"q", "Q"}:
                    persist_current_view()
                    return 0

                status_message = self._t("reader_unknown_command")


class KeyReader:
    """Cross-platform single-key reader for interactive navigation."""

    def __enter__(self) -> "KeyReader":
        self._is_windows = os.name == "nt"
        if self._is_windows:
            self._module = __import__("msvcrt")
            return self

        import termios
        import tty

        self._termios = termios
        self._tty = tty
        self._fd = sys.stdin.fileno()
        self._original_settings = termios.tcgetattr(self._fd)
        tty.setcbreak(self._fd)
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        if self._is_windows:
            return
        self._termios.tcsetattr(
            self._fd,
            self._termios.TCSADRAIN,
            self._original_settings,
        )

    def read_key(self) -> str:
        if self._is_windows:
            return self._read_windows_key()
        return self._read_posix_key()

    def prompt_line(self, prompt: str) -> str:
        """Temporarily switch back to line input for prompts."""

        if self._is_windows:
            print()
            return input(prompt)

        self._termios.tcsetattr(
            self._fd,
            self._termios.TCSADRAIN,
            self._original_settings,
        )
        try:
            print()
            return input(prompt)
        finally:
            self._tty.setcbreak(self._fd)

    def run_external(self, command: list[str]) -> None:
        """Temporarily leave raw input mode and run an external interactive command."""

        if self._is_windows:
            subprocess.run(command, check=False)
            return

        self._termios.tcsetattr(
            self._fd,
            self._termios.TCSADRAIN,
            self._original_settings,
        )
        try:
            subprocess.run(command, check=False)
        finally:
            self._tty.setcbreak(self._fd)

    def _read_windows_key(self) -> str:
        char = self._module.getwch()
        if char == "\x03":
            raise KeyboardInterrupt
        if char in {"\r", "\n"}:
            return "enter"
        if char in {"\x00", "\xe0"}:
            special = self._module.getwch()
            return {
                "K": "left",
                "M": "right",
                "H": "up",
                "P": "down",
                "G": "g",
                "O": "G",
            }.get(special, special)
        if char == "\x1b":
            return "escape"
        return char

    def _read_posix_key(self) -> str:
        char = sys.stdin.read(1)
        if char == "\x03":
            raise KeyboardInterrupt
        if char in {"\r", "\n"}:
            return "enter"
        if char == "\x1b":
            # Some embedded terminals deliver arrow-key bytes with a noticeable delay.
            if not self._input_ready(timeout=ESCAPE_INITIAL_TIMEOUT):
                return "escape"
            prefix = sys.stdin.read(1)
            if prefix not in {"[", "O"}:
                return "escape"
            return self._read_posix_prefixed_key(prefix)

        if char in {"[", "O"}:
            command = self._read_posix_prefixed_key(char, allow_fallback=True)
            return command

        return char

    def _read_posix_prefixed_key(self, prefix: str, *, allow_fallback: bool = False) -> str:
        """Read a partially received POSIX key sequence after `[` or `O`."""

        sequence = prefix
        command = decode_posix_escape_sequence(sequence)
        if command != "escape" and sequence.startswith("O"):
            return command

        for _ in range(10):
            if not self._input_ready(timeout=ESCAPE_CHUNK_TIMEOUT):
                break
            sequence += sys.stdin.read(1)
            command = decode_posix_escape_sequence(sequence)
            if command != "escape" and (sequence[-1].isalpha() or sequence[-1] == "~"):
                return command

        return prefix if allow_fallback else command

    @staticmethod
    def _input_ready(timeout: float = 0.02) -> bool:
        ready, _, _ = select.select([sys.stdin], [], [], timeout)
        return bool(ready)


def run_reader_from_text(
    text: str,
    source_name: str,
    width: int | None = None,
    lines_per_page: int | None = None,
    start_page: int = 1,
    start_offset: int | None = None,
    furthest_offset: int = 0,
    progress_callback: Callable[[int, int, int], None] | None = None,
    bookmarks: list[BookmarkEntry] | None = None,
    bookmark_add_callback: Callable[[int, str, str], list[BookmarkEntry]] | None = None,
    ui_language: str = "zh",
) -> int:
    """Create a session and start reading from in-memory text."""

    session = ReaderSession.from_text(
        text=text,
        source_name=source_name,
        width=width,
        lines_per_page=lines_per_page,
        furthest_offset=furthest_offset,
        ui_language=ui_language,
    )
    return session.read(
        start_page=start_page,
        start_offset=start_offset,
        progress_callback=progress_callback,
        bookmarks=bookmarks,
        bookmark_add_callback=bookmark_add_callback,
    )


def run_file_reader(
    path: Path,
    encoding: str | None = None,
    width: int | None = None,
    lines_per_page: int | None = None,
    start_page: int = 1,
    start_offset: int | None = None,
    furthest_offset: int = 0,
    progress_callback: Callable[[int, int, int], None] | None = None,
    bookmarks: list[BookmarkEntry] | None = None,
    bookmark_add_callback: Callable[[int, str, str], list[BookmarkEntry]] | None = None,
    ui_language: str = "zh",
) -> int:
    """Read a local text file."""

    text = load_text(path, encoding=encoding)
    return run_reader_from_text(
        text=text,
        source_name=path.name,
        width=width,
        lines_per_page=lines_per_page,
        start_page=start_page,
        start_offset=start_offset,
        furthest_offset=furthest_offset,
        progress_callback=progress_callback,
        bookmarks=bookmarks,
        bookmark_add_callback=bookmark_add_callback,
        ui_language=ui_language,
    )


def run_demo_reader(
    width: int | None = None,
    lines_per_page: int | None = None,
    start_page: int = 1,
    ui_language: str = "zh",
) -> int:
    """Read the bundled demo text."""

    text = load_demo_text()
    return run_reader_from_text(
        text=text,
        source_name="demo.txt",
        width=width,
        lines_per_page=lines_per_page,
        start_page=start_page,
        ui_language=ui_language,
    )
