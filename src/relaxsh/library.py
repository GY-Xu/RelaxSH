"""Persistent library and reading progress storage for RelaxSH."""

from __future__ import annotations

import hashlib
import json
import os
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from relaxsh.i18n import SUPPORTED_LANGUAGES, normalize_language
from relaxsh.reader import ReaderError, load_text_with_encoding, normalize_text


SUPPORTED_SUFFIXES = {".txt"}
STATE_FILENAME = "library.json"
GAME_2048_BOARD_SIZE = 4
GAME_GOMOKU_BOARD_SIZE = 11
GAME_SNAKE_ROWS = 12
GAME_SNAKE_COLS = 18


def utc_now_iso() -> str:
    """Return the current UTC timestamp in ISO 8601 format."""

    return datetime.now(timezone.utc).isoformat()


def get_app_home() -> Path:
    """Resolve the directory used to persist RelaxSH state."""

    override = os.environ.get("RELAXSH_HOME")
    if override:
        return Path(override).expanduser().resolve()

    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "RelaxSH"

    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "RelaxSH"

    base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return base / "relaxsh"


def get_state_path() -> Path:
    """Resolve the JSON file that stores books and progress."""

    return get_app_home() / STATE_FILENAME


def ensure_app_home() -> Path:
    """Create the state directory if needed."""

    app_home = get_app_home()
    app_home.mkdir(parents=True, exist_ok=True)
    return app_home


def sha1_for_file(path: Path) -> str:
    """Hash a file to help detect duplicate imports."""

    digest = hashlib.sha1()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def format_timestamp(value: str | None) -> str:
    """Render an ISO timestamp into a compact local string."""

    if not value:
        return "-"

    try:
        timestamp = datetime.fromisoformat(value)
    except ValueError:
        return value
    return timestamp.astimezone().strftime("%Y-%m-%d %H:%M")


@dataclass
class ReadingProgress:
    """Resume information for a single book."""

    cursor_offset: int = 0
    furthest_offset: int = 0
    last_read_at: str | None = None


@dataclass
class BookmarkRecord:
    """One saved bookmark or excerpt for a book."""

    id: str
    offset: int
    created_at: str
    excerpt: str
    note: str = ""


@dataclass
class AppSettings:
    """Global app settings stored alongside the library."""

    language: str = "zh"


def _normalize_2048_board(board: object) -> list[list[int]]:
    """Normalize a persisted 2048 board into a safe 4x4 integer grid."""

    if not isinstance(board, list) or len(board) != GAME_2048_BOARD_SIZE:
        return []

    normalized: list[list[int]] = []
    for row in board:
        if not isinstance(row, list) or len(row) != GAME_2048_BOARD_SIZE:
            return []
        normalized_row: list[int] = []
        for value in row:
            try:
                normalized_row.append(max(0, int(value)))
            except (TypeError, ValueError):
                return []
        normalized.append(normalized_row)
    return normalized


def _normalize_gomoku_board(board: object) -> list[list[str]]:
    """Normalize a persisted Gomoku board into a safe 11x11 grid."""

    if not isinstance(board, list) or len(board) != GAME_GOMOKU_BOARD_SIZE:
        return []

    normalized: list[list[str]] = []
    for row in board:
        if not isinstance(row, list) or len(row) != GAME_GOMOKU_BOARD_SIZE:
            return []
        normalized_row: list[str] = []
        for value in row:
            token = str(value)
            normalized_row.append(token if token in {"", "X", "O"} else "")
        normalized.append(normalized_row)
    return normalized


def _normalize_snake_body(body: object) -> list[list[int]]:
    """Normalize a persisted Snake body into unique in-bounds coordinates."""

    if not isinstance(body, list):
        return []

    normalized: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for segment in body:
        if not isinstance(segment, (list, tuple)) or len(segment) != 2:
            return []
        try:
            row_index = int(segment[0])
            col_index = int(segment[1])
        except (TypeError, ValueError):
            return []
        if not (0 <= row_index < GAME_SNAKE_ROWS and 0 <= col_index < GAME_SNAKE_COLS):
            return []
        key = (row_index, col_index)
        if key in seen:
            return []
        seen.add(key)
        normalized.append([row_index, col_index])
    return normalized


def _normalize_snake_points(points: object) -> list[list[int]]:
    if not isinstance(points, list):
        return []

    normalized: list[list[int]] = []
    seen: set[tuple[int, int]] = set()
    for entry in points:
        if not isinstance(entry, (list, tuple)) or len(entry) != 2:
            return []
        try:
            row_index = int(entry[0])
            col_index = int(entry[1])
        except (TypeError, ValueError):
            return []
        if not (0 <= row_index < GAME_SNAKE_ROWS and 0 <= col_index < GAME_SNAKE_COLS):
            return []
        key = (row_index, col_index)
        if key in seen:
            continue
        seen.add(key)
        normalized.append([row_index, col_index])
    return normalized


@dataclass
class Game2048Record:
    """Persisted state for the built-in 2048 game."""

    best_score: int = 0
    score: int = 0
    board: list[list[int]] = field(default_factory=list)
    won: bool = False
    game_over: bool = False
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "Game2048Record":
        board = _normalize_2048_board(payload.get("board"))
        return cls(
            best_score=max(0, int(payload.get("best_score", 0))),
            score=max(0, int(payload.get("score", 0))),
            board=board,
            won=bool(payload.get("won", False)),
            game_over=bool(payload.get("game_over", False)),
            updated_at=payload.get("updated_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def has_saved_game(self) -> bool:
        return bool(self.board) and not self.game_over

    @property
    def max_tile(self) -> int:
        if not self.board:
            return 0
        return max((max(row) for row in self.board), default=0)


@dataclass
class GameGomokuRecord:
    """Persisted state for the built-in Gomoku game."""

    board: list[list[str]] = field(default_factory=list)
    cursor_row: int = GAME_GOMOKU_BOARD_SIZE // 2
    cursor_col: int = GAME_GOMOKU_BOARD_SIZE // 2
    winner: str = ""
    game_over: bool = False
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "GameGomokuRecord":
        board = _normalize_gomoku_board(payload.get("board"))
        cursor_row = max(0, min(GAME_GOMOKU_BOARD_SIZE - 1, int(payload.get("cursor_row", GAME_GOMOKU_BOARD_SIZE // 2))))
        cursor_col = max(0, min(GAME_GOMOKU_BOARD_SIZE - 1, int(payload.get("cursor_col", GAME_GOMOKU_BOARD_SIZE // 2))))
        winner = str(payload.get("winner", ""))
        winner = winner if winner in {"", "human", "ai", "draw"} else ""
        return cls(
            board=board,
            cursor_row=cursor_row,
            cursor_col=cursor_col,
            winner=winner,
            game_over=bool(payload.get("game_over", False)),
            updated_at=payload.get("updated_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def has_saved_game(self) -> bool:
        return bool(self.board) and any(any(cell for cell in row) for row in self.board) and not self.game_over

    @property
    def move_count(self) -> int:
        if not self.board:
            return 0
        return sum(1 for row in self.board for cell in row if cell)


@dataclass
class GameSnakeRecord:
    """Persisted state for the built-in Snake game."""

    best_score: int = 0
    score: int = 0
    snake: list[list[int]] = field(default_factory=list)
    rocks: list[list[int]] = field(default_factory=list)
    food_row: int = 0
    food_col: int = 0
    direction: str = "right"
    speed: str = "normal"
    difficulty: str = "normal"
    game_over: bool = False
    updated_at: str | None = None

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "GameSnakeRecord":
        snake = _normalize_snake_body(payload.get("snake"))
        rocks = _normalize_snake_points(payload.get("rocks"))
        food_row = int(payload.get("food_row", 0))
        food_col = int(payload.get("food_col", 0))
        if not (0 <= food_row < GAME_SNAKE_ROWS):
            food_row = 0
        if not (0 <= food_col < GAME_SNAKE_COLS):
            food_col = 0
        direction = str(payload.get("direction", "right"))
        if direction not in {"up", "down", "left", "right"}:
            direction = "right"
        speed = str(payload.get("speed", "normal"))
        if speed not in {"slow", "normal", "fast"}:
            speed = "normal"
        difficulty = str(payload.get("difficulty", "normal"))
        if difficulty not in {"easy", "normal", "hard"}:
            difficulty = "normal"
        return cls(
            best_score=max(0, int(payload.get("best_score", 0))),
            score=max(0, int(payload.get("score", 0))),
            snake=snake,
            rocks=rocks,
            food_row=food_row,
            food_col=food_col,
            direction=direction,
            speed=speed,
            difficulty=difficulty,
            game_over=bool(payload.get("game_over", False)),
            updated_at=payload.get("updated_at"),
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def has_saved_game(self) -> bool:
        return bool(self.snake) and not self.game_over

    @property
    def length(self) -> int:
        return len(self.snake)


@dataclass
class BookRecord:
    """Metadata and reading state for one imported novel."""

    id: str
    title: str
    path: str
    added_at: str
    updated_at: str
    size_bytes: int
    modified_at_ns: int
    total_chars: int
    content_sha1: str
    encoding: str | None = None
    progress: ReadingProgress = field(default_factory=ReadingProgress)
    bookmarks: list[BookmarkRecord] = field(default_factory=list)

    @classmethod
    def from_dict(cls, payload: dict[str, object]) -> "BookRecord":
        progress_payload = payload.get("progress", {})
        progress = ReadingProgress(
            cursor_offset=int(progress_payload.get("cursor_offset", 0)),
            furthest_offset=int(progress_payload.get("furthest_offset", 0)),
            last_read_at=progress_payload.get("last_read_at"),
        )
        bookmarks = [
            BookmarkRecord(
                id=str(bookmark["id"]),
                offset=int(bookmark.get("offset", 0)),
                created_at=str(bookmark.get("created_at", "")),
                excerpt=str(bookmark.get("excerpt", "")),
                note=str(bookmark.get("note", "")),
            )
            for bookmark in payload.get("bookmarks", [])
        ]
        return cls(
            id=str(payload["id"]),
            title=str(payload["title"]),
            path=str(payload["path"]),
            added_at=str(payload["added_at"]),
            updated_at=str(payload["updated_at"]),
            size_bytes=int(payload.get("size_bytes", 0)),
            modified_at_ns=int(payload.get("modified_at_ns", 0)),
            total_chars=int(payload.get("total_chars", 0)),
            content_sha1=str(payload.get("content_sha1", "")),
            encoding=payload.get("encoding"),
            progress=progress,
            bookmarks=bookmarks,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @property
    def file_path(self) -> Path:
        return Path(self.path)

    @property
    def percent_read(self) -> float:
        if self.total_chars <= 0:
            return 0.0

        furthest = min(max(self.progress.furthest_offset, 0), self.total_chars)
        return round((furthest / self.total_chars) * 100, 1)

    @property
    def status(self) -> str:
        if self.progress.furthest_offset >= self.total_chars > 0:
            return "done"
        if self.progress.furthest_offset > 0:
            return "reading"
        return "new"

    @property
    def bookmark_count(self) -> int:
        return len(self.bookmarks)


@dataclass
class ImportEvent:
    """One import result for a file."""

    status: str
    book: BookRecord
    detail: str


@dataclass
class ImportSummary:
    """Summary returned after importing one path or directory."""

    imported: list[ImportEvent] = field(default_factory=list)
    updated: list[ImportEvent] = field(default_factory=list)
    skipped: list[ImportEvent] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def total_processed(self) -> int:
        return len(self.imported) + len(self.updated) + len(self.skipped)


class Library:
    """Persistent in-memory view of the user's novel library."""

    def __init__(
        self,
        books: list[BookRecord] | None = None,
        settings: AppSettings | None = None,
        game_2048: Game2048Record | None = None,
        game_gomoku: GameGomokuRecord | None = None,
        game_snake: GameSnakeRecord | None = None,
    ) -> None:
        self.books: list[BookRecord] = books or []
        self.settings = settings or AppSettings()
        self.game_2048 = game_2048 or Game2048Record()
        self.game_gomoku = game_gomoku or GameGomokuRecord()
        self.game_snake = game_snake or GameSnakeRecord()

    @classmethod
    def load(cls) -> "Library":
        state_path = get_state_path()
        if not state_path.exists():
            return cls()

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        books = [BookRecord.from_dict(book) for book in payload.get("books", [])]
        settings_payload = payload.get("settings", {})
        games_payload = payload.get("games", {})
        settings = AppSettings(
            language=normalize_language(settings_payload.get("language")),
        )
        game_2048 = Game2048Record.from_dict(games_payload.get("2048", {}))
        game_gomoku = GameGomokuRecord.from_dict(games_payload.get("gomoku", {}))
        game_snake = GameSnakeRecord.from_dict(games_payload.get("snake", {}))
        return cls(
            books,
            settings=settings,
            game_2048=game_2048,
            game_gomoku=game_gomoku,
            game_snake=game_snake,
        )

    def save(self) -> None:
        ensure_app_home()
        payload = {
            "schema_version": 5,
            "settings": asdict(self.settings),
            "books": [book.to_dict() for book in self.books],
            "games": {
                "2048": self.game_2048.to_dict(),
                "gomoku": self.game_gomoku.to_dict(),
                "snake": self.game_snake.to_dict(),
            },
        }
        get_state_path().write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    def sorted_books(self) -> list[BookRecord]:
        return sorted(
            self.books,
            key=lambda book: (
                book.progress.last_read_at or "",
                book.updated_at,
                book.added_at,
                book.title.casefold(),
            ),
            reverse=True,
        )

    def import_path(self, path: Path) -> ImportSummary:
        resolved = path.expanduser().resolve()
        summary = ImportSummary()

        if not resolved.exists():
            raise ReaderError(f"Import path not found: {resolved}")

        if resolved.is_file():
            self._import_file_into_summary(resolved, summary)
            self.save()
            return summary

        candidates = sorted(
            candidate
            for candidate in resolved.rglob("*")
            if candidate.is_file() and candidate.suffix.lower() in SUPPORTED_SUFFIXES
        )
        if not candidates:
            raise ReaderError(f"No TXT files found under: {resolved}")

        for candidate in candidates:
            self._import_file_into_summary(candidate.resolve(), summary)

        self.save()
        return summary

    def _import_file_into_summary(self, path: Path, summary: ImportSummary) -> None:
        try:
            event = self.import_file(path)
        except ReaderError as exc:
            summary.errors.append(f"{path}: {exc}")
            return

        if event.status == "imported":
            summary.imported.append(event)
        elif event.status == "updated":
            summary.updated.append(event)
        else:
            summary.skipped.append(event)

    def import_file(self, path: Path, encoding: str | None = None) -> ImportEvent:
        resolved = path.expanduser().resolve()
        if resolved.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise ReaderError(f"Only TXT files are supported right now: {resolved}")
        if not resolved.exists():
            raise ReaderError(f"Import path not found: {resolved}")
        if not resolved.is_file():
            raise ReaderError(f"Expected a TXT file, got: {resolved}")

        file_stat = resolved.stat()
        text, encoding = load_text_with_encoding(resolved, encoding=encoding)
        normalized = normalize_text(text)
        total_chars = len(normalized)
        content_sha1 = sha1_for_file(resolved)
        now = utc_now_iso()
        existing = self._find_book_by_path(resolved)
        duplicate = self._find_book_by_hash(content_sha1)

        if existing is None and duplicate is None:
            book = BookRecord(
                id=uuid.uuid4().hex,
                title=resolved.stem,
                path=str(resolved),
                added_at=now,
                updated_at=now,
                size_bytes=file_stat.st_size,
                modified_at_ns=file_stat.st_mtime_ns,
                total_chars=total_chars,
                content_sha1=content_sha1,
                encoding=encoding,
            )
            self.books.append(book)
            return ImportEvent("imported", book, "Imported new book.")

        if existing is None and duplicate is not None:
            return ImportEvent(
                "skipped",
                duplicate,
                f"Skipped duplicate content at {resolved.name}.",
            )

        previous_snapshot = (
            existing.path,
            existing.modified_at_ns,
            existing.size_bytes,
            existing.content_sha1,
        )
        existing.title = resolved.stem
        existing.path = str(resolved)
        existing.updated_at = now
        existing.size_bytes = file_stat.st_size
        existing.modified_at_ns = file_stat.st_mtime_ns
        existing.total_chars = total_chars
        existing.content_sha1 = content_sha1
        existing.encoding = encoding
        existing.progress.cursor_offset = min(existing.progress.cursor_offset, total_chars)
        existing.progress.furthest_offset = min(existing.progress.furthest_offset, total_chars)

        current_snapshot = (
            existing.path,
            existing.modified_at_ns,
            existing.size_bytes,
            existing.content_sha1,
        )
        if previous_snapshot == current_snapshot:
            return ImportEvent("skipped", existing, "Already imported and unchanged.")
        return ImportEvent("updated", existing, "Updated book metadata and file info.")

    def _find_book_by_path(self, path: Path) -> BookRecord | None:
        normalized_path = str(path)
        for book in self.books:
            if book.path == normalized_path:
                return book
        return None

    def _find_book_by_hash(self, content_sha1: str) -> BookRecord | None:
        for book in self.books:
            if book.content_sha1 and book.content_sha1 == content_sha1:
                return book

        return None

    def resolve_book(self, reference: str) -> BookRecord:
        query = reference.strip()
        if not query:
            raise ReaderError("Please provide a book id or title.")

        candidate_path = Path(query).expanduser()
        if candidate_path.exists():
            resolved_path = str(candidate_path.resolve())
            for book in self.books:
                if book.path == resolved_path:
                    return book

        for book in self.books:
            if book.id == query:
                return book

        prefix_matches = [book for book in self.books if book.id.startswith(query)]
        if len(prefix_matches) == 1:
            return prefix_matches[0]
        if len(prefix_matches) > 1:
            raise ReaderError(f"Book id prefix is ambiguous: {query}")

        lowered = query.casefold()
        exact_title_matches = [
            book
            for book in self.books
            if book.title.casefold() == lowered or Path(book.path).name.casefold() == lowered
        ]
        if len(exact_title_matches) == 1:
            return exact_title_matches[0]
        if len(exact_title_matches) > 1:
            raise ReaderError(f"Multiple books share the title: {query}")

        fuzzy_matches = [
            book
            for book in self.books
            if lowered in book.title.casefold() or lowered in Path(book.path).name.casefold()
        ]
        if len(fuzzy_matches) == 1:
            return fuzzy_matches[0]
        if len(fuzzy_matches) > 1:
            raise ReaderError(f"Book reference is ambiguous: {query}")

        raise ReaderError(f"No imported book matched: {query}")

    def most_recent_book(self) -> BookRecord:
        candidates = [book for book in self.books if book.progress.last_read_at]
        if not candidates:
            raise ReaderError("No recent book found. Read one imported book first.")
        return max(candidates, key=lambda book: book.progress.last_read_at or "")

    def update_progress(
        self,
        book_id: str,
        cursor_offset: int,
        furthest_offset: int,
    ) -> BookRecord:
        book = self.resolve_book(book_id)
        total_chars = max(book.total_chars, 0)
        book.progress.cursor_offset = min(max(cursor_offset, 0), total_chars)
        book.progress.furthest_offset = min(
            max(furthest_offset, book.progress.furthest_offset, 0),
            total_chars,
        )
        book.progress.last_read_at = utc_now_iso()
        book.updated_at = utc_now_iso()
        self.save()
        return book

    def add_bookmark(
        self,
        book_id: str,
        offset: int,
        excerpt: str,
        note: str = "",
    ) -> BookRecord:
        book = self.resolve_book(book_id)
        total_chars = max(book.total_chars, 0)
        clamped_offset = min(max(offset, 0), total_chars)
        excerpt_text = excerpt.strip() or "(empty page)"
        bookmark = BookmarkRecord(
            id=uuid.uuid4().hex,
            offset=clamped_offset,
            created_at=utc_now_iso(),
            excerpt=excerpt_text[:240],
            note=note.strip()[:120],
        )
        book.bookmarks.append(bookmark)
        book.bookmarks.sort(key=lambda item: (item.offset, item.created_at))
        book.updated_at = utc_now_iso()
        self.save()
        return book

    def set_language(self, language: str) -> str:
        """Update and persist the global UI language."""

        normalized = normalize_language(language)
        if normalized not in SUPPORTED_LANGUAGES:
            raise ReaderError(f"Unsupported language: {language}")
        self.settings.language = normalized
        self.save()
        return normalized

    def save_2048_state(
        self,
        board: list[list[int]],
        score: int,
        *,
        won: bool = False,
        game_over: bool = False,
    ) -> Game2048Record:
        """Persist the current 2048 board and score."""

        normalized_board = _normalize_2048_board(board)
        self.game_2048.board = normalized_board
        self.game_2048.score = max(0, int(score))
        self.game_2048.best_score = max(self.game_2048.best_score, self.game_2048.score)
        self.game_2048.won = bool(won)
        self.game_2048.game_over = bool(game_over)
        self.game_2048.updated_at = utc_now_iso()
        self.save()
        return self.game_2048

    def clear_2048_state(self) -> Game2048Record:
        """Clear the resumable 2048 board while keeping the best score."""

        self.game_2048 = Game2048Record(
            best_score=self.game_2048.best_score,
            updated_at=utc_now_iso(),
        )
        self.save()
        return self.game_2048

    def save_gomoku_state(
        self,
        board: list[list[str]],
        *,
        cursor_row: int,
        cursor_col: int,
        winner: str = "",
        game_over: bool = False,
    ) -> GameGomokuRecord:
        """Persist the current Gomoku board and cursor state."""

        normalized_board = _normalize_gomoku_board(board)
        self.game_gomoku.board = normalized_board
        self.game_gomoku.cursor_row = max(0, min(GAME_GOMOKU_BOARD_SIZE - 1, int(cursor_row)))
        self.game_gomoku.cursor_col = max(0, min(GAME_GOMOKU_BOARD_SIZE - 1, int(cursor_col)))
        normalized_winner = str(winner)
        self.game_gomoku.winner = normalized_winner if normalized_winner in {"", "human", "ai", "draw"} else ""
        self.game_gomoku.game_over = bool(game_over)
        self.game_gomoku.updated_at = utc_now_iso()
        self.save()
        return self.game_gomoku

    def clear_gomoku_state(self) -> GameGomokuRecord:
        """Clear the resumable Gomoku board."""

        self.game_gomoku = GameGomokuRecord(updated_at=utc_now_iso())
        self.save()
        return self.game_gomoku

    def save_snake_state(
        self,
        snake: list[tuple[int, int]] | list[list[int]],
        rocks: list[tuple[int, int]] | list[list[int]],
        score: int,
        *,
        food_row: int,
        food_col: int,
        direction: str,
        speed: str,
        difficulty: str,
        game_over: bool = False,
    ) -> GameSnakeRecord:
        """Persist the current Snake body, direction, and score."""

        normalized_snake = _normalize_snake_body(snake)
        normalized_rocks = _normalize_snake_points(rocks)
        self.game_snake.snake = normalized_snake
        self.game_snake.rocks = normalized_rocks
        self.game_snake.score = max(0, int(score))
        self.game_snake.best_score = max(self.game_snake.best_score, self.game_snake.score)
        self.game_snake.food_row = max(0, min(GAME_SNAKE_ROWS - 1, int(food_row)))
        self.game_snake.food_col = max(0, min(GAME_SNAKE_COLS - 1, int(food_col)))
        normalized_direction = str(direction)
        self.game_snake.direction = normalized_direction if normalized_direction in {"up", "down", "left", "right"} else "right"
        normalized_speed = str(speed)
        self.game_snake.speed = normalized_speed if normalized_speed in {"slow", "normal", "fast"} else "normal"
        normalized_difficulty = str(difficulty)
        self.game_snake.difficulty = (
            normalized_difficulty if normalized_difficulty in {"easy", "normal", "hard"} else "normal"
        )
        self.game_snake.game_over = bool(game_over)
        self.game_snake.updated_at = utc_now_iso()
        self.save()
        return self.game_snake

    def clear_snake_state(self) -> GameSnakeRecord:
        """Clear the resumable Snake board while keeping the best score."""

        self.game_snake = GameSnakeRecord(
            best_score=self.game_snake.best_score,
            speed=self.game_snake.speed,
            difficulty=self.game_snake.difficulty,
            updated_at=utc_now_iso(),
        )
        self.save()
        return self.game_snake
