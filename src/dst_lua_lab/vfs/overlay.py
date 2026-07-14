from __future__ import annotations

from collections.abc import Mapping

from .base import Mount, Resolution, make_uri, normalize_path


class OverlayMount(Mount):
    """An in-memory, non-persistent mount used by patches and individual runs."""

    def __init__(
        self,
        files: Mapping[str, bytes | bytearray | memoryview | str] | None = None,
        *,
        name: str = "overlay",
        uri_root: str = "overlay://",
        case_sensitive: bool = True,
    ) -> None:
        super().__init__(name=name, uri_root=uri_root, case_sensitive=case_sensitive)
        self._files: dict[str, tuple[str, bytes]] = {}
        for path, data in (files or {}).items():
            self.write(path, data)

    def write(self, path: str, data: bytes | bytearray | memoryview | str) -> None:
        display_path = normalize_path(path)
        source = data.encode("utf-8") if isinstance(data, str) else bytes(data)
        key = display_path if self.case_sensitive else display_path.casefold()
        self._files[key] = (display_path, source)

    def remove(self, path: str) -> None:
        normalized = normalize_path(path)
        key = normalized if self.case_sensitive else normalized.casefold()
        self._files.pop(key, None)

    def read(self, path: str) -> Resolution | None:
        normalized = normalize_path(path)
        key = normalized if self.case_sensitive else normalized.casefold()
        entry = self._files.get(key)
        if entry is None:
            return None
        display_path, data = entry
        return Resolution.from_bytes(
            uri=make_uri(self.uri_root, display_path),
            display_path=display_path,
            data=data,
            mount_name=self.name,
        )
