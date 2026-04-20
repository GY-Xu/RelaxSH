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
    GameSnakeSession,
    GameSnakeSnapshot,
    choose_gomoku_ai_move,
    has_2048_moves,
    is_gomoku_winning_move,
    move_snake,
    move_2048_board,
    start_2048_game,
    start_gomoku_game,
    start_snake_game,
)


class DummyGameKeyReader:
    def __init__(self, keys: list[str]) -> None:
        self._keys = iter(keys)
        self.external_commands: list[list[str]] = []

    def __enter__(self) -> "DummyGameKeyReader":
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def read_key(self, timeout: float | None = None) -> str:
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

    def test_2048_render_uses_framed_layout(self) -> None:
        snapshot = Game2048Snapshot(
            board=[
                [2, 0, 0, 0],
                [0, 4, 0, 0],
                [0, 0, 8, 0],
                [0, 0, 0, 16],
            ],
            score=30,
            best_score=30,
        )

        rendered = Game2048Session(snapshot, rng=random.Random(0))._render()

        self.assertIn("╭", rendered)
        self.assertIn("┌", rendered)
        self.assertIn("·", rendered)
        self.assertIn("2 0 4 8", rendered)
        self.assertIn("Pulse", rendered)

    def test_2048_render_uses_colors_when_supported(self) -> None:
        snapshot = Game2048Snapshot(
            board=[
                [2, 4, 8, 16],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ]
        )

        with patch("relaxsh.games._supports_ansi_colors", return_value=True):
            rendered = Game2048Session(snapshot, rng=random.Random(0))._render()

        self.assertIn("\x1b[", rendered)

    def test_2048_render_shows_result_block_after_win(self) -> None:
        snapshot = Game2048Snapshot(
            board=[
                [2048, 64, 32, 16],
                [8, 4, 2, 0],
                [0, 0, 0, 0],
                [0, 0, 0, 0],
            ],
            score=4096,
            best_score=4096,
            won=True,
        )

        rendered = Game2048Session(snapshot, rng=random.Random(0))._render()

        self.assertIn("Result", rendered)
        self.assertIn("已经摸到 2048", rendered)
        self.assertIn("2048 达 成", rendered)


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

    def test_gomoku_render_uses_stone_symbols(self) -> None:
        snapshot = start_gomoku_game()
        snapshot.board[5][5] = "X"
        snapshot.board[5][6] = "O"
        snapshot.cursor_row = 5
        snapshot.cursor_col = 7

        rendered = GameGomokuSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("●", rendered)
        self.assertIn("○", rendered)
        self.assertIn("◎", rendered)
        self.assertIn("五 子 棋", rendered)
        self.assertIn("Focus", rendered)
        self.assertIn("木纹棋桌已经摆好", rendered)
        self.assertIn("╭", rendered)

    def test_gomoku_render_shows_star_points_and_winning_highlight(self) -> None:
        snapshot = start_gomoku_game()
        for col_index in range(2, 7):
            snapshot.board[5][col_index] = "X"
        snapshot.cursor_row = 0
        snapshot.cursor_col = 0

        rendered = GameGomokuSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("✦", rendered)
        self.assertIn("◆", rendered)

    def test_gomoku_render_uses_black_stone_color(self) -> None:
        snapshot = start_gomoku_game()
        snapshot.board[5][5] = "X"
        snapshot.cursor_row = 0
        snapshot.cursor_col = 0

        with patch("relaxsh.games._supports_ansi_colors", return_value=True):
            rendered = GameGomokuSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("\x1b[38;5;16;48;5;180m●\x1b[0m", rendered)

    def test_gomoku_cursor_black_stone_uses_board_background(self) -> None:
        snapshot = start_gomoku_game()
        snapshot.board[5][5] = "X"
        snapshot.cursor_row = 5
        snapshot.cursor_col = 5

        with patch("relaxsh.games._supports_ansi_colors", return_value=True):
            rendered = GameGomokuSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("\x1b[1;38;5;16;48;5;180m◆\x1b[0m", rendered)

    def test_gomoku_render_shows_result_block_after_win(self) -> None:
        snapshot = start_gomoku_game()
        for col_index in range(2, 7):
            snapshot.board[5][col_index] = "X"
        snapshot.winner = "human"
        snapshot.game_over = True

        rendered = GameGomokuSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("对 局 结 算", rendered)
        self.assertIn("Result", rendered)
        self.assertIn("你拿下了这一局", rendered)


class SnakeTests(unittest.TestCase):
    def test_new_snake_game_starts_with_food_off_body(self) -> None:
        snapshot = start_snake_game(random.Random(0))

        self.assertEqual(snapshot.length, 3)
        self.assertNotIn((snapshot.food_row, snapshot.food_col), snapshot.snake)
        self.assertNotIn((snapshot.food_row, snapshot.food_col), snapshot.rocks)
        self.assertEqual(snapshot.direction, "right")
        self.assertEqual(snapshot.speed, "normal")
        self.assertEqual(snapshot.difficulty, "normal")

    def test_hard_snake_game_starts_with_rocks(self) -> None:
        snapshot = start_snake_game(random.Random(0), difficulty="hard", speed="fast")

        self.assertEqual(snapshot.speed, "fast")
        self.assertEqual(snapshot.difficulty, "hard")
        self.assertEqual(len(snapshot.rocks), 8)
        self.assertTrue(all(rock not in snapshot.snake for rock in snapshot.rocks))
        self.assertNotIn((snapshot.food_row, snapshot.food_col), snapshot.rocks)

    def test_move_snake_grows_when_eating_food(self) -> None:
        snake = [(5, 5), (5, 4), (5, 3)]

        result = move_snake(snake, "right", (5, 6), rng=random.Random(0))

        self.assertTrue(result.ate_food)
        self.assertEqual(result.score_gain, 1)
        self.assertEqual(len(result.snake), 4)
        self.assertEqual(result.snake[0], (5, 6))
        self.assertIsNotNone(result.food)

    def test_move_snake_detects_wall_collision(self) -> None:
        snake = [(0, 0), (0, 1), (0, 2)]

        result = move_snake(snake, "left", (4, 4), rng=random.Random(0))

        self.assertTrue(result.game_over)

    def test_move_snake_detects_rock_collision(self) -> None:
        snake = [(5, 5), (5, 4), (5, 3)]

        result = move_snake(snake, "right", (2, 2), rocks=[(5, 6)], rng=random.Random(0))

        self.assertTrue(result.game_over)
        self.assertEqual(result.impact_cell, (5, 6))

    def test_snake_session_accepts_arrow_keys(self) -> None:
        snapshot = GameSnakeSnapshot(
            snake=[(5, 5), (5, 4), (5, 3)],
            rocks=[],
            food_row=5,
            food_col=6,
            direction="right",
            speed="normal",
            difficulty="normal",
        )
        reader = DummyGameKeyReader(["right", "q"])

        with patch("relaxsh.games.KeyReader", return_value=reader), patch("relaxsh.games.render_screen"):
            exit_code = GameSnakeSession(snapshot, rng=random.Random(0)).run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(snapshot.score, 1)
        self.assertEqual(snapshot.length, 4)
        self.assertEqual(snapshot.snake[0], (5, 6))
        self.assertEqual(snapshot.speed, "normal")
        self.assertEqual(snapshot.difficulty, "normal")

    def test_snake_render_shows_snake_and_food(self) -> None:
        snapshot = GameSnakeSnapshot(
            snake=[(5, 5), (5, 4), (5, 3)],
            rocks=[(1, 1), (8, 8)],
            food_row=2,
            food_col=2,
            direction="right",
            speed="fast",
            difficulty="hard",
            score=1,
            best_score=2,
        )

        rendered = GameSnakeSession(snapshot, rng=random.Random(0))._render()

        self.assertIn("●", rendered)
        self.assertIn("◆", rendered)
        self.assertIn("▣", rendered)
        self.assertIn("▶", rendered)
        self.assertIn("╔", rendered)

    def test_snake_start_render_uses_hero_banner_and_build_panel(self) -> None:
        session = GameSnakeSession(GameSnakeSnapshot(snake=[]), rng=random.Random(0))

        rendered = session._render_start()

        self.assertIn("贪 吃 蛇", rendered)
        self.assertIn("Build", rendered)
        self.assertIn("速度", rendered)

    def test_snake_render_marks_self_collision(self) -> None:
        snapshot = GameSnakeSnapshot(
            snake=[(5, 5), (5, 4), (6, 4), (6, 5), (6, 6), (5, 6)],
            food_row=2,
            food_col=2,
            direction="down",
        )
        session = GameSnakeSession(snapshot, rng=random.Random(0))

        session._step()
        rendered = session._render_summary()

        self.assertTrue(snapshot.game_over)
        self.assertIn("✕", rendered)
        self.assertIn("本 局 结 束", rendered)

    def test_snake_start_screen_cycles_speed_and_difficulty(self) -> None:
        snapshot = GameSnakeSnapshot(snake=[])
        reader = DummyGameKeyReader(["d", "s", " ", "q"])
        session = GameSnakeSession(snapshot, rng=random.Random(0))

        with patch("relaxsh.games.KeyReader", return_value=reader), patch("relaxsh.games.render_screen"):
            exit_code = session.run()

        self.assertEqual(exit_code, 0)
        self.assertEqual(session.snapshot.speed, "fast")
        self.assertEqual(session.snapshot.difficulty, "hard")


if __name__ == "__main__":
    unittest.main()
