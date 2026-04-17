from __future__ import annotations

import contextlib
import io
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from relaxsh.cli import (
    _compose_launcher_lines,
    _center_line,
    _normalize_prompted_path,
    _render_launcher_mascot,
    _strip_ansi,
    filter_books,
    main,
    run_library_browser,
    run_novel_launcher,
    run_settings,
)
from relaxsh.display import text_width
from relaxsh.library import BookRecord, Library
from relaxsh.reader import (
    BookmarkEntry,
    DEFAULT_ENCODINGS,
    ReaderSession,
    decode_posix_escape_sequence,
    load_text,
    render_screen,
    resolve_boss_command,
)


class DummyKeyReader:
    def __init__(self, keys: list[str]) -> None:
        self._keys = iter(keys)
        self.external_commands: list[list[str]] = []

    def read_key(self) -> str:
        return next(self._keys)

    def run_external(self, command: list[str]) -> None:
        self.external_commands.append(command)


def make_book_record(title: str, path: Path) -> BookRecord:
    return BookRecord(
        id=title.lower().replace(" ", "-"),
        title=title,
        path=str(path),
        added_at="2026-01-01T00:00:00+00:00",
        updated_at="2026-01-01T00:00:00+00:00",
        size_bytes=10,
        modified_at_ns=0,
        total_chars=100,
        content_sha1=f"sha1-{title}",
    )


class CliTests(unittest.TestCase):
    def test_normalize_prompted_path_handles_shell_escaped_posix_input(self) -> None:
        raw = r"/Users/xgy/Downloads/梦河夜航\ \(严雪芥\)\ \(z-library.sk\,\ 1lib.sk\,\ z-lib.sk\).txt"

        normalized = _normalize_prompted_path(raw)

        self.assertEqual(
            normalized,
            "/Users/xgy/Downloads/梦河夜航 (严雪芥) (z-library.sk, 1lib.sk, z-lib.sk).txt",
        )

    def test_normalize_prompted_path_unwraps_quoted_path(self) -> None:
        raw = '"/Users/xgy/Downloads/demo novel.txt"'

        normalized = _normalize_prompted_path(raw)

        self.assertEqual(normalized, "/Users/xgy/Downloads/demo novel.txt")

    def test_normalize_prompted_path_handles_shell_escaped_windows_style_input(self) -> None:
        raw = "C:\\Users\\xgy\\AppData\\Local\\Temp\\demo\\ novel\\ \\(test\\).txt"

        normalized = _normalize_prompted_path(raw)

        self.assertEqual(
            normalized,
            "C:\\Users\\xgy\\AppData\\Local\\Temp\\demo novel (test).txt",
        )

    def test_launcher_imports_folder_from_interactive_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novels_dir = Path(tmpdir) / "novels"
                novels_dir.mkdir()
                (novels_dir / "alpha.txt").write_text("alpha", encoding="utf-8")
                (novels_dir / "beta.txt").write_text("beta", encoding="utf-8")

                stdout = io.StringIO()
                with patch("builtins.input", side_effect=["1", "1", str(novels_dir), "n", "", "0", "0"]), patch(
                    "relaxsh.cli._is_interactive_terminal", return_value=True
                ), patch("relaxsh.cli.clear_screen"), contextlib.redirect_stdout(stdout):
                    exit_code = main([])

                library = Library.load()

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertEqual(len(library.books), 2)
        self.assertIn("小说阅读", output)
        self.assertNotIn("打开演示文本", output)
        self.assertIn("导入结果", output)

    def test_launcher_settings_can_switch_to_english_and_persist(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                stdout = io.StringIO()
                with patch("builtins.input", side_effect=["2", "2", "", "0", "0"]), patch(
                    "relaxsh.cli._is_interactive_terminal", return_value=True
                ), patch("relaxsh.cli.clear_screen"), contextlib.redirect_stdout(stdout):
                    exit_code = main([])

                library = Library.load()

        self.assertEqual(exit_code, 0)
        self.assertEqual(library.settings.language, "en")
        self.assertIn("Settings", stdout.getvalue())
        self.assertIn("Language switched to English.", stdout.getvalue())

    def test_launcher_boss_label_shows_posix_return_hint(self) -> None:
        with patch("relaxsh.cli.os.name", "posix"):
            lines = _compose_launcher_lines("zh", use_color=False)

        self.assertTrue(any("b. 老板键（q 键退出）" in line for line in lines))

    def test_launcher_boss_label_shows_windows_return_hint(self) -> None:
        with patch("relaxsh.cli.os.name", "nt"):
            lines = _compose_launcher_lines("zh", use_color=False)

        self.assertTrue(any("b. 老板键（关闭任务管理器返回）" in line for line in lines))

    def test_launcher_boss_key_runs_native_command_from_main_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                with patch("builtins.input", side_effect=["b", "0"]), patch(
                    "relaxsh.cli._is_interactive_terminal", return_value=True
                ), patch("relaxsh.cli.clear_screen"), patch(
                    "relaxsh.cli.resolve_boss_command", return_value=(["/usr/bin/top"], "top")
                ), patch("relaxsh.cli.subprocess.run") as run_mock, contextlib.redirect_stdout(io.StringIO()):
                    exit_code = main([])

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(["/usr/bin/top"], check=False)

    def test_settings_menu_boss_key_runs_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                with patch("builtins.input", side_effect=["b", "0"]), patch(
                    "relaxsh.cli.clear_screen"
                ), patch("relaxsh.cli.resolve_boss_command", return_value=(["/usr/bin/top"], "top")), patch(
                    "relaxsh.cli.subprocess.run"
                ) as run_mock, contextlib.redirect_stdout(io.StringIO()):
                    exit_code = run_settings(library)

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(["/usr/bin/top"], check=False)

    def test_novel_menu_boss_key_runs_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                with patch("builtins.input", side_effect=["b", "0"]), patch(
                    "relaxsh.cli.clear_screen"
                ), patch("relaxsh.cli.resolve_boss_command", return_value=(["/usr/bin/top"], "top")), patch(
                    "relaxsh.cli.subprocess.run"
                ) as run_mock, contextlib.redirect_stdout(io.StringIO()):
                    exit_code = run_novel_launcher(library)

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(["/usr/bin/top"], check=False)

    def test_library_browser_boss_key_runs_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("alpha", encoding="utf-8")
                library = Library.load()
                library.import_file(novel)
                library.save()

                with patch("builtins.input", side_effect=["b", ""]), patch(
                    "relaxsh.cli.clear_screen"
                ), patch("relaxsh.cli.resolve_boss_command", return_value=(["/usr/bin/top"], "top")), patch(
                    "relaxsh.cli.subprocess.run"
                ) as run_mock, contextlib.redirect_stdout(io.StringIO()):
                    exit_code = run_library_browser(library)

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(["/usr/bin/top"], check=False)

    def test_import_menu_boss_key_runs_native_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                with patch("builtins.input", side_effect=["1", "1", "b", "", "0", "0"]), patch(
                    "relaxsh.cli._is_interactive_terminal", return_value=True
                ), patch("relaxsh.cli.clear_screen"), patch(
                    "relaxsh.cli.resolve_boss_command", return_value=(["/usr/bin/top"], "top")
                ), patch("relaxsh.cli.subprocess.run") as run_mock, contextlib.redirect_stdout(io.StringIO()):
                    exit_code = main([])

        self.assertEqual(exit_code, 0)
        run_mock.assert_called_once_with(["/usr/bin/top"], check=False)

    def test_launcher_mascot_renders_block_fallback(self) -> None:
        lines = _render_launcher_mascot(use_color=False)

        self.assertGreaterEqual(len(lines), 4)
        self.assertTrue(any("█" in line for line in lines))
        self.assertTrue(any("▓" in line or "▒" in line or "░" in line for line in lines))

    def test_center_line_uses_visible_width_for_ansi_text(self) -> None:
        centered = _center_line("\x1b[31m██\x1b[0m")

        self.assertTrue(centered.startswith(" "))
        self.assertTrue(_strip_ansi(centered).rstrip().endswith("██"))

    def test_launcher_places_mascot_above_menu(self) -> None:
        with patch("shutil.get_terminal_size", return_value=os.terminal_size((100, 24))):
            lines = _compose_launcher_lines("zh", use_color=False)

        title_index = next(index for index, line in enumerate(lines) if "RelaxSH" in line)
        cat_index = next(
            index
            for index, line in enumerate(lines)
            if "█" in line or "▓" in line or "▒" in line or "░" in line
        )
        self.assertLess(cat_index, title_index)

    def test_novel_launcher_does_not_render_home_mascot(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                stdout = io.StringIO()
                with patch("builtins.input", side_effect=["0"]), patch(
                    "relaxsh.cli.clear_screen"
                ), contextlib.redirect_stdout(stdout):
                    exit_code = run_novel_launcher(library)

        self.assertEqual(exit_code, 0)
        self.assertNotIn("███    ███", stdout.getvalue())

    def test_launcher_imports_shell_escaped_file_path_from_interactive_menu(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "demo novel (test).txt"
                novel.write_text("alpha", encoding="utf-8")
                escaped_path = str(novel).replace(" ", r"\ ").replace("(", r"\(").replace(")", r"\)")

                stdout = io.StringIO()
                with patch(
                    "builtins.input",
                    side_effect=["1", "1", escaped_path, "n", "", "0", "0"],
                ), patch("relaxsh.cli._is_interactive_terminal", return_value=True), patch(
                    "relaxsh.cli.clear_screen"
                ), contextlib.redirect_stdout(stdout):
                    exit_code = main([])

                library = Library.load()

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(library.books), 1)
        self.assertEqual(library.books[0].title, "demo novel (test)")

    def test_launcher_can_open_book_by_index_from_library_browser(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                alpha = Path(tmpdir) / "alpha.txt"
                beta = Path(tmpdir) / "beta.txt"
                alpha.write_text("alpha", encoding="utf-8")
                beta.write_text("beta", encoding="utf-8")

                library = Library.load()
                first = library.import_file(alpha).book
                second = library.import_file(beta).book
                library.save()
                expected_second_entry = library.sorted_books()[1]

                stdout = io.StringIO()
                with patch("builtins.input", side_effect=["1", "2", "2", "", "0", "0"]), patch(
                    "relaxsh.cli._is_interactive_terminal", return_value=True
                ), patch("relaxsh.cli.clear_screen"), patch(
                    "relaxsh.cli.open_book", return_value=0
                ) as open_book_mock, contextlib.redirect_stdout(stdout):
                    exit_code = main([])

        self.assertEqual(exit_code, 0)
        open_book_mock.assert_called_once()
        opened_book = open_book_mock.call_args.args[1]
        self.assertEqual(opened_book.id, expected_second_entry.id)
        self.assertIn("书架", stdout.getvalue())

    def test_import_menu_open_now_uses_only_imported_books(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                existing = Path(tmpdir) / "existing.txt"
                existing.write_text("existing", encoding="utf-8")
                library = Library.load()
                existing_book = library.import_file(existing).book
                library.save()

                novels_dir = Path(tmpdir) / "novels"
                novels_dir.mkdir()
                alpha = novels_dir / "alpha.txt"
                beta = novels_dir / "beta.txt"
                alpha.write_text("alpha", encoding="utf-8")
                beta.write_text("beta", encoding="utf-8")

                stdout = io.StringIO()
                with patch(
                    "builtins.input",
                    side_effect=["1", "1", str(novels_dir), "y", "2", "0", "0"],
                ), patch("relaxsh.cli._is_interactive_terminal", return_value=True), patch(
                    "relaxsh.cli.clear_screen"
                ), patch("relaxsh.cli.open_book", return_value=0) as open_book_mock, contextlib.redirect_stdout(
                    stdout
                ):
                    exit_code = main([])

        self.assertEqual(exit_code, 0)
        open_book_mock.assert_called_once()
        opened_book = open_book_mock.call_args.args[1]
        self.assertNotEqual(opened_book.id, existing_book.id)
        self.assertIn(opened_book.title, {"alpha", "beta"})
        self.assertIn("刚导入的书", stdout.getvalue())

    def test_library_browser_search_filters_books_before_opening(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                alpha = Path(tmpdir) / "alpha.txt"
                beta = Path(tmpdir) / "beta-story.txt"
                alpha.write_text("alpha", encoding="utf-8")
                beta.write_text("beta", encoding="utf-8")

                library = Library.load()
                alpha_book = library.import_file(alpha).book
                beta_book = library.import_file(beta).book
                library.save()

                stdout = io.StringIO()
                with patch(
                    "builtins.input",
                    side_effect=["1", "2", "/beta", "1", "", "0", "0"],
                ), patch("relaxsh.cli._is_interactive_terminal", return_value=True), patch(
                    "relaxsh.cli.clear_screen"
                ), patch("relaxsh.cli.open_book", return_value=0) as open_book_mock, contextlib.redirect_stdout(
                    stdout
                ):
                    exit_code = main([])

        self.assertEqual(exit_code, 0)
        open_book_mock.assert_called_once()
        opened_book = open_book_mock.call_args.args[1]
        self.assertEqual(opened_book.id, beta_book.id)
        self.assertNotEqual(opened_book.id, alpha_book.id)
        self.assertIn("当前筛选: beta", stdout.getvalue())

    def test_filter_books_matches_title_and_path_terms(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            alpha = make_book_record("Alpha Story", Path(tmpdir) / "alpha-story.txt")
            beta = make_book_record("Beta Novel", Path(tmpdir) / "nested" / "beta.txt")

            filtered = filter_books([alpha, beta], "beta nested")

        self.assertEqual([book.title for book in filtered], ["Beta Novel"])

    def test_library_command_prints_imported_books(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("第一章\n开始了。", encoding="utf-8")

                library = Library.load()
                book = library.import_file(novel).book
                library.update_progress(book.id, cursor_offset=3, furthest_offset=6)

                stdout = io.StringIO()
                with contextlib.redirect_stdout(stdout):
                    exit_code = main(["library"])

        output = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("alpha", output)
        self.assertIn("进度", output)
        self.assertIn("%", output)

    def test_read_command_rejects_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novels_dir = Path(tmpdir) / "novels"
                novels_dir.mkdir()

                stderr = io.StringIO()
                with contextlib.redirect_stderr(stderr):
                    exit_code = main(["read", str(novels_dir)])

        self.assertEqual(exit_code, 1)
        self.assertIn("only accepts one TXT file", stderr.getvalue())

    def test_read_command_imports_file_in_non_interactive_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("one\ntwo\nthree", encoding="utf-8")

                stdout = io.StringIO()
                with patch("sys.stdin.isatty", return_value=False), patch(
                    "sys.stdout.isatty", return_value=False
                ):
                    with contextlib.redirect_stdout(stdout):
                        exit_code = main(["read", str(novel)])

                library = Library.load()

        self.assertEqual(exit_code, 0)
        self.assertIn("one", stdout.getvalue())
        self.assertEqual(len(library.books), 1)

    def test_reader_session_uses_saved_offsets(self) -> None:
        session = ReaderSession.from_text(
            text="alpha beta gamma delta\nepsilon zeta eta theta",
            source_name="unit.txt",
            width=20,
            lines_per_page=3,
        )

        second_page = session.pages[1]

        self.assertGreater(len(session.pages), 1)
        self.assertEqual(session.page_index_for_offset(second_page.start_offset), 1)
        self.assertGreater(session.progress_percent(1), session.progress_percent(0))

    def test_decode_posix_escape_sequence_supports_common_arrow_variants(self) -> None:
        self.assertEqual(decode_posix_escape_sequence("[C"), "right")
        self.assertEqual(decode_posix_escape_sequence("[D"), "left")
        self.assertEqual(decode_posix_escape_sequence("OC"), "right")
        self.assertEqual(decode_posix_escape_sequence("OD"), "left")
        self.assertEqual(decode_posix_escape_sequence("[1;5C"), "right")
        self.assertEqual(decode_posix_escape_sequence("[1;9D"), "left")

    def test_reader_detects_chapters_and_browses_to_selected_one(self) -> None:
        text = (
            "第1章 初见\n"
            "alpha line 1\n"
            "alpha line 2\n"
            "\n"
            "第2章 出发\n"
            "beta line 1\n"
            "beta line 2\n"
            "\n"
            "Chapter 3 Finale\n"
            "gamma line 1\n"
        )
        session = ReaderSession.from_text(
            text=text,
            source_name="chapters.txt",
            width=20,
            lines_per_page=4,
        )

        self.assertEqual(
            [chapter.title for chapter in session.chapters],
            ["第1章 初见", "第2章 出发", "Chapter 3 Finale"],
        )

        second_line = session.line_index_for_offset(session.chapters[1].start_offset)
        second_page = session.page_index_for_offset(session.chapters[1].start_offset)
        third_page = session.page_index_for_offset(session.chapters[2].start_offset)

        self.assertEqual(session.adjacent_chapter_page_index(second_page, -1), 0)
        self.assertEqual(session.adjacent_chapter_page_index(second_page, 1), third_page)

        with patch("relaxsh.reader.clear_screen"), contextlib.redirect_stdout(io.StringIO()):
            selected_page = session.browse_chapters(0, DummyKeyReader(["2"]))

        self.assertEqual(selected_page, second_line)

    def test_chapter_browser_lines_fit_terminal_width_with_chinese_titles(self) -> None:
        text = "\n".join(
            [f"第{index}章 章节标题很长很长很长\n内容{index}" for index in range(1, 12)]
        )
        session = ReaderSession.from_text(
            text=text,
            source_name="chapters.txt",
            width=32,
            lines_per_page=6,
        )

        rendered = session.format_chapter_browser(0, 0)

        for line in rendered.splitlines():
            self.assertLessEqual(text_width(line), session.width)

    def test_chapter_browser_hides_progress_percentages(self) -> None:
        text = "\n".join(
            [f"第{index}章 标题\n内容{index}" for index in range(1, 4)]
        )
        session = ReaderSession.from_text(
            text=text,
            source_name="chapters.txt",
            width=32,
            lines_per_page=6,
            furthest_offset=6,
        )

        rendered = session.format_chapter_browser(0, 0)

        self.assertNotIn("%", rendered)
        self.assertIn("6/", rendered)
        self.assertIn("字", rendered)

    def test_reader_page_renders_progress_and_current_chapter(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 初见\nalpha line 1\nalpha line 2\n\n第2章 出发\nbeta line 1\n",
            source_name="render.txt",
            width=48,
            lines_per_page=4,
            furthest_offset=8,
        )

        rendered = session.format_page(0)

        self.assertIn("RelaxSH | render.txt | 第 1/", rendered)
        self.assertIn("章节: 第1章 初见 |", rendered)
        self.assertIn("/", rendered)
        self.assertIn("字", rendered)
        self.assertIn("[d] 下一页", rendered)
        self.assertIn("[s] 下移一行", rendered)
        self.assertIn("%", rendered)

    def test_reader_page_can_render_in_english_when_requested(self) -> None:
        session = ReaderSession.from_text(
            text="Chapter 1 Start\nalpha line 1\n",
            source_name="render-en.txt",
            width=48,
            lines_per_page=4,
            furthest_offset=5,
            ui_language="en",
        )

        rendered = session.format_page(0)

        self.assertIn("RelaxSH | render-en.txt | Page 1/", rendered)
        self.assertIn("Chapter: Chapter 1 Start |", rendered)
        self.assertIn("chars", rendered)
        self.assertIn("[d] next", rendered)
        self.assertIn("[s] down 1 line", rendered)

    def test_reader_page_chapter_progress_tracks_current_view(self) -> None:
        session = ReaderSession.from_text(
            text=(
                "第1章 开始\n"
                "alpha alpha alpha\n"
                "\n"
                "第2章 继续\n"
                "beta beta beta\n"
                "gamma gamma gamma\n"
                "delta delta delta\n"
                "omega omega omega\n"
            ),
            source_name="chapter-live.txt",
            width=80,
            lines_per_page=3,
            furthest_offset=9999,
            ui_language="zh",
        )

        chapter_two_index = 1
        chapter_two_line = session.line_index_for_offset(session.chapters[chapter_two_index].start_offset)
        current_page = session.page_for_line_index(chapter_two_line)
        current_read, current_total = session.chapter_read_stats_for_offset(
            chapter_two_index,
            current_page.end_offset,
        )
        furthest_read, _ = session.chapter_read_stats(chapter_two_index)

        rendered = session.format_page(chapter_two_line)

        self.assertLess(current_read, furthest_read)
        self.assertIn(f"{current_read}/{current_total}字", rendered)
        self.assertNotIn(f"{furthest_read}/{current_total}字", rendered)

    def test_reader_footer_shows_windows_boss_key_hint(self) -> None:
        session = ReaderSession.from_text(
            text="Chapter 1 Start\nalpha line 1\n",
            source_name="render-en.txt",
            width=96,
            lines_per_page=4,
            furthest_offset=5,
            ui_language="zh",
        )

        with patch("relaxsh.reader.os.name", "nt"):
            footer = session._reader_footer()

        self.assertIn("关任务管理器返回", footer)

    def test_reader_page_wraps_footer_without_ellipsis_on_narrow_width(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 初见\nalpha line 1\nalpha line 2\n",
            source_name="narrow.txt",
            width=36,
            lines_per_page=4,
            ui_language="zh",
        )

        rendered = session.format_page(0)
        lines = rendered.splitlines()
        footer_start = max(index for index, line in enumerate(lines) if set(line) == {"="}) + 1
        footer_lines = lines[footer_start:]

        self.assertTrue(any("[d]" in line or "[d/a]" in line for line in footer_lines))
        self.assertTrue(any("[b]老板" in line for line in footer_lines))
        self.assertTrue(all("..." not in line for line in footer_lines))
        for line in footer_lines:
            self.assertLessEqual(text_width(line), session.width)

    def test_reader_auto_layout_refreshes_after_terminal_resize(self) -> None:
        with patch(
            "relaxsh.reader.shutil.get_terminal_size",
            return_value=os.terminal_size((80, 18)),
        ):
            session = ReaderSession.from_text(
                text="第1章 初见\n" + ("alpha beta gamma\n" * 20),
                source_name="resize.txt",
                width=None,
                lines_per_page=None,
                ui_language="zh",
            )

        initial_width = session.width
        initial_lines = session.lines_per_page

        with patch(
            "relaxsh.reader.shutil.get_terminal_size",
            return_value=os.terminal_size((44, 16)),
        ):
            top_line_index = session.refresh_layout_for_line_index(0)

        rendered = session.format_page(top_line_index)
        lines = rendered.splitlines()
        footer_start = max(index for index, line in enumerate(lines) if set(line) == {"="}) + 1
        footer_lines = lines[footer_start:]

        self.assertEqual(top_line_index, 0)
        self.assertLess(session.width, initial_width)
        self.assertLess(session.lines_per_page, initial_lines)
        self.assertTrue(any("[d]" in line or "[d/a]" in line for line in footer_lines))
        self.assertTrue(all("..." not in line for line in footer_lines))

    def test_boss_screen_renders_disguise_mode_dashboard(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 初见\nalpha line 1\n",
            source_name="boss.txt",
            width=40,
            lines_per_page=6,
        )

        rendered = session.format_boss_screen()

        self.assertIn("运维看板", rendered)
        self.assertIn("发布监控", rendered)
        self.assertIn("报表构建", rendered)
        self.assertNotIn("阅读器", rendered)

    def test_resolve_boss_command_prefers_top_on_posix(self) -> None:
        with patch("relaxsh.reader.os.name", "posix"), patch(
            "relaxsh.reader.shutil.which",
            side_effect=lambda name: "/usr/bin/top" if name == "top" else None,
        ):
            command = resolve_boss_command()

        self.assertEqual(command, (["/usr/bin/top"], "top"))

    def test_resolve_boss_command_prefers_taskmgr_on_windows(self) -> None:
        with patch("relaxsh.reader.os.name", "nt"), patch.dict(
            os.environ,
            {},
            clear=True,
        ), patch(
            "relaxsh.reader.os.path.isfile",
            return_value=False,
        ), patch(
            "relaxsh.reader.shutil.which",
            side_effect=lambda name: r"C:\Windows\System32\taskmgr.exe" if name == "taskmgr.exe" else None,
        ):
            command = resolve_boss_command()

        self.assertEqual(command, ([r"C:\Windows\System32\taskmgr.exe"], "taskmgr"))

    def test_resolve_boss_command_uses_windows_system_root_when_path_lookup_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            windows_root = Path(tmpdir) / "Windows"
            system32 = windows_root / "System32"
            system32.mkdir(parents=True)
            taskmgr = system32 / "Taskmgr.exe"
            taskmgr.write_text("", encoding="utf-8")

            with patch("relaxsh.reader.os.name", "nt"), patch.dict(
                os.environ,
                {"WINDIR": str(windows_root)},
                clear=False,
            ), patch("relaxsh.reader.shutil.which", return_value=None):
                command = resolve_boss_command()

        self.assertEqual(command, ([str(taskmgr)], "taskmgr"))

    def test_trigger_boss_key_runs_external_command_when_available(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 初见\nalpha line 1\n",
            source_name="boss.txt",
            width=40,
            lines_per_page=6,
        )
        input_reader = DummyKeyReader([])

        with patch("relaxsh.reader.resolve_boss_command", return_value=(["/usr/bin/top"], "top")):
            launched, status = session.trigger_boss_key(input_reader)

        self.assertTrue(launched)
        self.assertIn("top", status)
        self.assertEqual(input_reader.external_commands, [["/usr/bin/top"]])

    def test_trigger_boss_key_falls_back_when_no_external_command_exists(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 初见\nalpha line 1\n",
            source_name="boss.txt",
            width=40,
            lines_per_page=6,
        )

        with patch("relaxsh.reader.resolve_boss_command", return_value=None):
            launched, status = session.trigger_boss_key(DummyKeyReader([]))

        self.assertFalse(launched)
        self.assertEqual(status, "")

    def test_render_screen_uses_ansi_redraw_when_supported(self) -> None:
        stdout = io.StringIO()
        with patch("relaxsh.reader._supports_ansi_screen_redraw", return_value=True), patch(
            "relaxsh.reader.clear_screen"
        ) as clear_mock, contextlib.redirect_stdout(stdout):
            render_screen("frame")

        self.assertEqual(stdout.getvalue(), "\x1b[H\x1b[Jframe")
        clear_mock.assert_not_called()

    def test_render_screen_falls_back_to_clear_screen_when_ansi_is_unavailable(self) -> None:
        stdout = io.StringIO()
        with patch("relaxsh.reader._supports_ansi_screen_redraw", return_value=False), patch(
            "relaxsh.reader.clear_screen"
        ) as clear_mock, contextlib.redirect_stdout(stdout):
            render_screen("frame")

        self.assertEqual(stdout.getvalue(), "frame")
        clear_mock.assert_called_once_with()

    def test_reader_search_finds_next_match_and_wraps(self) -> None:
        session = ReaderSession.from_text(
            text="alpha start\nbeta middle\nalpha finale",
            source_name="search.txt",
            width=20,
            lines_per_page=3,
        )

        target_page, status = session.search_page_index("alpha", 0, repeat=True)

        self.assertEqual(target_page, 0)
        self.assertIn("回卷", status)

    def test_reader_bookmark_browser_jumps_to_selected_bookmark(self) -> None:
        session = ReaderSession.from_text(
            text="第1章 开始\nA\nB\n\n第2章 继续\nC\nD\n\n第3章 终章\nE\n",
            source_name="bookmarks.txt",
            width=20,
            lines_per_page=4,
        )
        bookmarks = [
            BookmarkEntry(
                id="one",
                offset=session.pages[0].start_offset,
                created_at="2026-01-01T00:00:00+00:00",
                excerpt="第一章",
                note="开头",
            ),
            BookmarkEntry(
                id="two",
                offset=session.pages[1].start_offset,
                created_at="2026-01-01T00:05:00+00:00",
                excerpt="第二章",
                note="中段",
            ),
        ]

        with patch("relaxsh.reader.clear_screen"), contextlib.redirect_stdout(io.StringIO()):
            selected_page = session.browse_bookmarks(0, bookmarks, DummyKeyReader(["2"]))

        self.assertEqual(selected_page, session.line_index_for_offset(bookmarks[1].offset))

    def test_load_text_supports_utf8_sig(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "utf8-sig.txt"
            path.write_text("hello", encoding="utf-8-sig")

            content = load_text(path)

        self.assertEqual(content, "hello")
        self.assertIn("gb18030", DEFAULT_ENCODINGS)


if __name__ == "__main__":
    unittest.main()
