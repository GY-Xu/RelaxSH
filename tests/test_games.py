from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from relaxsh.games import (
    Game2048Session,
    Game2048Snapshot,
    GameGomokuSession,
    choose_gomoku_ai_move,
    has_2048_moves,
    is_gomoku_winning_move,
    move_2048_board,
    start_2048_game,
    start_gomoku_game,
)


class DummyGameKeyReader:
    def __init__(self, keys: list[str]) -> None:
        self._keys = iter(keys)
        self.external_commands: list[list[str]] = []

    def __enter__(self) -> "DummyGameKeyReader":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read_key(self) -> str:
        return next(self._keys)

    def run_external(self, command: list[str]) -> None:
        self.external_commands.append(command)


class Game2048Tests(unittest.TestCase):
    def test_new_game_starts_with_two_tiles(self) -> None:
        snapshot = start_2048_game(random.Random(0))

        non_zero_tiles = [value for row in snapshot.board for value in row if value]
        self.assertEqual(len(non_zero_tiles), 2)
        self.assertTrue(all(value in {2, 4} for value in non_zero_tiles))

    def test_move_left_merges_once_per_pair(self) -> None:
        board = [
            [2, 2, 2, 2],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
            [0, 0, 0, 0],
        ]

        result = move_2048_board(board, "left", random.Random(0))

        self.assertEqual(result.board[0][:4], [4, 4, 0, 0])
        self.assertEqual(result.score_gain, 8)
        self.assertTrue(result.moved)

    def test_full_board_without_matches_has_no_moves(self) -> None:
        board = [
            [2, 4, 2, 4],
            [4, 2, 4, 2],
            [2, 4, 2, 4],
            [4, 2, 4, 2],
        ]

        self.assertFalse(has_2048_moves(board))

    def test_2048_session_accepts_arrow_keys(self) -> None:
        snapshot = Game2048Snapshot(
            board=[
                [2, 2, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ]
        )
        reader = DummyGameKeyReader(["left", "q"])

        with patch("relaxsh.games.KeyReader", return_value=reader), patch("relaxsh.games.render_screen"):
            exit_code = Game2048Session(snapshot, rng=random.Random(0)).run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(snapshot.score, 4)
        self.assertEqual(snapshot.max_tile, 4)
        self.assertEqual(sum(1 for row in snapshot.board for cell in row if cell), 2)


class GomokuTests(unittest.TestCase):
    def test_new_gomoku_game_starts_empty_with_center_cursor(self) -> None:
        snapshot = start_gomoku_game()

        self.assertEqual(snapshot.cursor_row, 5)
        self.assertEqual(snapshot.cursor_col, 5)
        self.assertEqual(snapshot.move_count, 0)
        self.assertTrue(all(cell == "" for row in snapshot.board for cell in row))

    def test_detects_horizontal_five_in_a_row(self) -> None:
        board = [["" for _ in range(11)] for _ in range(11)]
        for col_index in range(2, 7):
            board[4][col_index] = "X"

        self.assertTrue(is_gomoku_winning_move(board, 4, 4, "X"))

    def test_ai_takes_immediate_winning_move(self) -> None:
        board = [["" for _ in range(11)] for _ in range(11)]
        for col_index in range(3, 7):
            board[5][col_index] = "O"

        move = choose_gomoku_ai_move(board, random.Random(0))

        self.assertIn(move, {(5, 2), (5, 7)})

    def test_ai_blocks_human_immediate_winning_move(self) -> None:
        board = [["" for _ in range(11)] for _ in range(11)]
        for col_index in range(3, 7):
            board[5][col_index] = "X"

        move = choose_gomoku_ai_move(board, random.Random(0))

        self.assertIn(move, {(5, 2), (5, 7)})

    def test_gomoku_session_accepts_arrow_keys_and_space_to_place(self) -> None:
        snapshot = start_gomoku_game()
        reader = DummyGameKeyReader(["right", " ", "q"])

        with patch("relaxsh.games.KeyReader", return_value=reader), patch("relaxsh.games.render_screen"):
            exit_code = GameGomokuSession(snapshot, rng=random.Random(0)).run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(snapshot.board[5][6], "X")
        self.assertTrue(any(cell == "O" for row in snapshot.board for cell in row))


if __name__ == "__main__":
    unittest.main()
