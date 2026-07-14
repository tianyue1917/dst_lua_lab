from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .base import Mount, Resolution, VfsFileNotFound, normalize_path
from .directory import DirectoryMount
from .zip_mount import ZipMount


class OverlayVFS:
    """Priority-ordered collection of mounts.

    Larger priority numbers win. Equal-priority mounts preserve insertion
    order, which keeps explicitly configured dependency ordering reproducible.
    """

    def __init__(self, mounts: list[Mount] | tuple[Mount, ...] | None = None) -> None:
        self._mounts: list[tuple[int, int, Mount]] = []
        self._sequence = 0
        for mount in mounts or ():
            self.add_mount(mount)

    @property
    def mounts(self) -> tuple[Mount, ...]:
        return tuple(item[2] for item in sorted(self._mounts, key=lambda x: (-x[0], x[1])))

    def add_mount(self, mount: Mount, priority: int = 0) -> Mount:
        self._mounts.append((priority, self._sequence, mount))
        self._sequence += 1
        return mount

    mount = add_mount

    def resolve(self, path: str, *, caller: str | None = None) -> Resolution:
        normalized = normalize_path(path)
        for mount in self.mounts:
            result = mount.read(normalized)
            if result is not None:
                return replace(result, request=path, caller=caller)
        raise VfsFileNotFound(f"VFS file not found: {path!r}")

    def read(self, path: str, *, caller: str | None = None) -> Resolution:
        return self.resolve(path, caller=caller)

    def read_bytes(self, path: str) -> bytes:
        return self.resolve(path).data

    def read_module(self, request: str, caller: str | None = None) -> Resolution:
        """Resolve a DST/Lua module request without applying require caching."""

        module_path = request
        if not request.endswith(".lua") and "/" not in request and "\\" not in request:
            module_path = request.replace(".", "/")
        normalized = normalize_path(module_path)
        if normalized.endswith(".lua"):
            stems = [normalized]
        else:
            stems = [f"{normalized}.lua", f"{normalized}/init.lua"]
        candidates: list[str] = []
        for stem in stems:
            candidates.append(stem)
            if not stem.startswith("scripts/"):
                candidates.append(f"scripts/{stem}")
        for candidate in candidates:
            try:
                result = self.resolve(candidate, caller=caller)
                return replace(result, request=request)
            except VfsFileNotFound:
                pass
        raise VfsFileNotFound(
            f"Lua module not found: {request!r}; tried {', '.join(candidates)}"
        )


Resolver = OverlayVFS
VFSResolver = OverlayVFS


def build_default_vfs(
    scripts_zip: Path | None,
    mod: Path | None,
    dependencies: list[Path],
) -> OverlayVFS:
    vfs = OverlayVFS()
    if scripts_zip is not None:
        vfs.add_mount(
            ZipMount(scripts_zip, name="dst_scripts", uri_root="dst://"),
            priority=0,
        )
    # The first explicitly listed dependency has the highest dependency priority.
    for index, dependency in enumerate(dependencies):
        vfs.add_mount(
            DirectoryMount(
                dependency,
                name=f"dependency_{index}",
                uri_root=f"dep://{index}",
            ),
            priority=100 - index,
        )
    if mod is not None:
        mod_path = Path(mod)
        vfs.add_mount(
            DirectoryMount(mod_path, name="target_mod", uri_root=f"mod://{mod_path.name}"),
            priority=200,
        )
    return vfs
