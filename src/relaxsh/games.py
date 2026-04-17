"""Built-in terminal mini-games for RelaxSH."""

from __future__ import annotations

import random
import os
import re
import shutil
import sys
from dataclasses import dataclass
from datetime import datetime
from typing import Callable

from relaxsh.display import clip_text, text_width, wrap_text
from relaxsh.i18n import tr
from relaxsh.reader import KeyReader, render_screen, resolve_boss_command


BOARD_SIZE = 4
TARGET_TILE = 2048
BOARD_CELL_MIN_WIDTH = 4
BOARD_CELL_MAX_WIDTH = 7
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
GOMOKU_GRID_FG = 94
GOMOKU_STAR_FG = 130
GOMOKU_BLACK_STONE_FG = 16
GOMOKU_WHITE_STONE_FG = 255
GOMOKU_CURSOR_EMPTY_FG = 18
GOMOKU_CURSOR_BLACK_FG = 16
GOMOKU_CURSOR_WHITE_FG = 255
GOMOKU_WIN_BG = 220
GOMOKU_WIN_WHITE_FG = 52


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


def _empty_2048_board() -> list[list[int]]:
    return [[0 for _ in range(BOARD_SIZE)] for _ in range(BOARD_SIZE)]


def _empty_gomoku_board() -> list[list[str]]:
    return [[GOMOKU_EMPTY for _ in range(GOMOKU_BOARD_SIZE)] for _ in range(GOMOKU_BOARD_SIZE)]


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
    lines = [_gomoku_axis_labels(compact=compact)]
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
        lines.append(f"{row_index + 1:>2} {body}")
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
            *_frame_block([title, subtitle], width, title=" 2048 "),
            *_board_lines(self.snapshot.board, width),
            *_frame_block(controls, width, title=" Controls "),
        ]
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
            *_frame_block([title, subtitle, legend], width, title=" Gomoku "),
            *_gomoku_board_lines(
                self.snapshot.board,
                cursor_row=self.snapshot.cursor_row,
                cursor_col=self.snapshot.cursor_col,
                width=width,
            ),
            *_frame_block(controls, width, title=" Controls "),
        ]
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
