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
    ) -> None:
        self.books: list[BookRecord] = books or []
        self.settings = settings or AppSettings()

    @classmethod
    def load(cls) -> "Library":
        state_path = get_state_path()
        if not state_path.exists():
            return cls()

        payload = json.loads(state_path.read_text(encoding="utf-8"))
        books = [BookRecord.from_dict(book) for book in payload.get("books", [])]
        settings_payload = payload.get("settings", {})
        settings = AppSettings(
            language=normalize_language(settings_payload.get("language")),
        )
        return cls(books, settings=settings)

    def save(self) -> None:
        ensure_app_home()
        payload = {
            "schema_version": 1,
            "settings": asdict(self.settings),
            "books": [book.to_dict() for book in self.books],
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
