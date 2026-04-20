"""Built-in terminal mini-games for RelaxSH."""

from __future__ import annotations

import random
import os
import re
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable

from relaxsh.display import clip_text, text_width, wrap_text
from relaxsh.i18n import tr
from relaxsh.reader import KeyReader, render_screen, resolve_boss_command


BOARD_SIZE = 4
TARGET_TILE = 2048
BOARD_CELL_MIN_WIDTH = 4
BOARD_CELL_MAX_WIDTH = 7
SNAKE_ROWS = 12
SNAKE_COLS = 18
SNAKE_SPEED_OPTIONS = ("slow", "normal", "fast")
SNAKE_SPEED_TICKS = {
    "slow": 0.22,
    "normal": 0.16,
    "fast": 0.11,
}
SNAKE_DIFFICULTY_OPTIONS = ("easy", "normal", "hard")
SNAKE_DIFFICULTY_ROCKS = {
    "easy": 0,
    "normal": 4,
    "hard": 8,
}
SNAKE_DIRECTION_DELTAS = {
    "up": (-1, 0),
    "down": (1, 0),
    "left": (0, -1),
    "right": (0, 1),
}
GOMOKU_BOARD_SIZE = 11
GOMOKU_WIN_LENGTH = 5
GOMOKU_HUMAN_STONE = "X"
GOMOKU_AI_STONE = "O"
GOMOKU_EMPTY = ""
GOMOKU_DIRECTIONS = ((0, 1), (1, 0), (1, 1), (1, -1))
GOMOKU_RENDER_STONES = {
    GOMOKU_EMPTY: "·",
    GOMOKU_HUMAN_STONE: "●",
    GOMOKU_AI_STONE: "○",
}
GOMOKU_STAR_POINTS = {
    (3, 3),
    (3, 7),
    (5, 5),
    (7, 3),
    (7, 7),
}
ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")
ANSI_RESET = "\x1b[0m"
TILE_COLORS = {
    0: (245, None, False),
    2: (238, 230, False),
    4: (238, 223, False),
    8: (231, 209, True),
    16: (231, 203, True),
    32: (231, 197, True),
    64: (231, 191, True),
    128: (232, 227, True),
    256: (232, 221, True),
    512: (232, 220, True),
    1024: (232, 214, True),
    2048: (232, 208, True),
}
GOMOKU_BOARD_BG = 180
GOMOKU_FRAME_BG = 137
GOMOKU_FRAME_FG = 94
GOMOKU_LABEL_FG = 230
GOMOKU_GRID_FG = 94
GOMOKU_STAR_FG = 130
GOMOKU_BLACK_STONE_FG = 16
GOMOKU_WHITE_STONE_FG = 255
GOMOKU_CURSOR_EMPTY_FG = 18
GOMOKU_CURSOR_BLACK_FG = 16
GOMOKU_CURSOR_WHITE_FG = 255
GOMOKU_WIN_BG = 220
GOMOKU_WIN_WHITE_FG = 52
SNAKE_BOARD_BG_LIGHT = 230
SNAKE_BOARD_BG_DARK = 223
SNAKE_BORDER_FG = 65
SNAKE_HEAD_BG = 34
SNAKE_HEAD_FG = 231
SNAKE_BODY_BG = 71
SNAKE_BODY_BG_TRAIL = (77, 71, 65, 29)
SNAKE_BODY_FG = 231
SNAKE_FOOD_BG = 160
SNAKE_FOOD_FG = 231
SNAKE_ROCK_BG = 240
SNAKE_ROCK_FG = 255
SNAKE_CRASH_BG = 196
SNAKE_CRASH_FG = 231


@dataclass
class Game2048Snapshot:
    """One serializable 2048 run state."""

    board: list[list[int]]
    score: int = 0
    best_score: int = 0
    won: bool = False
    game_over: bool = False

    @property
    def max_tile(self) -> int:
        if not self.board:
            return 0
        return max((max(row) for row in self.board), default=0)


@dataclass
class Move2048Result:
    """Outcome of one attempted move."""

    board: list[list[int]]
    score_gain: int
    moved: bool


@dataclass
class GameSnakeSnapshot:
    """One serializable Snake run state."""

    snake: list[tuple[int, int]]
    rocks: list[tuple[int, int]] = field(default_factory=list)
    food_row: int = 0
    food_col: int = 0
    direction: str = "right"
    speed: str = "normal"
    difficulty: str = "normal"
    score: int = 0
    best_score: int = 0
    game_over: bool = False

    @property
    def length(self) -> int:
        return len(self.snake)


@dataclass
class MoveSnakeResult:
    """Outcome of one snake tick."""

    snake: list[tuple[int, int]]
    food: tuple[int, int] | None
    score_gain: int
    ate_food: bool
    game_over: bool
    impact_cell: tuple[int, int] | None = None


@dataclass
class GameGomokuSnapshot:
    """One serializable Gomoku run state."""

    board: list[list[str]]
    cursor_row: int = GOMOKU_BOARD_SIZE // 2
    cursor_col: int = GOMOKU_BOARD_SIZE // 2
    winner: str = ""
    game_over: bool = False

    @property
    def move_count(self) -> int:
        if not self.board:
            return 0
        return sum(1 for row in self.board for cell in row if cell)


def clone_2048_board(board: list[list[int]]) -> list[list[int]]:
    """Deep-copy a 2048 board."""

    return [row[:] for row in board]


def clone_gomoku_board(board: list[list[str]]) -> list[list[str]]:
    """Deep-copy a Gomoku board."""

    return [row[:] for row in board]


def clone_snake_body(snake: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Deep-copy a Snake body path."""

    return [(row_index, col_index) for row_index, col_index in snake]


def _clone_snake_points(points: list[tuple[int, int]]) -> list[tuple[int, int]]:
    return [(row_index, col_index) for row_index, col_index in points]


def _empty_2048_board() -> list[list[int]]:
    return [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def _empty_gomoku_board() -> list[list[str]]:
    return [[GOMOKU_EMPTY for _ in range(GOMOKU_BOARD_SIZE)] for _ in range(GOMOKU_BOARD_SIZE)]


def _snake_in_bounds(row_index: int, col_index: int) -> bool:
    return 0 <= row_index < SNAKE_ROWS and 0 <= col_index < SNAKE_COLS


def _normalize_snake_speed(speed: str) -> str:
    return speed if speed in SNAKE_SPEED_OPTIONS else "normal"


def _normalize_snake_difficulty(difficulty: str) -> str:
    return difficulty if difficulty in SNAKE_DIFFICULTY_OPTIONS else "normal"


def _cycle_snake_option(options: tuple[str, ...], current: str, step: int) -> str:
    normalized_current = current if current in options else options[0]
    return options[(options.index(normalized_current) + step) % len(options)]


def _snake_starting_body() -> list[tuple[int, int]]:
    center_row = SNAKE_ROWS // 2
    center_col = SNAKE_COLS // 2
    return [
        (center_row, center_col + 1),
        (center_row, center_col),
        (center_row, center_col - 1),
    ]


def _snake_safe_zone() -> set[tuple[int, int]]:
    center_row = SNAKE_ROWS // 2
    center_col = SNAKE_COLS // 2
    return {
        (row_index, col_index)
        for row_index in range(max(0, center_row - 2), min(SNAKE_ROWS, center_row + 3))
        for col_index in range(max(0, center_col - 4), min(SNAKE_COLS, center_col + 5))
    }


def _spawn_snake_rocks(
    snake: list[tuple[int, int]],
    difficulty: str,
    rng: random.Random | None = None,
) -> list[tuple[int, int]]:
    rng = rng or random.Random()
    rock_count = SNAKE_DIFFICULTY_ROCKS[_normalize_snake_difficulty(difficulty)]
    if rock_count <= 0:
        return []

    blocked = set(snake) | _snake_safe_zone()
    candidates = [
        (row_index, col_index)
        for row_index in range(SNAKE_ROWS)
        for col_index in range(SNAKE_COLS)
        if (row_index, col_index) not in blocked
    ]
    if not candidates:
        return []
    rock_count = min(rock_count, len(candidates))
    return sorted(rng.sample(candidates, rock_count))


def _spawn_snake_food(
    snake: list[tuple[int, int]],
    rng: random.Random | None = None,
    rocks: list[tuple[int, int]] | None = None,
) -> tuple[int, int] | None:
    rng = rng or random.Random()
    occupied = set(snake)
    if rocks:
        occupied.update(rocks)
    candidates = [
        (row_index, col_index)
        for row_index in range(SNAKE_ROWS)
        for col_index in range(SNAKE_COLS)
        if (row_index, col_index) not in occupied
    ]
    if not candidates:
        return None
    return rng.choice(candidates)


def _empty_cells(board: list[list[int]]) -> list[tuple[int, int]]:
    cells: list[tuple[int, int]] = []
    for row_index, row in enumerate(board):
        for col_index, value in enumerate(row):
            if value == 0:
                cells.append((row_index, col_index))
    return cells


def spawn_2048_tile(board: list[list[int]], rng: random.Random | None = None) -> bool:
    """Spawn a random 2 or 4 tile into an empty position."""

    rng = rng or random.Random()
    empties = _empty_cells(board)
    if not empties:
        return False
    row_index, col_index = rng.choice(empties)
    board[row_index][col_index] = 4 if rng.random() < 0.1 else 2
    return True


def start_2048_game(rng: random.Random | None = None) -> Game2048Snapshot:
    """Create a fresh 2048 game with two opening tiles."""

    rng = rng or random.Random()
    board = _empty_2048_board()
    spawn_2048_tile(board, rng)
    spawn_2048_tile(board, rng)
    return Game2048Snapshot(board=board)


def start_gomoku_game() -> GameGomokuSnapshot:
    """Create a fresh Gomoku board with the cursor centered."""

    center = GOMOKU_BOARD_SIZE // 2
    return GameGomokuSnapshot(
        board=_empty_gomoku_board(),
        cursor_row=center,
        cursor_col=center,
    )


def start_snake_game(
    rng: random.Random | None = None,
    *,
    speed: str = "normal",
    difficulty: str = "normal",
) -> GameSnakeSnapshot:
    """Create a fresh Snake board with a centered opening body."""

    rng = rng or random.Random()
    snake = _snake_starting_body()
    normalized_speed = _normalize_snake_speed(speed)
    normalized_difficulty = _normalize_snake_difficulty(difficulty)
    rocks = _spawn_snake_rocks(snake, normalized_difficulty, rng)
    food = _spawn_snake_food(snake, rng, rocks) or (0, 0)
    return GameSnakeSnapshot(
        snake=snake,
        rocks=rocks,
        food_row=food[0],
        food_col=food[1],
        speed=normalized_speed,
        difficulty=normalized_difficulty,
    )


def _merge_2048_line(line: list[int]) -> tuple[list[int], int, bool]:
    """Merge one logical 2048 row to the left."""

    squeezed = [value for value in line if value]
    merged: list[int] = []
    score_gain = 0
    index = 0

    while index < len(squeezed):
        if index + 1 < len(squeezed) and squeezed[index] == squeezed[index + 1]:
            value = squeezed[index] * 2
            merged.append(value)
            score_gain += value
            index += 2
        else:
            merged.append(squeezed[index])
            index += 1

    merged.extend([0] * (BOARD_SIZE - len(merged)))
    return merged, score_gain, merged != line


def _transpose_2048(board: list[list[int]]) -> list[list[int]]:
    return [list(row) for row in zip(*board)]


def move_2048_board(
    board: list[list[int]],
    direction: str,
    rng: random.Random | None = None,
) -> Move2048Result:
    """Apply one 2048 move in the requested direction."""

    rng = rng or random.Random()
    if direction not in {"up", "down", "left", "right"}:
        raise ValueError(f"Unsupported 2048 direction: {direction}")

    working = clone_2048_board(board)
    if direction == "up":
        working = _transpose_2048(working)
    elif direction == "down":
        working = [list(reversed(row)) for row in _transpose_2048(working)]
    elif direction == "right":
        working = [list(reversed(row)) for row in working]

    moved = False
    score_gain = 0
    merged_rows: list[list[int]] = []
    for row in working:
        merged, row_score, row_moved = _merge_2048_line(row)
        merged_rows.append(merged)
        score_gain += row_score
        moved = moved or row_moved

    rebuilt = merged_rows
    if direction == "up":
        rebuilt = _transpose_2048(rebuilt)
    elif direction == "down":
        rebuilt = _transpose_2048([list(reversed(row)) for row in rebuilt])
    elif direction == "right":
        rebuilt = [list(reversed(row)) for row in rebuilt]

    if moved:
        spawn_2048_tile(rebuilt, rng)
    return Move2048Result(board=rebuilt, score_gain=score_gain, moved=moved)


def has_2048_moves(board: list[list[int]]) -> bool:
    """Return whether at least one legal move remains."""

    if _empty_cells(board):
        return True

    for row_index in range(BOARD_SIZE):
        for col_index in range(BOARD_SIZE):
            value = board[row_index][col_index]
            if row_index + 1 < BOARD_SIZE and board[row_index + 1][col_index] == value:
                return True
            if col_index + 1 < BOARD_SIZE and board[row_index][col_index + 1] == value:
                return True
    return False


def _next_snake_direction(current: str, requested: str) -> str:
    opposite = {
        "up": "down",
        "down": "up",
        "left": "right",
        "right": "left",
    }
    if requested not in SNAKE_DIRECTION_DELTAS:
        return current
    if len(current) and opposite[current] == requested:
        return current
    return requested


def move_snake(
    snake: list[tuple[int, int]],
    direction: str,
    food: tuple[int, int],
    rocks: list[tuple[int, int]] | None = None,
    rng: random.Random | None = None,
) -> MoveSnakeResult:
    """Advance the snake one tick and report the outcome."""

    rng = rng or random.Random()
    if not snake:
        return MoveSnakeResult(
            snake=[],
            food=food,
            score_gain=0,
            ate_food=False,
            game_over=True,
            impact_cell=None,
        )

    row_delta, col_delta = SNAKE_DIRECTION_DELTAS[direction]
    rock_positions = set(rocks or [])
    head_row, head_col = snake[0]
    next_head = (head_row + row_delta, head_col + col_delta)
    if not _snake_in_bounds(*next_head):
        return MoveSnakeResult(
            snake=clone_snake_body(snake),
            food=food,
            score_gain=0,
            ate_food=False,
            game_over=True,
            impact_cell=next_head,
        )

    will_eat = next_head == food
    if next_head in rock_positions:
        return MoveSnakeResult(
            snake=clone_snake_body(snake),
            food=food,
            score_gain=0,
            ate_food=False,
            game_over=True,
            impact_cell=next_head,
        )
    occupied = set(snake if will_eat else snake[:-1])
    if next_head in occupied:
        return MoveSnakeResult(
            snake=clone_snake_body(snake),
            food=food,
            score_gain=0,
            ate_food=False,
            game_over=True,
            impact_cell=next_head,
        )

    next_snake = [next_head, *snake]
    next_food = food
    score_gain = 0
    if will_eat:
        score_gain = 1
        next_food = _spawn_snake_food(next_snake, rng, rocks)
    else:
        next_snake.pop()

    game_over = next_food is None
    return MoveSnakeResult(
        snake=next_snake,
        food=next_food,
        score_gain=score_gain,
        ate_food=will_eat,
        game_over=game_over,
        impact_cell=None,
    )


def _gomoku_in_bounds(row_index: int, col_index: int) -> bool:
    return 0 <= row_index < GOMOKU_BOARD_SIZE and 0 <= col_index < GOMOKU_BOARD_SIZE


def _count_gomoku_direction(
    board: list[list[str]],
    row_index: int,
    col_index: int,
    row_step: int,
    col_step: int,
    stone: str,
) -> int:
    total = 0
    next_row = row_index + row_step
    next_col = col_index + col_step
    while _gomoku_in_bounds(next_row, next_col) and board[next_row][next_col] == stone:
        total += 1
        next_row += row_step
        next_col += col_step
    return total


def is_gomoku_winning_move(
    board: list[list[str]],
    row_index: int,
    col_index: int,
    stone: str,
) -> bool:
    """Return whether the placed stone creates five in a row."""

    if not _gomoku_in_bounds(row_index, col_index):
        return False
    if board[row_index][col_index] != stone:
        return False

    for row_step, col_step in GOMOKU_DIRECTIONS:
        total = 1
        total += _count_gomoku_direction(board, row_index, col_index, row_step, col_step, stone)
        total += _count_gomoku_direction(board, row_index, col_index, -row_step, -col_step, stone)
        if total >= GOMOKU_WIN_LENGTH:
            return True
    return False


def gomoku_winner(board: list[list[str]]) -> str:
    """Return the stone that has already connected five, if any."""

    for row_index in range(GOMOKU_BOARD_SIZE):
        for col_index in range(GOMOKU_BOARD_SIZE):
            stone = board[row_index][col_index]
            if stone and is_gomoku_winning_move(board, row_index, col_index, stone):
                return stone
    return ""


def gomoku_board_full(board: list[list[str]]) -> bool:
    """Return whether no empty Gomoku cell remains."""

    return all(cell for row in board for cell in row)


def _gomoku_candidate_moves(board: list[list[str]]) -> list[tuple[int, int]]:
    """Collect empty cells near existing stones to keep AI search fast."""

    occupied: list[tuple[int, int]] = []
    for row_index, row in enumerate(board):
        for col_index, cell in enumerate(row):
            if cell:
                occupied.append((row_index, col_index))

    if not occupied:
        center = GOMOKU_BOARD_SIZE // 2
        return [(center, center)]

    candidates: set[tuple[int, int]] = set()
    for row_index, col_index in occupied:
        for row_delta in range(-2, 3):
            for col_delta in range(-2, 3):
                next_row = row_index + row_delta
                next_col = col_index + col_delta
                if not _gomoku_in_bounds(next_row, next_col):
                    continue
                if board[next_row][next_col] != GOMOKU_EMPTY:
                    continue
                candidates.add((next_row, next_col))

    return sorted(candidates)


def _find_gomoku_immediate_move(board: list[list[str]], stone: str) -> tuple[int, int] | None:
    for row_index, col_index in _gomoku_candidate_moves(board):
        board[row_index][col_index] = stone
        try:
            if is_gomoku_winning_move(board, row_index, col_index, stone):
                return row_index, col_index
        finally:
            board[row_index][col_index] = GOMOKU_EMPTY
    return None


def _gomoku_pattern_score(length: int, open_ends: int) -> int:
    if length >= 5:
        return 200_000
    if length == 4 and open_ends == 2:
        return 20_000
    if length == 4 and open_ends == 1:
        return 7_000
    if length == 3 and open_ends == 2:
        return 2_500
    if length == 3 and open_ends == 1:
        return 350
    if length == 2 and open_ends == 2:
        return 120
    if length == 2 and open_ends == 1:
        return 20
    if length == 1 and open_ends == 2:
        return 8
    if length == 1 and open_ends == 1:
        return 2
    return 0


def _score_gomoku_move(
    board: list[list[str]],
    row_index: int,
    col_index: int,
    stone: str,
) -> int:
    if board[row_index][col_index] != GOMOKU_EMPTY:
        return -1

    board[row_index][col_index] = stone
    try:
        total = 0
        for row_step, col_step in GOMOKU_DIRECTIONS:
            length = 1
            open_ends = 0
            for direction in (-1, 1):
                next_row = row_index + row_step * direction
                next_col = col_index + col_step * direction
                while _gomoku_in_bounds(next_row, next_col) and board[next_row][next_col] == stone:
                    length += 1
                    next_row += row_step * direction
                    next_col += col_step * direction
                if _gomoku_in_bounds(next_row, next_col) and board[next_row][next_col] == GOMOKU_EMPTY:
                    open_ends += 1
            total += _gomoku_pattern_score(length, open_ends)

        neighbor_bonus = 0
        for row_delta in (-1, 0, 1):
            for col_delta in (-1, 0, 1):
                if row_delta == 0 and col_delta == 0:
                    continue
                next_row = row_index + row_delta
                next_col = col_index + col_delta
                if _gomoku_in_bounds(next_row, next_col) and board[next_row][next_col] != GOMOKU_EMPTY:
                    neighbor_bonus += 4
        center = GOMOKU_BOARD_SIZE // 2
        center_bonus = max(0, 12 - (abs(row_index - center) + abs(col_index - center)))
        return total + neighbor_bonus + center_bonus
    finally:
        board[row_index][col_index] = GOMOKU_EMPTY


def choose_gomoku_ai_move(
    board: list[list[str]],
    rng: random.Random | None = None,
) -> tuple[int, int] | None:
    """Pick an AI move with light tactical search and heuristic scoring."""

    rng = rng or random.Random()
    immediate_win = _find_gomoku_immediate_move(board, GOMOKU_AI_STONE)
    if immediate_win is not None:
        return immediate_win

    immediate_block = _find_gomoku_immediate_move(board, GOMOKU_HUMAN_STONE)
    if immediate_block is not None:
        return immediate_block

    candidates = _gomoku_candidate_moves(board)
    if not candidates:
        return None

    ranked: list[tuple[int, int, int, int]] = []
    center = GOMOKU_BOARD_SIZE // 2
    for row_index, col_index in candidates:
        attack_score = _score_gomoku_move(board, row_index, col_index, GOMOKU_AI_STONE)
        defense_score = _score_gomoku_move(board, row_index, col_index, GOMOKU_HUMAN_STONE)
        distance = abs(row_index - center) + abs(col_index - center)
        total_score = attack_score * 3 + defense_score * 2
        ranked.append((total_score, -distance, -row_index, -col_index))

    best_score = max(score for score, _, _, _ in ranked)
    best_moves = [
        (row_index, col_index)
        for (score, _distance, _neg_row, _neg_col), (row_index, col_index) in zip(ranked, candidates)
        if score == best_score
    ]
    best_moves.sort(
        key=lambda move: (
            abs(move[0] - center) + abs(move[1] - center),
            move[0],
            move[1],
        )
    )
    if len(best_moves) == 1:
        return best_moves[0]
    return rng.choice(best_moves[: min(3, len(best_moves))])


def _game_width() -> int:
    terminal_width = shutil.get_terminal_size((88, 28)).columns
    return max(32, min(88, terminal_width - 4))


def _supports_ansi_colors() -> bool:
    return sys.stdout.isatty() and os.environ.get("NO_COLOR") is None


def _strip_ansi(text: str) -> str:
    return ANSI_ESCAPE_RE.sub("", text)


def _visible_text_width(text: str) -> int:
    return text_width(_strip_ansi(text))


def _colorize(text: str, *, fg: int | None = None, bg: int | None = None, bold: bool = False) -> str:
    if not _supports_ansi_colors():
        return text

    codes: list[str] = []
    if bold:
        codes.append("1")
    if fg is not None:
        codes.append(f"38;5;{fg}")
    if bg is not None:
        codes.append(f"48;5;{bg}")
    if not codes:
        return text
    return f"\x1b[{';'.join(codes)}m{text}{ANSI_RESET}"


def _pad_visible_text(text: str, width: int) -> str:
    return text + (" " * max(0, width - _visible_text_width(text)))


def _center_line(line: str, width: int) -> str:
    visible_width = _visible_text_width(line)
    if visible_width >= width:
        return clip_text(_strip_ansi(line), width)
    padding = max(0, (width - visible_width) // 2)
    return (" " * padding) + line


def _frame_block(lines: list[str], width: int, *, title: str = "") -> list[str]:
    inner_width = max(12, width - 2)
    top = "╭" + ("─" * inner_width) + "╮"
    if title:
        clipped_title = clip_text(f" {title} ", max(0, inner_width - 2))
        title_width = text_width(clipped_title)
        left_width = max(0, (inner_width - title_width) // 2)
        right_width = max(0, inner_width - title_width - left_width)
        top = f"╭{'─' * left_width}{clipped_title}{'─' * right_width}╮"

    framed = [top]
    for line in lines:
        framed.append(f"│{_pad_visible_text(line, inner_width)}│")
    framed.append("╰" + ("─" * inner_width) + "╯")
    return framed


def _pill_text(label: str, *, fg: int = 231, bg: int = 65, bold: bool = True) -> str:
    return _colorize(f" {label} ", fg=fg, bg=bg, bold=bold)


def _hero_banner(width: int, title: str, subtitle: str, *, border_fg: int = 71, fill_bg: int = 65) -> list[str]:
    banner_width = min(max(26, text_width(title) + 8), max(26, width - 12))
    top = _colorize("╭" + ("═" * (banner_width - 2)) + "╮", fg=border_fg, bold=True)
    middle = _colorize(f"│{title.center(banner_width - 2)}│", fg=231, bg=fill_bg, bold=True)
    bottom = _colorize("╰" + ("═" * (banner_width - 2)) + "╯", fg=border_fg, bold=True)
    return [
        _center_line(top, width),
        _center_line(middle, width),
        _center_line(bottom, width),
        _center_line(_colorize(subtitle, fg=244), width),
    ]


def _sparkline(width: int, token: str, *, fg: int, bg: int | None = None) -> str:
    repeated = (f"{token} " * max(1, width // max(2, text_width(token) + 1))).strip()
    line = clip_text(repeated, max(8, width - 2))
    return _center_line(_colorize(line, fg=fg, bg=bg, bold=True), width)


def _board_cell_width(content_width: int) -> int:
    available = max(BOARD_SIZE * (BOARD_CELL_MIN_WIDTH + 1) + BOARD_SIZE + 1, min(content_width, 48))
    return max(
        BOARD_CELL_MIN_WIDTH + 1,
        min(BOARD_CELL_MAX_WIDTH + 1, (available - (BOARD_SIZE + 1)) // BOARD_SIZE),
    )


def _board_lines(board: list[list[int]], width: int) -> list[str]:
    cell_width = _board_cell_width(width)
    top_border = "┌" + "┬".join("─" * cell_width for _ in range(BOARD_SIZE)) + "┐"
    middle_border = "├" + "┼".join("─" * cell_width for _ in range(BOARD_SIZE)) + "┤"
    bottom_border = "└" + "┴".join("─" * cell_width for _ in range(BOARD_SIZE)) + "┘"
    lines = [top_border]
    for row_index, row in enumerate(board):
        cells = [_render_2048_cell(value, cell_width) for value in row]
        lines.append("│" + "│".join(cells) + "│")
        lines.append(bottom_border if row_index == BOARD_SIZE - 1 else middle_border)
    return [_center_line(line, width) for line in lines]


def _render_2048_cell(value: int, cell_width: int) -> str:
    label = "·" if value == 0 else str(value)
    content = label.center(cell_width)
    fg, bg, bold = TILE_COLORS.get(
        value,
        (231, 202, True) if value else TILE_COLORS[0],
    )
    if value == 0:
        return _colorize(content, fg=fg)
    return _colorize(content, fg=fg, bg=bg, bold=bold)


def _snake_cell_background(row_index: int, col_index: int) -> int:
    return SNAKE_BOARD_BG_LIGHT if (row_index + col_index) % 2 == 0 else SNAKE_BOARD_BG_DARK


def _snake_head_glyph(direction: str) -> str:
    return {
        "up": "▲",
        "down": "▼",
        "left": "◀",
        "right": "▶",
    }.get(direction, "●")


def _snake_body_bg(segment_index: int) -> int:
    if segment_index <= 0:
        return SNAKE_HEAD_BG
    return SNAKE_BODY_BG_TRAIL[min(segment_index - 1, len(SNAKE_BODY_BG_TRAIL) - 1)]


def _render_snake_cell(
    row_index: int,
    col_index: int,
    snake_positions: dict[tuple[int, int], int],
    rocks: set[tuple[int, int]],
    food: tuple[int, int],
    direction: str,
    impact_cell: tuple[int, int] | None = None,
) -> str:
    position = (row_index, col_index)
    background = _snake_cell_background(row_index, col_index)
    if impact_cell == position:
        return _colorize("✕ ", fg=SNAKE_CRASH_FG, bg=SNAKE_CRASH_BG, bold=True)
    segment_index = snake_positions.get(position)
    if segment_index == 0:
        return _colorize(
            f"{_snake_head_glyph(direction)} ",
            fg=SNAKE_HEAD_FG,
            bg=SNAKE_HEAD_BG,
            bold=True,
        )
    if segment_index is not None:
        glyph = "●" if segment_index < 3 else "◉" if segment_index == len(snake_positions) - 1 else "●"
        return _colorize(
            f"{glyph} ",
            fg=SNAKE_BODY_FG,
            bg=_snake_body_bg(segment_index),
            bold=segment_index < 4,
        )
    if position in rocks:
        return _colorize("▣ ", fg=SNAKE_ROCK_FG, bg=SNAKE_ROCK_BG, bold=True)
    if position == food:
        return _colorize("◆ ", fg=SNAKE_FOOD_FG, bg=SNAKE_FOOD_BG, bold=True)
    if _supports_ansi_colors():
        return _colorize("  ", bg=background)
    return "· "


def _snake_board_lines(
    snake: list[tuple[int, int]],
    rocks: list[tuple[int, int]],
    food: tuple[int, int],
    width: int,
    *,
    direction: str,
    impact_cell: tuple[int, int] | None = None,
) -> list[str]:
    top_border = _colorize("╔" + ("══" * SNAKE_COLS) + "╗", fg=SNAKE_BORDER_FG, bold=True)
    bottom_border = _colorize("╚" + ("══" * SNAKE_COLS) + "╝", fg=SNAKE_BORDER_FG, bold=True)
    side_wall = _colorize("║", fg=SNAKE_BORDER_FG, bold=True)
    snake_positions = {position: index for index, position in enumerate(snake)}
    rock_positions = set(rocks)
    lines = [top_border]
    for row_index in range(SNAKE_ROWS):
        cells = [
            _render_snake_cell(
                row_index,
                col_index,
                snake_positions,
                rock_positions,
                food,
                direction,
                impact_cell,
            )
            for col_index in range(SNAKE_COLS)
        ]
        lines.append(f"{side_wall}{''.join(cells)}{side_wall}")
    lines.append(bottom_border)
    return [_center_line(line, width) for line in lines]


def _gomoku_winning_cells(board: list[list[str]]) -> set[tuple[int, int]]:
    for row_index in range(GOMOKU_BOARD_SIZE):
        for col_index in range(GOMOKU_BOARD_SIZE):
            stone = board[row_index][col_index]
            if not stone:
                continue
            for row_step, col_step in GOMOKU_DIRECTIONS:
                prev_row = row_index - row_step
                prev_col = col_index - col_step
                if _gomoku_in_bounds(prev_row, prev_col) and board[prev_row][prev_col] == stone:
                    continue
                line_cells: list[tuple[int, int]] = []
                next_row = row_index
                next_col = col_index
                while _gomoku_in_bounds(next_row, next_col) and board[next_row][next_col] == stone:
                    line_cells.append((next_row, next_col))
                    next_row += row_step
                    next_col += col_step
                if len(line_cells) >= GOMOKU_WIN_LENGTH:
                    return set(line_cells)
    return set()


def _gomoku_axis_labels(*, compact: bool) -> str:
    labels = [chr(ord("A") + index) for index in range(GOMOKU_BOARD_SIZE)]
    if compact:
        return "   " + " ".join(labels)
    return "   " + " ".join(labels)


def _gomoku_cell_text(
    board: list[list[str]],
    row_index: int,
    col_index: int,
    *,
    cursor_row: int,
    cursor_col: int,
    winning_cells: set[tuple[int, int]],
    compact: bool,
) -> str:
    position = (row_index, col_index)
    raw_value = board[row_index][col_index]
    stone = GOMOKU_RENDER_STONES[raw_value]
    if raw_value == GOMOKU_EMPTY:
        stone = "✦" if position in GOMOKU_STAR_POINTS else "┼"
    elif position in winning_cells:
        stone = "◆" if raw_value == GOMOKU_HUMAN_STONE else "◇"
    if row_index == cursor_row and col_index == cursor_col:
        if raw_value == GOMOKU_EMPTY:
            return _colorize("◎", fg=GOMOKU_CURSOR_EMPTY_FG, bg=GOMOKU_BOARD_BG, bold=True)
        if raw_value == GOMOKU_HUMAN_STONE:
            return _colorize("◆", fg=GOMOKU_CURSOR_BLACK_FG, bg=GOMOKU_BOARD_BG, bold=True)
        return _colorize("◇", fg=GOMOKU_CURSOR_WHITE_FG, bg=GOMOKU_BOARD_BG, bold=True)
    if raw_value == GOMOKU_HUMAN_STONE:
        return _colorize(
            stone,
            fg=GOMOKU_BLACK_STONE_FG,
            bg=GOMOKU_WIN_BG if position in winning_cells else GOMOKU_BOARD_BG,
            bold=position in winning_cells,
        )
    if raw_value == GOMOKU_AI_STONE:
        return _colorize(
            stone,
            fg=GOMOKU_WIN_WHITE_FG if position in winning_cells else GOMOKU_WHITE_STONE_FG,
            bg=88 if position in winning_cells else GOMOKU_BOARD_BG,
            bold=True,
        )
    if position in GOMOKU_STAR_POINTS:
        return _colorize(stone, fg=GOMOKU_STAR_FG, bg=GOMOKU_BOARD_BG, bold=True)
    return _colorize(stone, fg=GOMOKU_GRID_FG if compact else 243, bg=GOMOKU_BOARD_BG)


def _gomoku_board_lines(
    board: list[list[str]],
    *,
    cursor_row: int,
    cursor_col: int,
    width: int,
) -> list[str]:
    compact = width < 40
    winning_cells = _gomoku_winning_cells(board)
    axis_labels = _gomoku_axis_labels(compact=compact)
    board_width = text_width(axis_labels)
    top_lip = _colorize("╭" + ("─" * (board_width + 2)) + "╮", fg=GOMOKU_FRAME_FG, bg=GOMOKU_FRAME_BG, bold=True)
    top_axis = _colorize(f"│ {axis_labels} │", fg=GOMOKU_LABEL_FG, bg=GOMOKU_FRAME_BG, bold=True)
    lines = [top_lip, top_axis]
    for row_index in range(GOMOKU_BOARD_SIZE):
        cells = [
            _gomoku_cell_text(
                board,
                row_index,
                col_index,
                cursor_row=cursor_row,
                cursor_col=cursor_col,
                winning_cells=winning_cells,
                compact=compact,
            )
            for col_index in range(GOMOKU_BOARD_SIZE)
        ]
        body = " ".join(cells)
        row_text = f"{row_index + 1:>2} {body}"
        row_label = _colorize(f"│ ", fg=GOMOKU_FRAME_FG, bg=GOMOKU_FRAME_BG, bold=True)
        row_tail = _colorize(" │", fg=GOMOKU_FRAME_FG, bg=GOMOKU_FRAME_BG, bold=True)
        lines.append(f"{row_label}{_pad_visible_text(row_text, board_width)}{row_tail}")
    bottom_axis = _colorize(f"│ {axis_labels} │", fg=GOMOKU_LABEL_FG, bg=GOMOKU_FRAME_BG, bold=True)
    bottom_lip = _colorize("╰" + ("─" * (board_width + 2)) + "╯", fg=GOMOKU_FRAME_FG, bg=GOMOKU_FRAME_BG, bold=True)
    lines = [line for line in lines if line]
    lines.extend([bottom_axis, bottom_lip])
    return [_center_line(line, width) for line in lines]


def _fit_lines(text: str, width: int) -> list[str]:
    return [clip_text(line, width) for line in wrap_text(text, width) or [""]]


def _format_boss_dashboard(width: int, height: int, language: str, status_message: str = "") -> str:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    header = clip_text(tr(language, "reader_boss_header", timestamp=timestamp), width)
    border = "=" * width
    body_lines = [
        clip_text(tr(language, f"reader_boss_line_{index}"), width)
        for index in range(1, 11)
    ]
    visible_body = body_lines[: max(3, height - 5)]
    footer = clip_text(tr(language, "reader_boss_footer"), width)
    sections = [border, header, border, *visible_body, border, footer]
    if status_message:
        sections.append(clip_text(status_message, width))
    return "\n".join(sections)


class Game2048Session:
    """Interactive 2048 runtime."""

    def __init__(
        self,
        snapshot: Game2048Snapshot,
        *,
        ui_language: str = "zh",
        rng: random.Random | None = None,
        state_callback: Callable[[Game2048Snapshot], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.ui_language = ui_language
        self.rng = rng or random.Random()
        self.state_callback = state_callback

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.ui_language, key, **kwargs)

    def _persist(self) -> None:
        if self.state_callback is None:
            return
        self.state_callback(
            Game2048Snapshot(
                board=clone_2048_board(self.snapshot.board),
                score=self.snapshot.score,
                best_score=self.snapshot.best_score,
                won=self.snapshot.won,
                game_over=self.snapshot.game_over,
            )
        )

    def _start_new_game(self) -> None:
        fresh = start_2048_game(self.rng)
        fresh.best_score = self.snapshot.best_score
        self.snapshot = fresh
        self._persist()

    def _hero_lines(self, width: int) -> list[str]:
        return _hero_banner(
            width,
            self._t("game_2048_banner"),
            self._t("game_2048_tagline"),
            border_fg=173,
            fill_bg=130,
        )

    def _progress_rank(self) -> str:
        if self.snapshot.max_tile >= 2048:
            return "S"
        if self.snapshot.max_tile >= 1024:
            return "A"
        if self.snapshot.max_tile >= 512:
            return "B"
        if self.snapshot.max_tile >= 256:
            return "C"
        return "D"

    def _insight_lines(self, width: int) -> list[str]:
        empty_tiles = sum(1 for row in self.snapshot.board for value in row if value == 0)
        return [
            f"{_pill_text(self._t('game_2048_chip_rank'), bg=130)} {self._progress_rank()}",
            clip_text(
                self._t(
                    "game_2048_stats_line_1",
                    score=self.snapshot.score,
                    best=self.snapshot.best_score,
                    tile=self.snapshot.max_tile,
                ),
                width - 4,
            ),
            clip_text(
                self._t(
                    "game_2048_stats_line_2",
                    empty=empty_tiles,
                    target=max(self.snapshot.max_tile * 2, 2048),
                ),
                width - 4,
            ),
        ]

    def _result_lines(self, width: int) -> list[str]:
        if self.snapshot.game_over:
            title_key = "game_2048_summary_title_over"
            flavor_key = "game_2048_summary_flavor_over"
        else:
            title_key = "game_2048_summary_title_win"
            flavor_key = "game_2048_summary_flavor_win"
        return [
            f"{_pill_text(self._t('game_2048_chip_result'), bg=173)} {self._progress_rank()}",
            clip_text(self._t(title_key), width - 4),
            clip_text(self._t(flavor_key), width - 4),
        ]

    def _celebration_lines(self, width: int) -> list[str]:
        if self.snapshot.game_over:
            return [
                _sparkline(width, "◇", fg=173),
                _center_line(_colorize(self._t("game_2048_lock_banner"), fg=130, bold=True), width),
            ]
        return [
            _sparkline(width, "✦", fg=221),
            _center_line(_colorize(self._t("game_2048_win_banner"), fg=220, bold=True), width),
            _sparkline(width, "◆", fg=214),
        ]

    def _render(self, status_message: str = "") -> str:
        width = _game_width()
        title = clip_text(
            self._t(
                "game_2048_header",
                score=self.snapshot.score,
                best=self.snapshot.best_score,
                tile=self.snapshot.max_tile,
            ),
            width - 4,
        )
        subtitle = clip_text(self._t("game_2048_subtitle"), width - 4)
        controls = _fit_lines(self._t("game_2048_controls"), width - 4)
        sections = [
            *self._hero_lines(width),
            *_frame_block([title, subtitle], width, title=" 2048 "),
            *_frame_block(self._insight_lines(width), width, title=" Pulse "),
            *(self._celebration_lines(width) if self.snapshot.won or self.snapshot.game_over else []),
            *_board_lines(self.snapshot.board, width),
            *_frame_block(controls, width, title=" Controls "),
        ]
        if self.snapshot.won or self.snapshot.game_over:
            sections.extend(_frame_block(self._result_lines(width), width, title=" Result "))
        if status_message:
            sections.extend(_frame_block(_fit_lines(status_message, width - 4), width, title=" Status "))
        return "\n".join(sections)

    def _trigger_boss_key(self, input_reader: KeyReader) -> tuple[bool, str]:
        resolved = resolve_boss_command()
        if resolved is None:
            return False, ""

        command, label = resolved
        try:
            input_reader.run_external(command)
        except OSError:
            return False, ""
        return True, self._t("reader_boss_returned", app=label)

    def run(self) -> int:
        """Run the 2048 interaction loop."""

        if not self.snapshot.board:
            self._start_new_game()
        else:
            self.snapshot.best_score = max(self.snapshot.best_score, self.snapshot.score)
            self._persist()

        boss_mode = False
        status_message = ""

        with KeyReader() as input_reader:
            while True:
                terminal_height = shutil.get_terminal_size((88, 28)).lines
                screen = (
                    _format_boss_dashboard(_game_width(), terminal_height, self.ui_language, status_message)
                    if boss_mode
                    else self._render(status_message)
                )
                render_screen(screen)
                status_message = ""

                command = input_reader.read_key()
                if boss_mode:
                    if command in {"b", "escape", "q", "Q"}:
                        boss_mode = False
                    continue

                if command in {"q", "Q", "escape"}:
                    self._persist()
                    return 0

                if command in {"r", "R", "n", "N"}:
                    self._start_new_game()
                    status_message = self._t("game_2048_new_game")
                    continue

                if command == "b":
                    launched, boss_status = self._trigger_boss_key(input_reader)
                    if launched:
                        status_message = boss_status
                    else:
                        boss_mode = True
                    continue

                direction = {
                    "w": "up",
                    "W": "up",
                    "s": "down",
                    "S": "down",
                    "a": "left",
                    "A": "left",
                    "d": "right",
                    "D": "right",
                    "up": "up",
                    "down": "down",
                    "left": "left",
                    "right": "right",
                }.get(command)

                if direction is None:
                    status_message = self._t("game_2048_unknown_command")
                    continue

                if self.snapshot.game_over:
                    status_message = self._t("game_2048_over")
                    continue

                move = move_2048_board(self.snapshot.board, direction, self.rng)
                if not move.moved:
                    status_message = self._t("game_2048_move_blocked")
                    continue

                self.snapshot.board = move.board
                self.snapshot.score += move.score_gain
                self.snapshot.best_score = max(self.snapshot.best_score, self.snapshot.score)

                if not self.snapshot.won and self.snapshot.max_tile >= TARGET_TILE:
                    self.snapshot.won = True
                    status_message = self._t("game_2048_win")

                self.snapshot.game_over = not has_2048_moves(self.snapshot.board)
                if self.snapshot.game_over:
                    status_message = self._t("game_2048_over")

                self._persist()


class GameSnakeSession:
    """Interactive Snake runtime with timed movement."""

    def __init__(
        self,
        snapshot: GameSnakeSnapshot,
        *,
        ui_language: str = "zh",
        rng: random.Random | None = None,
        state_callback: Callable[[GameSnakeSnapshot], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.ui_language = ui_language
        self.rng = rng or random.Random()
        self.state_callback = state_callback
        self.paused = False
        self.last_impact_cell: tuple[int, int] | None = None
        self.last_win = False
        self.screen = "play" if snapshot.snake and not snapshot.game_over else "start"
        self.selected_speed = _normalize_snake_speed(snapshot.speed)
        self.selected_difficulty = _normalize_snake_difficulty(snapshot.difficulty)

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.ui_language, key, **kwargs)

    def _persist(self) -> None:
        if self.state_callback is None:
            return
        self.state_callback(
            GameSnakeSnapshot(
                snake=clone_snake_body(self.snapshot.snake),
                rocks=_clone_snake_points(self.snapshot.rocks),
                food_row=self.snapshot.food_row,
                food_col=self.snapshot.food_col,
                direction=self.snapshot.direction,
                speed=self.snapshot.speed,
                difficulty=self.snapshot.difficulty,
                score=self.snapshot.score,
                best_score=self.snapshot.best_score,
                game_over=self.snapshot.game_over,
            )
        )

    def _start_new_game(self) -> None:
        fresh = start_snake_game(
            self.rng,
            speed=self.selected_speed,
            difficulty=self.selected_difficulty,
        )
        fresh.best_score = self.snapshot.best_score
        self.snapshot = fresh
        self.paused = False
        self.last_impact_cell = None
        self.last_win = False
        self.screen = "play"
        self._persist()

    def _tick_seconds(self) -> float:
        return SNAKE_SPEED_TICKS[_normalize_snake_speed(self.snapshot.speed)]

    def _speed_label(self, speed: str | None = None) -> str:
        return self._t(f"game_snake_speed_{_normalize_snake_speed(speed or self.snapshot.speed)}")

    def _difficulty_label(self, difficulty: str | None = None) -> str:
        return self._t(f"game_snake_difficulty_{_normalize_snake_difficulty(difficulty or self.snapshot.difficulty)}")

    def _difficulty_rocks(self, difficulty: str | None = None) -> int:
        return SNAKE_DIFFICULTY_ROCKS[_normalize_snake_difficulty(difficulty or self.snapshot.difficulty)]

    def _preview_snapshot(self) -> GameSnakeSnapshot:
        preview_rng = random.Random(0)
        return start_snake_game(
            preview_rng,
            speed=self.selected_speed,
            difficulty=self.selected_difficulty,
        )

    def _hero_banner_lines(self, width: int, *, summary: bool = False) -> list[str]:
        title_key = (
            "game_snake_summary_banner_win"
            if summary and self.last_win
            else "game_snake_summary_banner_over"
            if summary
            else "game_snake_start_banner"
        )
        subtitle_key = (
            "game_snake_summary_flavor_win"
            if summary and self.last_win
            else "game_snake_summary_flavor_over"
            if summary
            else "game_snake_start_tagline"
        )
        title = self._t(title_key)
        subtitle = self._t(subtitle_key)
        banner_width = min(max(26, text_width(title) + 8), max(26, width - 12))
        top = _colorize("╭" + ("═" * (banner_width - 2)) + "╮", fg=71, bold=True)
        middle = _colorize(f"│{title.center(banner_width - 2)}│", fg=231, bg=65, bold=True)
        bottom = _colorize("╰" + ("═" * (banner_width - 2)) + "╯", fg=71, bold=True)
        return [
            _center_line(top, width),
            _center_line(middle, width),
            _center_line(bottom, width),
            _center_line(_colorize(subtitle, fg=244), width),
        ]

    def _choice_meter(self, options: tuple[str, ...], current: str, *, accent_fg: int) -> str:
        tokens: list[str] = []
        for option in options:
            active = option == current
            glyph = "◆" if active else "◇"
            tokens.append(_colorize(glyph, fg=accent_fg if active else 244, bold=active))
        return "".join(tokens)

    def _result_rank(self) -> str:
        if self.last_win:
            return "S"
        if self.snapshot.score >= 18:
            return "A"
        if self.snapshot.score >= 10:
            return "B"
        if self.snapshot.score >= 5:
            return "C"
        return "D"

    def _start_chip_lines(self, width: int) -> list[str]:
        return [
            f"{_pill_text(self._t('game_snake_start_speed_chip'))} "
            f"{self._choice_meter(SNAKE_SPEED_OPTIONS, self.selected_speed, accent_fg=45)} "
            f"{self._speed_label(self.selected_speed)}",
            clip_text(self._t(f"game_snake_speed_desc_{self.selected_speed}"), width - 4),
            f"{_pill_text(self._t('game_snake_start_difficulty_chip'), bg=94)} "
            f"{self._choice_meter(SNAKE_DIFFICULTY_OPTIONS, self.selected_difficulty, accent_fg=214)} "
            f"{self._difficulty_label(self.selected_difficulty)}",
            clip_text(self._t(f"game_snake_difficulty_desc_{self.selected_difficulty}"), width - 4),
            f"{_pill_text(self._t('game_snake_start_obstacle_chip'), bg=240)} "
            f"{self._t('game_snake_start_obstacles', count=self._difficulty_rocks(self.selected_difficulty))}",
        ]

    def _start_screen_lines(self, width: int) -> list[str]:
        speed_label = self._speed_label(self.selected_speed)
        difficulty_label = self._difficulty_label(self.selected_difficulty)
        speed_desc = self._t(f"game_snake_speed_desc_{self.selected_speed}")
        difficulty_desc = self._t(f"game_snake_difficulty_desc_{self.selected_difficulty}")
        return [
            clip_text(self._t("game_snake_start_title", best=self.snapshot.best_score), width - 4),
            clip_text(self._t("game_snake_start_subtitle"), width - 4),
            clip_text(self._t("game_snake_start_speed", value=speed_label), width - 4),
            clip_text(speed_desc, width - 4),
            clip_text(self._t("game_snake_start_difficulty", value=difficulty_label), width - 4),
            clip_text(
                self._t(
                    "game_snake_start_obstacles",
                    count=self._difficulty_rocks(self.selected_difficulty),
                ),
                width - 4,
            ),
            clip_text(difficulty_desc, width - 4),
            clip_text(self._t("game_snake_start_hint"), width - 4),
        ]

    def _result_lines(self, width: int) -> list[str]:
        return [
            f"{_pill_text(self._t('game_snake_summary_rank_chip'), bg=130)} {self._result_rank()}",
            clip_text(
                self._t("game_snake_summary_title_win" if self.last_win else "game_snake_summary_title_over"),
                width - 4,
            ),
            clip_text(
                self._t(
                    "game_snake_summary_stats",
                    score=self.snapshot.score,
                    best=self.snapshot.best_score,
                    length=self.snapshot.length,
                ),
                width - 4,
            ),
            clip_text(
                self._t(
                    "game_snake_summary_meta",
                    speed=self._speed_label(),
                    difficulty=self._difficulty_label(),
                    rocks=len(self.snapshot.rocks),
                ),
                width - 4,
            ),
            clip_text(self._t("game_snake_summary_hint"), width - 4),
        ]

    def _banner_message(self, status_message: str) -> tuple[str, str] | None:
        if self.paused:
            return (" Pause ", self._t("game_snake_banner_paused"))
        if status_message:
            return (" Status ", status_message)
        return None

    def _radar_lines(self, width: int) -> list[str]:
        direction_label = self._t(f"game_snake_direction_{self.snapshot.direction}")
        line_1 = self._t(
            "game_snake_radar_line_1",
            direction=direction_label,
            food=f"{self.snapshot.food_row + 1:02d},{self.snapshot.food_col + 1:02d}",
        )
        line_2 = self._t(
            "game_snake_radar_line_2",
            speed=self._speed_label(),
            difficulty=self._difficulty_label(),
            rocks=len(self.snapshot.rocks),
            tick=f"{self._tick_seconds():.2f}",
        )
        return [
            *_fit_lines(line_1, width - 4),
            *_fit_lines(line_2, width - 4),
            *_fit_lines(
                self._t(
                    "game_snake_radar_tip",
                    score_target=max(6, self.snapshot.best_score + 1),
                ),
                width - 4,
            ),
        ]

    def _render_start(self, status_message: str = "") -> str:
        width = _game_width()
        preview = self._preview_snapshot()
        sections = [
            *self._hero_banner_lines(width),
            *_frame_block(self._start_screen_lines(width), width, title=" Snake "),
            *_frame_block(self._start_chip_lines(width), width, title=" Build "),
            *_snake_board_lines(
                preview.snake,
                preview.rocks,
                (preview.food_row, preview.food_col),
                width,
                direction=preview.direction,
            ),
            *_frame_block(
                [
                    clip_text(
                        self._t(
                            "game_snake_start_preview",
                            speed=self._speed_label(self.selected_speed),
                            difficulty=self._difficulty_label(self.selected_difficulty),
                        ),
                        width - 4,
                    ),
                    *_fit_lines(self._t("game_snake_start_controls"), width - 4),
                ],
                width,
                title=" Setup ",
            ),
        ]
        if status_message:
            sections.extend(_frame_block(_fit_lines(status_message, width - 4), width, title=" Status "))
        return "\n".join(sections)

    def _render(self, status_message: str = "") -> str:
        width = _game_width()
        state = (
            self._t("game_snake_state_over")
            if self.snapshot.game_over
            else self._t("game_snake_state_paused")
            if self.paused
            else self._t("game_snake_state_running")
        )
        title = clip_text(
            self._t(
                "game_snake_header",
                score=self.snapshot.score,
                best=self.snapshot.best_score,
                length=self.snapshot.length,
                state=state,
            ),
            width - 4,
        )
        subtitle = clip_text(self._t("game_snake_subtitle"), width - 4)
        legend = clip_text(self._t("game_snake_legend"), width - 4)
        controls = _fit_lines(self._t("game_snake_controls"), width - 4)
        sections = [
            *_frame_block([title, subtitle, legend], width, title=" Snake "),
            *_frame_block(self._radar_lines(width), width, title=" Radar "),
            *_snake_board_lines(
                self.snapshot.snake,
                self.snapshot.rocks,
                (self.snapshot.food_row, self.snapshot.food_col),
                width,
                direction=self.snapshot.direction,
                impact_cell=self.last_impact_cell,
            ),
            *_frame_block(controls, width, title=" Controls "),
        ]
        banner = self._banner_message(status_message)
        if banner is not None:
            title_text, body = banner
            sections.extend(_frame_block(_fit_lines(body, width - 4), width, title=title_text))
        return "\n".join(sections)

    def _render_summary(self) -> str:
        width = _game_width()
        sections = [
            *self._hero_banner_lines(width, summary=True),
            *_frame_block(self._result_lines(width), width, title=" Result "),
            *_snake_board_lines(
                self.snapshot.snake,
                self.snapshot.rocks,
                (self.snapshot.food_row, self.snapshot.food_col),
                width,
                direction=self.snapshot.direction,
                impact_cell=self.last_impact_cell,
            ),
            *_frame_block(
                [
                    clip_text(
                        self._t(
                            "game_snake_summary_story",
                            speed=self._speed_label(),
                            difficulty=self._difficulty_label(),
                        ),
                        width - 4,
                    ),
                    *_fit_lines(self._t("game_snake_summary_controls"), width - 4),
                ],
                width,
                title=" Next ",
            ),
        ]
        return "\n".join(sections)

    def _trigger_boss_key(self, input_reader: KeyReader) -> tuple[bool, str]:
        resolved = resolve_boss_command()
        if resolved is None:
            return False, ""

        command, label = resolved
        try:
            input_reader.run_external(command)
        except OSError:
            return False, ""
        return True, self._t("reader_boss_returned", app=label)

    def _step(self) -> str:
        result = move_snake(
            self.snapshot.snake,
            self.snapshot.direction,
            (self.snapshot.food_row, self.snapshot.food_col),
            self.snapshot.rocks,
            self.rng,
        )
        self.snapshot.snake = result.snake
        self.snapshot.score += result.score_gain
        self.snapshot.best_score = max(self.snapshot.best_score, self.snapshot.score)
        if result.impact_cell is not None and _snake_in_bounds(*result.impact_cell):
            self.last_impact_cell = result.impact_cell
        else:
            self.last_impact_cell = None
        self.last_win = False
        if result.food is not None:
            self.snapshot.food_row, self.snapshot.food_col = result.food
        if result.game_over:
            self.snapshot.game_over = True
            self.last_win = result.food is None and result.ate_food
            self.screen = "summary"
            self._persist()
            if result.food is None and result.ate_food:
                return self._t("game_snake_win")
            return self._t("game_snake_over")

        self._persist()
        if result.ate_food:
            return self._t("game_snake_ate_food")
        return ""

    def run(self) -> int:
        """Run the Snake interaction loop."""

        if not self.snapshot.snake:
            self.snapshot.speed = self.selected_speed
            self.snapshot.difficulty = self.selected_difficulty
            self.snapshot.best_score = max(self.snapshot.best_score, self.snapshot.score)
        else:
            self.snapshot.speed = _normalize_snake_speed(self.snapshot.speed)
            self.snapshot.difficulty = _normalize_snake_difficulty(self.snapshot.difficulty)
            self.snapshot.best_score = max(self.snapshot.best_score, self.snapshot.score)
            self._persist()

        boss_mode = False
        status_message = ""

        with KeyReader() as input_reader:
            while True:
                terminal_height = shutil.get_terminal_size((88, 28)).lines
                screen = (
                    _format_boss_dashboard(_game_width(), terminal_height, self.ui_language, status_message)
                    if boss_mode
                    else self._render_start(status_message)
                    if self.screen == "start"
                    else self._render_summary()
                    if self.screen == "summary"
                    else self._render(status_message)
                )
                render_screen(screen)
                status_message = ""

                timeout = None if boss_mode or self.screen != "play" or self.paused else self._tick_seconds()
                command = input_reader.read_key(timeout=timeout)
                if command is None:
                    status_message = self._step()
                    continue

                if boss_mode:
                    if command in {"b", "escape", "q", "Q"}:
                        boss_mode = False
                    continue

                if command in {"q", "Q", "escape"}:
                    if self.screen == "play":
                        self._persist()
                    return 0

                if command in {"p", "P"}:
                    if self.screen != "play":
                        continue
                    self.paused = not self.paused
                    status_message = self._t("game_snake_paused" if self.paused else "game_snake_resumed")
                    continue

                if command == "b":
                    launched, boss_status = self._trigger_boss_key(input_reader)
                    if launched:
                        status_message = boss_status
                    else:
                        boss_mode = True
                    continue

                if self.screen == "start":
                    if command in {"a", "A", "left"}:
                        self.selected_speed = _cycle_snake_option(SNAKE_SPEED_OPTIONS, self.selected_speed, -1)
                        status_message = self._t("game_snake_status_speed", value=self._speed_label(self.selected_speed))
                        continue
                    if command in {"d", "D", "right"}:
                        self.selected_speed = _cycle_snake_option(SNAKE_SPEED_OPTIONS, self.selected_speed, 1)
                        status_message = self._t("game_snake_status_speed", value=self._speed_label(self.selected_speed))
                        continue
                    if command in {"w", "W", "up"}:
                        self.selected_difficulty = _cycle_snake_option(
                            SNAKE_DIFFICULTY_OPTIONS, self.selected_difficulty, -1
                        )
                        status_message = self._t(
                            "game_snake_status_difficulty",
                            value=self._difficulty_label(self.selected_difficulty),
                        )
                        continue
                    if command in {"s", "S", "down"}:
                        self.selected_difficulty = _cycle_snake_option(
                            SNAKE_DIFFICULTY_OPTIONS, self.selected_difficulty, 1
                        )
                        status_message = self._t(
                            "game_snake_status_difficulty",
                            value=self._difficulty_label(self.selected_difficulty),
                        )
                        continue
                    if command in {" ", "j", "\r", "\n", "enter"}:
                        self._start_new_game()
                        status_message = self._t("game_snake_new_game")
                        continue
                    status_message = self._t("game_snake_start_unknown_command")
                    continue

                if self.screen == "summary":
                    if command in {"r", "R", "n", "N", " ", "\r", "\n", "enter"}:
                        self.screen = "start"
                        self.paused = False
                        self.last_impact_cell = None
                        status_message = self._t("game_snake_back_to_setup")
                        continue
                    status_message = self._t("game_snake_summary_unknown_command")
                    continue

                if command in {"r", "R", "n", "N"}:
                    self.screen = "start"
                    self.paused = False
                    self.last_impact_cell = None
                    self.selected_speed = _normalize_snake_speed(self.snapshot.speed)
                    self.selected_difficulty = _normalize_snake_difficulty(self.snapshot.difficulty)
                    status_message = self._t("game_snake_back_to_setup")
                    continue

                requested_direction = {
                    "w": "up",
                    "W": "up",
                    "s": "down",
                    "S": "down",
                    "a": "left",
                    "A": "left",
                    "d": "right",
                    "D": "right",
                    "up": "up",
                    "down": "down",
                    "left": "left",
                    "right": "right",
                }.get(command)

                if requested_direction is None:
                    status_message = self._t("game_snake_unknown_command")
                    continue

                if self.paused:
                    self.paused = False

                self.snapshot.direction = _next_snake_direction(self.snapshot.direction, requested_direction)
                status_message = self._step()


class GameGomokuSession:
    """Interactive Gomoku runtime with a lightweight built-in AI."""

    def __init__(
        self,
        snapshot: GameGomokuSnapshot,
        *,
        ui_language: str = "zh",
        rng: random.Random | None = None,
        state_callback: Callable[[GameGomokuSnapshot], None] | None = None,
    ) -> None:
        self.snapshot = snapshot
        self.ui_language = ui_language
        self.rng = rng or random.Random()
        self.state_callback = state_callback

    def _t(self, key: str, **kwargs: object) -> str:
        return tr(self.ui_language, key, **kwargs)

    def _persist(self) -> None:
        if self.state_callback is None:
            return
        self.state_callback(
            GameGomokuSnapshot(
                board=clone_gomoku_board(self.snapshot.board),
                cursor_row=self.snapshot.cursor_row,
                cursor_col=self.snapshot.cursor_col,
                winner=self.snapshot.winner,
                game_over=self.snapshot.game_over,
            )
        )

    def _start_new_game(self) -> None:
        self.snapshot = start_gomoku_game()
        self._persist()

    def _status_label(self) -> str:
        if self.snapshot.winner == "human":
            return self._t("game_gomoku_result_human")
        if self.snapshot.winner == "ai":
            return self._t("game_gomoku_result_ai")
        if self.snapshot.winner == "draw":
            return self._t("game_gomoku_result_draw")
        return self._t("game_gomoku_result_playing")

    def _hero_lines(self, width: int) -> list[str]:
        title_key = "game_gomoku_banner_result" if self.snapshot.game_over else "game_gomoku_banner"
        subtitle_key = (
            "game_gomoku_tagline_result_human"
            if self.snapshot.winner == "human"
            else "game_gomoku_tagline_result_ai"
            if self.snapshot.winner == "ai"
            else "game_gomoku_tagline_result_draw"
            if self.snapshot.winner == "draw"
            else "game_gomoku_tagline"
        )
        return _hero_banner(
            width,
            self._t(title_key),
            self._t(subtitle_key),
            border_fg=137,
            fill_bg=95,
        )

    def _status_lines(self, width: int) -> list[str]:
        placed = sum(1 for row in self.snapshot.board for cell in row if cell == GOMOKU_HUMAN_STONE)
        ai_stones = sum(1 for row in self.snapshot.board for cell in row if cell == GOMOKU_AI_STONE)
        return [
            f"{_pill_text(self._t('game_gomoku_chip_status'), bg=95)} {self._status_label()}",
            clip_text(
                self._t(
                    "game_gomoku_stats_line_1",
                    moves=self.snapshot.move_count,
                    human=placed,
                    ai=ai_stones,
                ),
                width - 4,
            ),
            clip_text(
                self._t(
                    "game_gomoku_stats_line_2",
                    cursor=f"{self.snapshot.cursor_row + 1},{chr(ord('A') + self.snapshot.cursor_col)}",
                ),
                width - 4,
            ),
        ]

    def _result_lines(self, width: int) -> list[str]:
        title_key = (
            "game_gomoku_summary_title_human"
            if self.snapshot.winner == "human"
            else "game_gomoku_summary_title_ai"
            if self.snapshot.winner == "ai"
            else "game_gomoku_summary_title_draw"
        )
        flavor_key = (
            "game_gomoku_summary_flavor_human"
            if self.snapshot.winner == "human"
            else "game_gomoku_summary_flavor_ai"
            if self.snapshot.winner == "ai"
            else "game_gomoku_summary_flavor_draw"
        )
        return [
            f"{_pill_text(self._t('game_gomoku_chip_result'), bg=137)} {self._status_label()}",
            clip_text(self._t(title_key), width - 4),
            clip_text(self._t(flavor_key), width - 4),
        ]

    def _table_lines(self, width: int) -> list[str]:
        winning = self.snapshot.game_over and self.snapshot.winner in {"human", "ai"}
        accent = "◆" if winning else "◦"
        fg = 130 if winning else 137
        return [
            _sparkline(width, accent, fg=fg, bg=GOMOKU_FRAME_BG),
            _center_line(_colorize(self._t("game_gomoku_table_line"), fg=230, bg=GOMOKU_FRAME_BG, bold=True), width),
        ]

    def _render(self, status_message: str = "") -> str:
        width = _game_width()
        title = clip_text(
            self._t(
                "game_gomoku_header",
                status=self._status_label(),
                moves=self.snapshot.move_count,
            ),
            width - 4,
        )
        subtitle = clip_text(self._t("game_gomoku_subtitle"), width - 4)
        legend = clip_text(self._t("game_gomoku_legend"), width - 4)
        controls = _fit_lines(self._t("game_gomoku_controls"), width - 4)
        sections = [
            *self._hero_lines(width),
            *_frame_block([title, subtitle, legend], width, title=" Gomoku "),
            *_frame_block(self._status_lines(width), width, title=" Focus "),
            *self._table_lines(width),
            *_gomoku_board_lines(
                self.snapshot.board,
                cursor_row=self.snapshot.cursor_row,
                cursor_col=self.snapshot.cursor_col,
                width=width,
            ),
            *_frame_block(controls, width, title=" Controls "),
        ]
        if self.snapshot.game_over:
            sections.extend(_frame_block(self._result_lines(width), width, title=" Result "))
        if status_message:
            sections.extend(_frame_block(_fit_lines(status_message, width - 4), width, title=" Status "))
        return "\n".join(sections)

    def _trigger_boss_key(self, input_reader: KeyReader) -> tuple[bool, str]:
        resolved = resolve_boss_command()
        if resolved is None:
            return False, ""

        command, label = resolved
        try:
            input_reader.run_external(command)
        except OSError:
            return False, ""
        return True, self._t("reader_boss_returned", app=label)

    def _move_cursor(self, row_delta: int, col_delta: int) -> None:
        self.snapshot.cursor_row = max(
            0,
            min(GOMOKU_BOARD_SIZE - 1, self.snapshot.cursor_row + row_delta),
        )
        self.snapshot.cursor_col = max(
            0,
            min(GOMOKU_BOARD_SIZE - 1, self.snapshot.cursor_col + col_delta),
        )

    def _nearest_empty_cursor(self, row_index: int, col_index: int) -> tuple[int, int]:
        if self.snapshot.board[row_index][col_index] == GOMOKU_EMPTY:
            return row_index, col_index

        for radius in range(1, GOMOKU_BOARD_SIZE):
            for row_delta in range(-radius, radius + 1):
                for col_delta in range(-radius, radius + 1):
                    next_row = row_index + row_delta
                    next_col = col_index + col_delta
                    if not _gomoku_in_bounds(next_row, next_col):
                        continue
                    if self.snapshot.board[next_row][next_col] == GOMOKU_EMPTY:
                        return next_row, next_col
        return row_index, col_index

    def _apply_human_move(self) -> str:
        row_index = self.snapshot.cursor_row
        col_index = self.snapshot.cursor_col
        if self.snapshot.board[row_index][col_index] != GOMOKU_EMPTY:
            return self._t("game_gomoku_cell_occupied")

        self.snapshot.board[row_index][col_index] = GOMOKU_HUMAN_STONE
        if is_gomoku_winning_move(self.snapshot.board, row_index, col_index, GOMOKU_HUMAN_STONE):
            self.snapshot.winner = "human"
            self.snapshot.game_over = True
            self._persist()
            return self._t("game_gomoku_human_win")

        if gomoku_board_full(self.snapshot.board):
            self.snapshot.winner = "draw"
            self.snapshot.game_over = True
            self._persist()
            return self._t("game_gomoku_draw")

        ai_move = choose_gomoku_ai_move(self.snapshot.board, self.rng)
        if ai_move is None:
            self.snapshot.winner = "draw"
            self.snapshot.game_over = True
            self._persist()
            return self._t("game_gomoku_draw")

        ai_row, ai_col = ai_move
        self.snapshot.board[ai_row][ai_col] = GOMOKU_AI_STONE
        if is_gomoku_winning_move(self.snapshot.board, ai_row, ai_col, GOMOKU_AI_STONE):
            self.snapshot.winner = "ai"
            self.snapshot.game_over = True
            self.snapshot.cursor_row = ai_row
            self.snapshot.cursor_col = ai_col
            self._persist()
            return self._t("game_gomoku_ai_win")

        if gomoku_board_full(self.snapshot.board):
            self.snapshot.winner = "draw"
            self.snapshot.game_over = True
            self.snapshot.cursor_row = ai_row
            self.snapshot.cursor_col = ai_col
            self._persist()
            return self._t("game_gomoku_draw")

        next_row, next_col = self._nearest_empty_cursor(row_index, col_index)
        self.snapshot.cursor_row = next_row
        self.snapshot.cursor_col = next_col
        self._persist()
        return self._t("game_gomoku_move_ok")

    def run(self) -> int:
        """Run the Gomoku interaction loop."""

        if not self.snapshot.board:
            self._start_new_game()
        else:
            self.snapshot.cursor_row = max(0, min(GOMOKU_BOARD_SIZE - 1, self.snapshot.cursor_row))
            self.snapshot.cursor_col = max(0, min(GOMOKU_BOARD_SIZE - 1, self.snapshot.cursor_col))
            self._persist()

        boss_mode = False
        status_message = ""

        with KeyReader() as input_reader:
            while True:
                terminal_height = shutil.get_terminal_size((88, 28)).lines
                screen = (
                    _format_boss_dashboard(_game_width(), terminal_height, self.ui_language, status_message)
                    if boss_mode
                    else self._render(status_message)
                )
                render_screen(screen)
                status_message = ""

                command = input_reader.read_key()
                if boss_mode:
                    if command in {"b", "escape", "q", "Q"}:
                        boss_mode = False
                    continue

                if command in {"q", "Q", "escape"}:
                    self._persist()
                    return 0

                if command in {"r", "R", "n", "N"}:
                    self._start_new_game()
                    status_message = self._t("game_gomoku_new_game")
                    continue

                if command == "b":
                    launched, boss_status = self._trigger_boss_key(input_reader)
                    if launched:
                        status_message = boss_status
                    else:
                        boss_mode = True
                    continue

                direction = {
                    "w": (-1, 0),
                    "W": (-1, 0),
                    "s": (1, 0),
                    "S": (1, 0),
                    "a": (0, -1),
                    "A": (0, -1),
                    "d": (0, 1),
                    "D": (0, 1),
                    "up": (-1, 0),
                    "down": (1, 0),
                    "left": (0, -1),
                    "right": (0, 1),
                }.get(command)
                if direction is not None:
                    row_delta, col_delta = direction
                    self._move_cursor(row_delta, col_delta)
                    continue

                if command in {" ", "space", "j", "J", "enter"}:
                    if self.snapshot.game_over:
                        status_message = self._status_label()
                        continue
                    status_message = self._apply_human_move()
                    continue

                status_message = self._t("game_gomoku_unknown_command")


def run_2048(
    *,
    ui_language: str = "zh",
    initial_board: list[list[int]] | None = None,
    initial_score: int = 0,
    best_score: int = 0,
    won: bool = False,
    game_over: bool = False,
    rng: random.Random | None = None,
    state_callback: Callable[[Game2048Snapshot], None] | None = None,
) -> int:
    """Launch the built-in 2048 game."""

    snapshot = Game2048Snapshot(
        board=clone_2048_board(initial_board or []),
        score=max(0, initial_score),
        best_score=max(best_score, initial_score),
        won=won,
        game_over=game_over,
    )
    return Game2048Session(
        snapshot,
        ui_language=ui_language,
        rng=rng,
        state_callback=state_callback,
    ).run()


def run_snake(
    *,
    ui_language: str = "zh",
    initial_snake: list[tuple[int, int]] | None = None,
    initial_rocks: list[tuple[int, int]] | None = None,
    food_row: int = 0,
    food_col: int = 0,
    direction: str = "right",
    speed: str = "normal",
    difficulty: str = "normal",
    initial_score: int = 0,
    best_score: int = 0,
    game_over: bool = False,
    rng: random.Random | None = None,
    state_callback: Callable[[GameSnakeSnapshot], None] | None = None,
) -> int:
    """Launch the built-in Snake game."""

    snapshot = GameSnakeSnapshot(
        snake=clone_snake_body(initial_snake or []),
        rocks=_clone_snake_points(initial_rocks or []),
        food_row=food_row,
        food_col=food_col,
        direction=direction if direction in SNAKE_DIRECTION_DELTAS else "right",
        speed=_normalize_snake_speed(speed),
        difficulty=_normalize_snake_difficulty(difficulty),
        score=max(0, initial_score),
        best_score=max(best_score, initial_score),
        game_over=game_over,
    )
    return GameSnakeSession(
        snapshot,
        ui_language=ui_language,
        rng=rng,
        state_callback=state_callback,
    ).run()


def run_gomoku(
    *,
    ui_language: str = "zh",
    initial_board: list[list[str]] | None = None,
    cursor_row: int = GOMOKU_BOARD_SIZE // 2,
    cursor_col: int = GOMOKU_BOARD_SIZE // 2,
    winner: str = "",
    game_over: bool = False,
    rng: random.Random | None = None,
    state_callback: Callable[[GameGomokuSnapshot], None] | None = None,
) -> int:
    """Launch the built-in Gomoku game."""

    snapshot = GameGomokuSnapshot(
        board=clone_gomoku_board(initial_board or []),
        cursor_row=max(0, min(GOMOKU_BOARD_SIZE - 1, cursor_row)),
        cursor_col=max(0, min(GOMOKU_BOARD_SIZE - 1, cursor_col)),
        winner=winner if winner in {"", "human", "ai", "draw"} else "",
        game_over=game_over,
    )
    return GameGomokuSession(
        snapshot,
        ui_language=ui_language,
        rng=rng,
        state_callback=state_callback,
    ).run()
