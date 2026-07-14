from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from hashlib import sha256
import re


class VfsError(Exception):
    """Base class for virtual filesystem errors."""


class InvalidVfsPath(VfsError, ValueError):
    """Raised when a request is absolute or can escape a mount root."""


class VfsFileNotFound(VfsError, FileNotFoundError):
    """Raised when no mounted source contains a requested file."""


_WINDOWS_DRIVE = re.compile(r"^[A-Za-z]:($|/)")


def normalize_path(path: str) -> str:
    """Return a safe, relative VFS path using forward slashes.

    VFS callers must never be able to address the host filesystem directly.
    Rejecting every ``..`` component (rather than resolving benign-looking
    pairs) also makes audit logs unambiguous.
    """

    if not isinstance(path, str):
        raise TypeError("VFS path must be a string")
    if "\x00" in path:
        raise InvalidVfsPath("VFS path contains a NUL byte")
    value = path.replace("\\", "/")
    if value.startswith("/") or _WINDOWS_DRIVE.match(value):
        raise InvalidVfsPath(f"absolute VFS path is forbidden: {path!r}")

    parts: list[str] = []
    for part in value.split("/"):
        if part in ("", "."):
            continue
        if part == "..":
            raise InvalidVfsPath(f"parent traversal is forbidden: {path!r}")
        parts.append(part)
    if not parts:
        raise InvalidVfsPath("VFS path is empty")
    return "/".join(parts)


def make_uri(uri_root: str, display_path: str) -> str:
    separator = "" if uri_root.endswith("/") else "/"
    return f"{uri_root}{separator}{display_path.lstrip('/')}"


@dataclass(frozen=True, slots=True)
class Resolution:
    """The exact bytes selected by VFS resolution and their provenance."""

    uri: str
    display_path: str
    data: bytes
    sha256: str
    mount_name: str
    request: str | None = None
    caller: str | None = None

    @classmethod
    def from_bytes(
        cls,
        *,
        uri: str,
        display_path: str,
        data: bytes,
        mount_name: str,
        request: str | None = None,
        caller: str | None = None,
    ) -> "Resolution":
        source = bytes(data)
        return cls(
            uri=uri,
            display_path=display_path,
            data=source,
            sha256=sha256(source).hexdigest(),
            mount_name=mount_name,
            request=request,
            caller=caller,
        )

    @property
    def source_bytes(self) -> bytes:
        return self.data

    @property
    def source(self) -> bytes:
        return self.data

    @property
    def mount(self) -> str:
        return self.mount_name


class Mount(ABC):
    def __init__(self, *, name: str, uri_root: str, case_sensitive: bool = True) -> None:
        self.name = name
        self.uri_root = uri_root
        self.case_sensitive = case_sensitive

    @abstractmethod
    def read(self, path: str) -> Resolution | None:
        """Read *path*, returning None if this mount does not contain it."""

    def exists(self, path: str) -> bool:
        return self.read(path) is not None
