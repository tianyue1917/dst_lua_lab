from __future__ import annotations

from pathlib import Path

from .base import Mount, Resolution, make_uri, normalize_path


class DirectoryMount(Mount):
    def __init__(
        self,
        root: str | Path,
        *,
        name: str = "directory",
        uri_root: str = "file://",
        case_sensitive: bool = True,
    ) -> None:
        super().__init__(name=name, uri_root=uri_root, case_sensitive=case_sensitive)
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise NotADirectoryError(self.root)
        self._casefold_index: dict[str, str] | None = None

    def _display_path(self, path: str) -> str | None:
        normalized = normalize_path(path)
        if self.case_sensitive:
            return normalized
        if self._casefold_index is None:
            index: dict[str, str] = {}
            for item in self.root.rglob("*"):
                if item.is_file():
                    relative = item.relative_to(self.root).as_posix()
                    index.setdefault(relative.casefold(), relative)
            self._casefold_index = index
        return self._casefold_index.get(normalized.casefold())

    def read(self, path: str) -> Resolution | None:
        display_path = self._display_path(path)
        if display_path is None:
            return None
        candidate = (self.root / display_path).resolve()
        # This also blocks directory symlinks that lead outside the mount.
        if not candidate.is_relative_to(self.root) or not candidate.is_file():
            return None
        data = candidate.read_bytes()
        return Resolution.from_bytes(
            uri=make_uri(self.uri_root, display_path),
            display_path=display_path,
            data=data,
            mount_name=self.name,
        )
