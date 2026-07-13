from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_MEDIA_EXTENSIONS = frozenset(
    {
        ".jpg",
        ".jpeg",
        ".png",
        ".webp",
        ".gif",
        ".heic",
        ".avif",
        ".mp4",
        ".mkv",
        ".webm",
        ".mov",
        ".m4v",
        ".mp3",
        ".m4a",
        ".aac",
        ".wav",
        ".flac",
    }
)


@dataclass(frozen=True)
class FileVerification:
    files: tuple[str, ...]
    total_bytes: int
    rejected: tuple[str, ...] = ()

    @property
    def count(self) -> int:
        return len(self.files)

    @property
    def ok(self) -> bool:
        return self.count > 0 and self.total_bytes > 0

    def summary(self) -> str:
        return f"已确认 {self.count} 个文件，共 {self.total_bytes} 字节"


def verify_files(
    paths: Iterable[str | Path],
    *,
    allowed_extensions: Iterable[str] | None = None,
    min_files: int = 1,
) -> FileVerification:
    allowed = {
        str(value).lower() if str(value).startswith(".") else f".{str(value).lower()}"
        for value in (allowed_extensions or DEFAULT_MEDIA_EXTENSIONS)
    }
    verified: list[str] = []
    rejected: list[str] = []
    total_bytes = 0
    seen: set[str] = set()
    for raw_path in paths:
        path = Path(raw_path)
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        try:
            size = path.stat().st_size
            if not path.is_file() or size <= 0 or path.suffix.lower() not in allowed:
                rejected.append(key)
                continue
        except OSError:
            rejected.append(key)
            continue
        verified.append(key)
        total_bytes += size
    result = FileVerification(tuple(verified), total_bytes, tuple(rejected))
    if result.count < max(1, int(min_files)):
        return FileVerification((), 0, tuple([*result.rejected, *result.files]))
    return result


def verify_recent_files(
    root: str | Path,
    *,
    since_epoch: float,
    allowed_extensions: Iterable[str] | None = None,
    max_files: int = 200,
) -> FileVerification:
    base = Path(root)
    if not base.exists() or not base.is_dir():
        return FileVerification((), 0)
    candidates: list[Path] = []
    try:
        for path in base.rglob("*"):
            if len(candidates) >= max(1, int(max_files)):
                break
            try:
                if path.is_file() and path.stat().st_mtime >= since_epoch - 1:
                    candidates.append(path)
            except OSError:
                continue
    except OSError:
        return FileVerification((), 0)
    return verify_files(candidates, allowed_extensions=allowed_extensions)
