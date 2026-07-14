from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from zipfile import ZipFile

import pytest

from dst_lua_lab.vfs import (
    DirectoryMount,
    InvalidVfsPath,
    OverlayMount,
    OverlayVFS,
    ZipMount,
    build_default_vfs,
    normalize_path,
)


def test_normalize_uses_forward_slashes_and_blocks_escape() -> None:
    assert normalize_path(r"scripts\widgets\foo.lua") == "scripts/widgets/foo.lua"
    assert normalize_path("scripts//./class.lua") == "scripts/class.lua"
    for unsafe in ("/etc/passwd", r"C:\Windows\win.ini", "../secret", "a/../../secret", r"\\server\share\x"):
        with pytest.raises(InvalidVfsPath):
            normalize_path(unsafe)


def test_directory_mount_returns_bytes_uri_and_hash(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    source = root / "scripts" / "hello.lua"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"return 'directory'\n")
    mount = DirectoryMount(root, name="target_mod", uri_root="mod://123")

    result = mount.read(r"scripts\hello.lua")
    assert result is not None
    assert result.data == b"return 'directory'\n"
    assert result.source_bytes == result.data
    assert result.uri == "mod://123/scripts/hello.lua"
    assert result.display_path == "scripts/hello.lua"
    assert result.sha256 == sha256(result.data).hexdigest()
    assert result.mount_name == "target_mod"


def test_directory_mount_does_not_follow_symlink_outside_root(tmp_path: Path) -> None:
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "outside.lua"
    outside.write_text("secret", encoding="utf-8")
    link = root / "linked.lua"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks are unavailable for this user")
    assert DirectoryMount(root).read("linked.lua") is None


def test_zip_mount_reads_scripts_class_lua(tmp_path: Path) -> None:
    archive = tmp_path / "scripts.zip"
    class_lua = b"local Class = {}\nreturn Class\n"
    with ZipFile(archive, "w") as zf:
        zf.writestr("scripts/class.lua", class_lua)
        zf.writestr("scripts/widgets/sample.lua", b"return {}")

    result = ZipMount(archive, name="dst_scripts", uri_root="dst://").read("scripts/class.lua")
    assert result is not None
    assert result.data == class_lua
    assert result.uri == "dst://scripts/class.lua"
    assert result.sha256 == sha256(class_lua).hexdigest()


def test_overlay_and_resolver_priority(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    root.mkdir()
    (root / "same.lua").write_bytes(b"directory")
    vfs = OverlayVFS()
    vfs.add_mount(DirectoryMount(root, name="mod", uri_root="mod://x"), priority=10)
    vfs.add_mount(OverlayMount({"same.lua": b"patch"}, name="patch", uri_root="patch://p"), priority=20)
    vfs.add_mount(OverlayMount({"same.lua": b"run"}, name="run", uri_root="work://r"), priority=30)

    result = vfs.resolve("same.lua", caller="modmain.lua:7")
    assert result.data == b"run"
    assert result.mount_name == "run"
    assert result.caller == "modmain.lua:7"


def test_build_default_vfs_and_read_module(tmp_path: Path) -> None:
    archive = tmp_path / "scripts.zip"
    with ZipFile(archive, "w") as zf:
        zf.writestr("scripts/class.lua", b"dst class")
    dependency = tmp_path / "dependency"
    (dependency / "scripts").mkdir(parents=True)
    (dependency / "scripts" / "shared.lua").write_bytes(b"dependency")
    mod = tmp_path / "123456"
    (mod / "scripts").mkdir(parents=True)
    (mod / "scripts" / "class.lua").write_bytes(b"mod class")

    vfs = build_default_vfs(archive, mod, [dependency])
    class_result = vfs.read_module("class", caller="modmain.lua:1")
    assert class_result.data == b"mod class"
    assert class_result.uri == "mod://123456/scripts/class.lua"
    assert class_result.request == "class"
    assert class_result.caller == "modmain.lua:1"
    assert vfs.read_module("shared").data == b"dependency"
    assert vfs.read_module("scripts/class.lua").data == b"mod class"


def test_overlay_does_not_modify_backing_directory(tmp_path: Path) -> None:
    root = tmp_path / "mod"
    root.mkdir()
    original = root / "file.lua"
    original.write_bytes(b"original")
    overlay = OverlayMount({"file.lua": b"changed"})
    assert overlay.read("file.lua").data == b"changed"  # type: ignore[union-attr]
    assert original.read_bytes() == b"original"
