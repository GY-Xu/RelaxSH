from __future__ import annotations

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

from relaxsh.library import Library, get_state_path


class LibraryTests(unittest.TestCase):
    def test_import_single_file_persists_library_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("第一章\n开始了。", encoding="utf-8")

                library = Library.load()
                event = library.import_file(novel)
                library.save()

                reloaded = Library.load()

        self.assertEqual(event.status, "imported")
        self.assertEqual(len(reloaded.books), 1)
        self.assertEqual(reloaded.books[0].title, "alpha")
        self.assertGreater(reloaded.books[0].total_chars, 0)
        self.assertTrue(get_state_path().name.endswith("library.json"))

    def test_directory_import_skips_duplicate_content(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novels_dir = Path(tmpdir) / "novels"
                novels_dir.mkdir()
                (novels_dir / "a.txt").write_text("same story", encoding="utf-8")
                (novels_dir / "b.txt").write_text("same story", encoding="utf-8")
                (novels_dir / "c.txt").write_text("different story", encoding="utf-8")

                library = Library.load()
                summary = library.import_path(novels_dir)

        self.assertEqual(len(library.books), 2)
        self.assertEqual(len(summary.imported), 2)
        self.assertEqual(len(summary.skipped), 1)

    def test_progress_is_stored_per_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                alpha = Path(tmpdir) / "alpha.txt"
                beta = Path(tmpdir) / "beta.txt"
                alpha.write_text("alpha book text", encoding="utf-8")
                beta.write_text("beta book text", encoding="utf-8")

                library = Library.load()
                alpha_book = library.import_file(alpha).book
                beta_book = library.import_file(beta).book
                library.save()

                library.update_progress(alpha_book.id, cursor_offset=5, furthest_offset=9)
                library.update_progress(beta_book.id, cursor_offset=1, furthest_offset=3)

                reloaded = Library.load()
                alpha_loaded = reloaded.resolve_book(alpha_book.id)
                beta_loaded = reloaded.resolve_book(beta_book.id)

        self.assertEqual(alpha_loaded.progress.cursor_offset, 5)
        self.assertEqual(alpha_loaded.progress.furthest_offset, 9)
        self.assertEqual(beta_loaded.progress.cursor_offset, 1)
        self.assertEqual(beta_loaded.progress.furthest_offset, 3)
        self.assertGreater(alpha_loaded.percent_read, beta_loaded.percent_read)

    def test_bookmarks_are_persisted_per_book(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("alpha book text", encoding="utf-8")

                library = Library.load()
                book = library.import_file(novel).book
                library.save()

                library.add_bookmark(book.id, offset=4, excerpt="alpha line", note="名场面")
                library.add_bookmark(book.id, offset=9, excerpt="book text", note="")

                reloaded = Library.load()
                loaded = reloaded.resolve_book(book.id)

        self.assertEqual(loaded.bookmark_count, 2)
        self.assertEqual(loaded.bookmarks[0].offset, 4)
        self.assertEqual(loaded.bookmarks[0].note, "名场面")
        self.assertEqual(loaded.bookmarks[1].excerpt, "book text")

    def test_resolve_book_accepts_id_prefix(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                novel = Path(tmpdir) / "alpha.txt"
                novel.write_text("alpha book text", encoding="utf-8")

                library = Library.load()
                book = library.import_file(novel).book

                resolved = library.resolve_book(book.id[:8])

        self.assertEqual(resolved.id, book.id)

    def test_settings_language_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()

                language = library.set_language("en")
                reloaded = Library.load()

        self.assertEqual(language, "en")
        self.assertEqual(reloaded.settings.language, "en")

    def test_2048_state_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                library.save_2048_state(
                    [[2, 2, 0, 0], [4, 8, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                    128,
                    won=True,
                )
                reloaded = Library.load()

        self.assertEqual(reloaded.game_2048.score, 128)
        self.assertEqual(reloaded.game_2048.best_score, 128)
        self.assertEqual(reloaded.game_2048.board[0][:2], [2, 2])
        self.assertTrue(reloaded.game_2048.won)
        self.assertTrue(reloaded.game_2048.has_saved_game)

    def test_clear_2048_state_keeps_best_score(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                library.save_2048_state(
                    [[2, 4, 0, 0], [0, 8, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]],
                    256,
                )
                cleared = library.clear_2048_state()
                reloaded = Library.load()

        self.assertEqual(cleared.best_score, 256)
        self.assertEqual(reloaded.game_2048.best_score, 256)
        self.assertEqual(reloaded.game_2048.board, [])
        self.assertFalse(reloaded.game_2048.has_saved_game)

    def test_gomoku_state_is_persisted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                board = [["" for _ in range(11)] for _ in range(11)]
                board[5][5] = "X"
                board[5][6] = "O"
                library.save_gomoku_state(
                    board,
                    cursor_row=5,
                    cursor_col=7,
                    winner="",
                    game_over=False,
                )
                reloaded = Library.load()

        self.assertEqual(reloaded.game_gomoku.cursor_row, 5)
        self.assertEqual(reloaded.game_gomoku.cursor_col, 7)
        self.assertEqual(reloaded.game_gomoku.board[5][5], "X")
        self.assertEqual(reloaded.game_gomoku.board[5][6], "O")
        self.assertTrue(reloaded.game_gomoku.has_saved_game)

    def test_clear_gomoku_state_removes_saved_board(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"RELAXSH_HOME": str(Path(tmpdir) / "state")}):
                library = Library.load()
                board = [["" for _ in range(11)] for _ in range(11)]
                board[5][5] = "X"
                library.save_gomoku_state(
                    board,
                    cursor_row=5,
                    cursor_col=5,
                )
                cleared = library.clear_gomoku_state()
                reloaded = Library.load()

        self.assertEqual(cleared.board, [])
        self.assertEqual(reloaded.game_gomoku.board, [])
        self.assertFalse(reloaded.game_gomoku.has_saved_game)



if __name__ == "__main__":
    unittest.main()
