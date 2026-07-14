from __future__ import annotations

from pathlib import Path
from zipfile import BadZipFile, ZipFile

from .base import InvalidVfsPath, Mount, Resolution, make_uri, normalize_path


class ZipMount(Mount):
    def __init__(
        self,
        archive: str | Path,
        *,
        prefix: str = "",
        name: str = "zip",
        uri_root: str = "zip://",
        case_sensitive: bool = True,
    ) -> None:
        super().__init__(name=name, uri_root=uri_root, case_sensitive=case_sensitive)
        self.archive = Path(archive).resolve()
        if not self.archive.is_file():
            raise FileNotFoundError(self.archive)
        self.prefix = "" if not prefix else normalize_path(prefix).rstrip("/") + "/"
        self._entries: dict[str, tuple[str, str]] = {}
        try:
            with ZipFile(self.archive) as zf:
                for info in zf.infolist():
                    if info.is_dir():
                        continue
                    try:
                        archive_name = normalize_path(info.filename)
                    except InvalidVfsPath:
                        # Malformed/malicious members are never addressable.
                        continue
                    if self.prefix and not archive_name.startswith(self.prefix):
                        continue
                    display_path = archive_name[len(self.prefix) :]
                    key = display_path if case_sensitive else display_path.casefold()
                    self._entries.setdefault(key, (info.filename, display_path))
        except BadZipFile:
            raise

    def read(self, path: str) -> Resolution | None:
        normalized = normalize_path(path)
        key = normalized if self.case_sensitive else normalized.casefold()
        entry = self._entries.get(key)
        if entry is None:
            return None
        archive_name, display_path = entry
        with ZipFile(self.archive) as zf:
            data = zf.read(archive_name)
        return Resolution.from_bytes(
            uri=make_uri(self.uri_root, display_path),
            display_path=display_path,
            data=data,
            mount_name=self.name,
        )
