from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Generator

from app.utils.file_entry import FileEntry


class LocalFileClient:
    """Local-directory adapter with the same interface as SMBClient/SFTPClient."""

    def __init__(self, base_path: str):
        raw = (base_path or "").strip().strip('"').strip("'")
        if not raw:
            raise ValueError("Local folder path is required")
        self.base_path = Path(raw).expanduser()

    def connect(self) -> None:
        if not self.base_path.exists():
            raise FileNotFoundError(f"Local folder does not exist: {self.base_path}")
        if not self.base_path.is_dir():
            raise NotADirectoryError(f"Local path is not a folder: {self.base_path}")

    def disconnect(self) -> None:
        return None

    def test_connection(self) -> bool:
        try:
            self.connect()
            next(self.base_path.iterdir(), None)
            return True
        except (OSError, ValueError):
            return False

    def walk(self, allowed_extensions: set[str] | None = None) -> Generator[FileEntry, None, None]:
        self.connect()
        for path in sorted(self.base_path.rglob("*"), key=lambda item: str(item).lower()):
            try:
                if not path.is_file():
                    continue
                ext = path.suffix.lstrip(".").lower()
                if allowed_extensions and ext not in allowed_extensions:
                    continue
                stat = path.stat()
                yield FileEntry(
                    rel_path=str(path.relative_to(self.base_path)),
                    full_path=str(path),
                    size=int(stat.st_size),
                    mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                )
            except OSError:
                continue

    def read_bytes(self, local_path: str) -> bytes:
        path = Path(local_path).resolve()
        base = self.base_path.resolve()
        try:
            path.relative_to(base)
        except ValueError as exc:
            raise ValueError(f"Path is outside the configured local folder: {path}") from exc
        return path.read_bytes()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.disconnect()
