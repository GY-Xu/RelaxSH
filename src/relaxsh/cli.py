"""Command-line interface for RelaxSH."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Sequence

from relaxsh.display import clip_text, pad_text, text_width
from relaxsh import __version__
from relaxsh.i18n import tr
from relaxsh.library import BookRecord, ImportSummary, Library, format_timestamp
from relaxsh.reader import BookmarkEntry, ReaderError, clear_screen, resolve_boss_command, run_file_reader


PROGRESS_COLUMN_WIDTH = 19
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
LAUNCHER_LEFT_PADDING = "  "
LAUNCHER_MASCOT_PIXELS = (
    "         ooo    ooo        ",
    "         ofo    ofo        ",
    "        oofo    ofoo       ",
    "        ofpoooooopfo       ",
    "       oofpffffffpfoo      ",
    "      oofpppffffpppfoo     ",
    "     ooffpppffffpppffoo    ",
    "     offpppppffpppppffo    ",
    "     offffffffffffffffo    ",
    "     offffhffffffhffffo    ",
    "     offfeeeffffeeefffo    ",
    "     offweeewwwweeewffo    ",
    "     offwwewwwwwwewwffo    ",
    "   ooooppwwwwnnwwwwppoooo  ",
    "     ofppwwwwnnwwwwppfo    ",
    "    oooowwwwnnnnwwwwoooo   ",
    "      offffwwwwwwffffo     ",
    "      offffffffffffffo     ",
    "      offoooffffoooffo     ",
    "      oofffffoofffffoo     ",
    "       oooooooooooooo      ",
)
LAUNCHER_MASCOT_PALETTE = {
    "o": (84, 55, 45),
    "f": (236, 188, 126),
    "w": (250, 236, 215),
    "p": (241, 181, 193),
    "e": (40, 28, 24),
    "n": (190, 112, 124),
    "h": (255, 255, 255),
}
LAUNCHER_MASCOT_FALLBACK = {
    " ": " ",
    "o": "█",
    "f": "▓",
    "w": "▒",
    "p": "░",
    "e": "█",
    "n": "▓",
    "h": " ",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="relaxsh",
        description="A terminal slacking companion focused on paged TXT reading.",
    )
    subparsers = parser.add_subparsers(dest="command")

    read_parser = subparsers.add_parser("read", help="Read a local TXT file.")
    read_parser.add_argument("path", help="Path to a local TXT file.")
    read_parser.add_argument(
        "--encoding",
        help="Force a specific text encoding. Defaults to trying utf-8, utf-8-sig and gb18030.",
    )
    read_parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Content width per line. Defaults to the current terminal width.",
    )
    read_parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Lines shown per page. Defaults to the current terminal height.",
    )
    read_parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start reading from a specific page number.",
    )
    read_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore any saved reading progress and start from the beginning.",
    )

    demo_parser = subparsers.add_parser("demo", help="Read the bundled demo text.")
    demo_parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Content width per line. Defaults to the current terminal width.",
    )
    demo_parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Lines shown per page. Defaults to the current terminal height.",
    )
    demo_parser.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Start reading from a specific page number.",
    )

    import_parser = subparsers.add_parser(
        "import",
        help="Import one TXT file or a directory of TXT novels into the library.",
    )
    import_parser.add_argument("path", help="TXT file or directory to import.")

    subparsers.add_parser("library", help="Show imported books and reading progress.")

    open_parser = subparsers.add_parser(
        "open",
        help="Open one imported book by id prefix, exact title, or unique fuzzy match.",
    )
    open_parser.add_argument("book", help="Book id prefix, title, or imported path.")
    open_parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Content width per line. Defaults to the current terminal width.",
    )
    open_parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Lines shown per page. Defaults to the current terminal height.",
    )
    open_parser.add_argument(
        "--fresh",
        action="store_true",
        help="Ignore the saved progress for this book and start from the beginning.",
    )

    continue_parser = subparsers.add_parser(
        "continue",
        help="Resume the most recently read imported book.",
    )
    continue_parser.add_argument(
        "--width",
        type=int,
        default=None,
        help="Content width per line. Defaults to the current terminal width.",
    )
    continue_parser.add_argument(
        "--lines",
        type=int,
        default=None,
        help="Lines shown per page. Defaults to the current terminal height.",
    )

    subparsers.add_parser("version", help="Show the current RelaxSH version.")
    return parser


def _status_text(book: BookRecord, language: str) -> str:
    return tr(language, f"library_status_{book.status}")


def _progress_meter(percent: float, width: int = 10) -> str:
    filled = min(width, max(0, round((percent / 100) * width)))
    return f"[{'#' * filled}{'-' * (width - filled)}]"


def _progress_text(percent: float) -> str:
    return f"{_progress_meter(percent)} {percent:5.1f}%"


def _library_column_widths(books: list[BookRecord], *, indexed: bool) -> tuple[int, int]:
    terminal_width = shutil.get_terminal_size((100, 24)).columns
    fixed_width = 8 + 1 + PROGRESS_COLUMN_WIDTH + 1 + 7 + 1 + 16 + 1
    if indexed:
        fixed_width += 3
    title_width = max(18, terminal_width // 3)
    path_width = max(18, terminal_width - fixed_width - title_width)
    return title_width, path_width


def _clip(value: str, width: int) -> str:
    return clip_text(value, width)


def filter_books(books: list[BookRecord], query: str) -> list[BookRecord]:
    """Filter books by case-insensitive title and path keywords."""

    terms = [term for term in query.casefold().split() if term]
    if not terms:
        return books

    filtered: list[BookRecord] = []
    for book in books:
        haystack = f"{book.title} {Path(book.path).name} {book.path}".casefold()
        if all(term in haystack for term in terms):
            filtered.append(book)
    return filtered


def print_library(books: list[BookRecord], *, language: str = "zh") -> None:
    if not books:
        print(tr(language, "library_empty"))
        return

    title_width, path_width = _library_column_widths(books, indexed=False)
    header = (
        f"{pad_text(tr(language, 'library_table_id'), 8)} "
        f"{pad_text(tr(language, 'library_table_progress'), PROGRESS_COLUMN_WIDTH)} "
        f"{pad_text(tr(language, 'library_table_status'), 7)} "
        f"{pad_text(tr(language, 'library_table_last_opened'), 16)} "
        f"{pad_text(tr(language, 'library_table_title'), title_width)} "
        f"{pad_text(tr(language, 'library_table_path'), path_width)}"
    )
    print(header)
    print("-" * text_width(header))
    for book in books:
        last_opened = format_timestamp(book.progress.last_read_at)
        title = _clip(book.title, title_width)
        path = _clip(book.path, path_width)
        print(
            f"{pad_text(book.id[:8], 8)} "
            f"{pad_text(_progress_text(book.percent_read), PROGRESS_COLUMN_WIDTH)} "
            f"{pad_text(_status_text(book, language), 7)} "
            f"{pad_text(last_opened, 16)} "
            f"{pad_text(title, title_width)} "
            f"{pad_text(path, path_width)}"
        )


def _localized_import_detail(language: str, detail: str) -> str:
    if detail == "Imported new book.":
        return tr(language, "import_detail_imported")
    if detail == "Updated book metadata and file info.":
        return tr(language, "import_detail_updated")
    if detail == "Already imported and unchanged.":
        return tr(language, "import_detail_unchanged")
    prefix = "Skipped duplicate content at "
    if detail.startswith(prefix) and detail.endswith("."):
        return tr(language, "import_detail_duplicate", name=detail[len(prefix) : -1])
    return detail


def print_import_summary(summary: ImportSummary, *, language: str = "zh") -> None:
    print(
        tr(
            language,
            "import_summary",
            imported=len(summary.imported),
            updated=len(summary.updated),
            skipped=len(summary.skipped),
            errors=len(summary.errors),
        )
    )
    for label, events in (
        (tr(language, "import_label_imported"), summary.imported),
        (tr(language, "import_label_updated"), summary.updated),
        (tr(language, "import_label_skipped"), summary.skipped),
    ):
        for event in events:
            detail = _localized_import_detail(language, event.detail)
            print(f"{label}: [{event.book.id[:8]}] {event.book.title} - {detail}")
    for error in summary.errors:
        print(f"{tr(language, 'error_prefix')}: {error}", file=sys.stderr)


def _pause(language: str = "zh", message: str | None = None) -> None:
    input(message or tr(language, "pause_prompt"))


def _is_interactive_terminal() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _prompt_choice(prompt: str) -> str:
    return input(prompt).strip()


def _boss_key_menu_text(language: str) -> str:
    """Return the platform-specific boss key label for menus."""

    key = "boss_key_menu_windows" if os.name == "nt" else "boss_key_menu_posix"
    return tr(language, key)


def _run_boss_key_from_menu(language: str) -> None:
    """Launch the platform-native boss key app from a non-reader menu."""

    resolved = resolve_boss_command()
    if resolved is None:
        print(tr(language, "boss_key_unavailable"))
        _pause(language)
        return

    command, _label = resolved
    try:
        subprocess.run(command, check=False)
    except OSError:
        print(tr(language, "boss_key_unavailable"))
        _pause(language)


def _supports_ansi_colors() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _visible_text_width(text: str) -> int:
    return text_width(_strip_ansi(text))


def _center_line(text: str) -> str:
    terminal_width = shutil.get_terminal_size((100, 24)).columns
    return (" " * max(0, (terminal_width - _visible_text_width(text)) // 2)) + text


def _render_mascot_pixel_pair(top: str, bottom: str) -> str:
    top_is_filled = top != " "
    bottom_is_filled = bottom != " "
    if not top_is_filled and not bottom_is_filled:
        return " "

    def fg(rgb: tuple[int, int, int]) -> str:
        return f"\x1b[38;2;{rgb[0]};{rgb[1]};{rgb[2]}m"

    def bg(rgb: tuple[int, int, int]) -> str:
        return f"\x1b[48;2;{rgb[0]};{rgb[1]};{rgb[2]}m"

    reset = "\x1b[0m"
    if top_is_filled and bottom_is_filled:
        top_rgb = LAUNCHER_MASCOT_PALETTE[top]
        bottom_rgb = LAUNCHER_MASCOT_PALETTE[bottom]
        if top_rgb == bottom_rgb:
            return f"{fg(top_rgb)}█{reset}"
        return f"{fg(top_rgb)}{bg(bottom_rgb)}▀{reset}"
    if top_is_filled:
        return f"{fg(LAUNCHER_MASCOT_PALETTE[top])}▀{reset}"
    return f"{fg(LAUNCHER_MASCOT_PALETTE[bottom])}▄{reset}"


def _render_launcher_mascot(*, use_color: bool | None = None) -> list[str]:
    if use_color is None:
        use_color = _supports_ansi_colors()

    if not use_color:
        return [
            "".join(LAUNCHER_MASCOT_FALLBACK[pixel] for pixel in row).rstrip()
            for row in LAUNCHER_MASCOT_PIXELS
        ]

    lines: list[str] = []
    for row_index in range(0, len(LAUNCHER_MASCOT_PIXELS), 2):
        top_row = LAUNCHER_MASCOT_PIXELS[row_index]
        bottom_row = (
            LAUNCHER_MASCOT_PIXELS[row_index + 1]
            if row_index + 1 < len(LAUNCHER_MASCOT_PIXELS)
            else (" " * len(top_row))
        )
        lines.append("".join(_render_mascot_pixel_pair(top, bottom) for top, bottom in zip(top_row, bottom_row)).rstrip())
    return lines


def _launcher_menu_lines(language: str) -> list[str]:
    return [
        tr(language, "main_title"),
        "",
        tr(language, "main_menu_novels"),
        tr(language, "main_menu_settings"),
        _boss_key_menu_text(language),
        tr(language, "main_menu_exit"),
    ]


def _compose_launcher_lines(language: str, *, use_color: bool | None = None) -> list[str]:
    menu_lines = _launcher_menu_lines(language)
    mascot_lines = _render_launcher_mascot(use_color=use_color)
    composed = [f"{LAUNCHER_LEFT_PADDING}{line}".rstrip() for line in mascot_lines]
    composed.append("")
    composed.extend(f"{LAUNCHER_LEFT_PADDING}{line}".rstrip() for line in menu_lines)
    return composed


def _print_launcher_block(language: str) -> None:
    for line in _compose_launcher_lines(language):
        print(line)
    print()


def _normalize_prompted_path(path_text: str) -> str:
    """Accept raw, quoted, or shell-escaped paths pasted into the interactive prompt."""

    text = path_text.strip()
    if not text:
        return text

    quote_pairs = {"'": "'", '"': '"'}
    if len(text) >= 2 and text[0] in quote_pairs and text[-1] == quote_pairs[text[0]]:
        return text[1:-1]

    try:
        parsed = shlex.split(text, posix=(sys.platform != "win32"))
    except ValueError:
        return text

    if len(parsed) == 1:
        return parsed[0]
    return text


def _current_language_label(language: str) -> str:
    return tr(language, "lang_option")


def _most_recent_book_or_error(library: Library, language: str) -> BookRecord:
    if not any(book.progress.last_read_at for book in library.books):
        raise ReaderError(tr(language, "library_no_recent"))
    return library.most_recent_book()


def print_book_list(books: list[BookRecord], *, indexed: bool = True, language: str = "zh") -> None:
    if not books:
        print(tr(language, "library_empty"))
        return

    title_width, path_width = _library_column_widths(books, indexed=indexed)
    prefix = f"{'#':>2} " if indexed else ""
    header = (
        f"{prefix}{pad_text(tr(language, 'library_table_id'), 8)} "
        f"{pad_text(tr(language, 'library_table_progress'), PROGRESS_COLUMN_WIDTH)} "
        f"{pad_text(tr(language, 'library_table_status'), 7)} "
        f"{pad_text(tr(language, 'library_table_last_opened'), 16)} "
        f"{pad_text(tr(language, 'library_table_title'), title_width)} "
        f"{pad_text(tr(language, 'library_table_path'), path_width)}"
    )
    print(header)
    print("-" * text_width(header))
    for index, book in enumerate(books, start=1):
        last_opened = format_timestamp(book.progress.last_read_at)
        title = _clip(book.title, title_width)
        path = _clip(book.path, path_width)
        prefix_value = f"{index:>2} " if indexed else ""
        print(
            f"{prefix_value}{pad_text(book.id[:8], 8)} "
            f"{pad_text(_progress_text(book.percent_read), PROGRESS_COLUMN_WIDTH)} "
            f"{pad_text(_status_text(book, language), 7)} "
            f"{pad_text(last_opened, 16)} "
            f"{pad_text(title, title_width)} "
            f"{pad_text(path, path_width)}"
        )


def _resolve_book_from_candidates(
    selection: str,
    books: list[BookRecord],
    *,
    language: str = "zh",
) -> BookRecord:
    query = selection.strip()
    if not query:
        raise ReaderError(tr(language, "book_resolve_missing"))

    if query.isdigit():
        index = int(query)
        if 1 <= index <= len(books):
            return books[index - 1]
        raise ReaderError(tr(language, "book_resolve_out_of_range"))

    for book in books:
        if book.id == query:
            return book

    prefix_matches = [book for book in books if book.id.startswith(query)]
    if len(prefix_matches) == 1:
        return prefix_matches[0]
    if len(prefix_matches) > 1:
        raise ReaderError(tr(language, "book_resolve_id_ambiguous", query=query))

    lowered = query.casefold()
    exact_title_matches = [
        book
        for book in books
        if book.title.casefold() == lowered or Path(book.path).name.casefold() == lowered
    ]
    if len(exact_title_matches) == 1:
        return exact_title_matches[0]
    if len(exact_title_matches) > 1:
        raise ReaderError(tr(language, "book_resolve_title_ambiguous", query=query))

    fuzzy_matches = [
        book
        for book in books
        if lowered in book.title.casefold() or lowered in Path(book.path).name.casefold()
    ]
    if len(fuzzy_matches) == 1:
        return fuzzy_matches[0]
    if len(fuzzy_matches) > 1:
        raise ReaderError(tr(language, "book_resolve_fuzzy_ambiguous", query=query))

    raise ReaderError(tr(language, "book_resolve_not_found", query=query))


def prompt_book_selection(
    books: list[BookRecord],
    *,
    screen_title: str,
    prompt_text: str,
    language: str = "zh",
) -> BookRecord | None:
    if not books:
        print(tr(language, "library_empty"))
        _pause(language)
        return None

    while True:
        clear_screen()
        print(screen_title)
        print()
        print_book_list(books, indexed=True, language=language)
        print()
        print(prompt_text)
        selection = _prompt_choice(tr(language, "select_book_prompt"))
        if not selection:
            return None
        if selection.lower() == "b":
            _run_boss_key_from_menu(language)
            continue
        try:
            return _resolve_book_from_candidates(selection, books, language=language)
        except ReaderError as exc:
            print(f"{tr(language, 'error_prefix')}: {exc}")
            _pause(language)


def interactive_import(library: Library) -> int:
    language = library.settings.language
    while True:
        clear_screen()
        print(tr(language, "import_title"))
        print()
        print(tr(language, "import_help"))
        print(_boss_key_menu_text(language))
        path_text = _prompt_choice(tr(language, "import_prompt"))
        if not path_text:
            return 0
        if path_text.lower() == "b":
            _run_boss_key_from_menu(language)
            continue

        normalized_path = _normalize_prompted_path(path_text)
        summary = library.import_path(Path(normalized_path))
        print()
        print_import_summary(summary, language=language)

        imported_books = summary.imported + summary.updated + summary.skipped
        if imported_books:
            while True:
                print()
                open_now = _prompt_choice(tr(language, "import_open_now")).strip().lower()
                if open_now == "b":
                    _run_boss_key_from_menu(language)
                    continue
                if open_now == "y":
                    if len(imported_books) == 1:
                        return open_book(library, imported_books[0].book, width=None, lines_per_page=None)
                    selected = prompt_book_selection(
                        [event.book for event in imported_books],
                        screen_title=tr(language, "library_recent_import_title"),
                        prompt_text=tr(language, "library_selection_prompt"),
                        language=language,
                    )
                    if selected is not None:
                        return open_book(library, selected, width=None, lines_per_page=None)
                break

        _pause(language)
        return 0


def run_library_browser(library: Library) -> int:
    search_query = ""
    while True:
        language = library.settings.language
        all_books = library.sorted_books()
        books = filter_books(all_books, search_query)
        clear_screen()
        print(tr(language, "library_title"))
        print()
        if not all_books:
            print(tr(language, "library_empty"))
            print()
            print(tr(language, "library_empty_action"))
            print(_boss_key_menu_text(language))
            print(tr(language, "library_empty_back"))
            print()
            selection = _prompt_choice(tr(language, "library_prompt")).strip().lower()
            if selection == "b":
                _run_boss_key_from_menu(language)
                continue
            if selection == "i":
                interactive_import(library)
                continue
            return 0

        reading_count = sum(1 for book in all_books if book.status == "reading")
        done_count = sum(1 for book in all_books if book.status == "done")
        print(
            tr(
                language,
                "library_overview",
                total=len(all_books),
                reading=reading_count,
                done=done_count,
            )
        )
        print()
        if search_query:
            print(
                tr(
                    language,
                    "library_filtered",
                    query=search_query,
                    count=len(books),
                )
            )
            print()
        if books:
            print_book_list(books, indexed=True, language=language)
        else:
            print(tr(language, "library_no_match"))
        print()
        print(tr(language, "library_open_hint"))
        selection = _prompt_choice(tr(language, "library_prompt")).strip()
        if not selection:
            return 0
        try:
            if selection.lower() == "b":
                _run_boss_key_from_menu(language)
                continue
            if selection.startswith("/"):
                query = selection[1:].strip()
                search_query = query
                continue
            if selection.lower() == "r":
                search_query = ""
                continue
            if selection.lower() == "i":
                interactive_import(library)
                continue
            if selection.lower() == "c":
                book = _most_recent_book_or_error(library, language)
                open_book(library, book, width=None, lines_per_page=None)
                continue
            book = _resolve_book_from_candidates(selection, books, language=language)
            open_book(library, book, width=None, lines_per_page=None)
        except ReaderError as exc:
            print(f"{tr(language, 'error_prefix')}: {exc}")
            _pause(language)


def run_settings(library: Library) -> int:
    while True:
        language = library.settings.language
        clear_screen()
        print(tr(language, "settings_title"))
        print()
        print(
            tr(
                language,
                "settings_current_language",
                value=_current_language_label(language),
            )
        )
        print()
        print(tr(language, "settings_menu_language_zh"))
        print(tr(language, "settings_menu_language_en"))
        print(_boss_key_menu_text(language))
        print(tr(language, "settings_menu_back"))
        print()
        choice = _prompt_choice(tr(language, "settings_prompt"))

        if choice in {"0", ""}:
            return 0

        if choice.lower() == "b":
            _run_boss_key_from_menu(language)
            continue

        if choice == "1":
            language = library.set_language("zh")
            print(
                tr(
                    language,
                    "settings_saved",
                    value=_current_language_label(language),
                )
            )
            _pause(language)
            continue

        if choice == "2":
            language = library.set_language("en")
            print(
                tr(
                    language,
                    "settings_saved",
                    value=_current_language_label(language),
                )
            )
            _pause(language)
            continue

        print(tr(language, "settings_invalid"))
        _pause(language)


def run_novel_launcher(library: Library) -> int:
    while True:
        language = library.settings.language
        clear_screen()
        print(tr(language, "novel_title"))
        print()
        print(tr(language, "novel_menu_import"))
        print(tr(language, "novel_menu_library"))
        print(tr(language, "novel_menu_continue"))
        print(_boss_key_menu_text(language))
        print(tr(language, "novel_menu_back"))
        print()
        choice = _prompt_choice(tr(language, "novel_menu_prompt"))

        try:
            if choice.lower() == "b":
                _run_boss_key_from_menu(language)
                continue

            if choice == "1":
                interactive_import(library)
                continue

            if choice == "2":
                run_library_browser(library)
                continue

            if choice == "3":
                book = _most_recent_book_or_error(library, language)
                open_book(library, book, width=None, lines_per_page=None)
                continue

            if choice in {"0", ""}:
                return 0

            print(tr(language, "novel_menu_invalid"))
            _pause(language)
        except ReaderError as exc:
            print(f"{tr(language, 'error_prefix')}: {exc}")
            _pause(language)


def run_launcher(library: Library) -> int:
    while True:
        language = library.settings.language
        clear_screen()
        _print_launcher_block(language)
        choice = _prompt_choice(f"{LAUNCHER_LEFT_PADDING}{tr(language, 'main_menu_prompt')}")

        if choice == "1":
            run_novel_launcher(library)
            continue

        if choice == "2":
            run_settings(library)
            continue

        if choice.lower() == "b":
            _run_boss_key_from_menu(language)
            continue

        if choice in {"0", "", "q", "quit", "exit"}:
            return 0

        print(tr(language, "main_menu_invalid"))
        _pause(language)


def open_book(
    library: Library,
    book: BookRecord,
    width: int | None,
    lines_per_page: int | None,
    *,
    start_page: int = 1,
    fresh: bool = False,
) -> int:
    start_offset = 0 if fresh else book.progress.cursor_offset

    def current_bookmarks() -> list[BookmarkEntry]:
        return [
            BookmarkEntry(
                id=bookmark.id,
                offset=bookmark.offset,
                created_at=bookmark.created_at,
                excerpt=bookmark.excerpt,
                note=bookmark.note,
            )
            for bookmark in sorted(book.bookmarks, key=lambda item: (item.offset, item.created_at))
        ]

    def persist_progress(cursor_offset: int, furthest_offset: int, total_chars: int) -> None:
        book.total_chars = total_chars
        library.update_progress(book.id, cursor_offset, furthest_offset)

    def persist_bookmark(offset: int, excerpt: str, note: str) -> list[BookmarkEntry]:
        updated_book = library.add_bookmark(book.id, offset, excerpt, note)
        book.bookmarks = updated_book.bookmarks
        return current_bookmarks()

    return run_file_reader(
        Path(book.path),
        encoding=book.encoding,
        width=width,
        lines_per_page=lines_per_page,
        start_page=start_page,
        start_offset=start_offset,
        furthest_offset=book.progress.furthest_offset,
        progress_callback=persist_progress,
        bookmarks=current_bookmarks(),
        bookmark_add_callback=persist_bookmark,
        ui_language=library.settings.language,
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    library = Library.load()

    try:
        if args.command is None:
            if _is_interactive_terminal():
                return run_launcher(library)
            parser.print_help()
            return 0

        if args.command == "read":
            candidate_path = Path(args.path).expanduser().resolve()
            if candidate_path.is_dir():
                raise ReaderError("`relaxsh read` only accepts one TXT file. Use `relaxsh import` for folders.")
            event = library.import_file(candidate_path, encoding=args.encoding)
            if args.encoding:
                event.book.encoding = args.encoding
            library.save()
            book = event.book
            return open_book(
                library,
                book,
                width=args.width,
                lines_per_page=args.lines,
                start_page=args.start_page,
                fresh=args.fresh,
            )

        if args.command == "demo":
            return run_demo_reader(
                width=args.width,
                lines_per_page=args.lines,
                start_page=args.start_page,
                ui_language=library.settings.language,
            )

        if args.command == "import":
            summary = library.import_path(Path(args.path))
            print_import_summary(summary, language=library.settings.language)
            return 0 if not summary.errors else 1

        if args.command == "library":
            print_library(library.sorted_books(), language=library.settings.language)
            return 0

        if args.command == "open":
            book = library.resolve_book(args.book)
            return open_book(
                library,
                book,
                width=args.width,
                lines_per_page=args.lines,
                fresh=args.fresh,
            )

        if args.command == "continue":
            book = library.most_recent_book()
            return open_book(
                library,
                book,
                width=args.width,
                lines_per_page=args.lines,
            )

        if args.command == "version":
            print(f"relaxsh {__version__}")
            return 0
    except ReaderError as exc:
        print(f"{tr(library.settings.language, 'error_prefix')}: {exc}", file=sys.stderr)
        return 1

    parser.print_help()
    return 1
