"""Setuptools build hooks for immutable built-in extension data.

The canonical extension sources remain in the repository-level ``modules``
and ``casepacks`` directories.  A wheel build stages a filtered copy inside
the Python package without requiring a second, generated source tree in Git.
"""

from __future__ import annotations

import os
import shutil
import stat
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py as _build_py


PROJECT_ROOT = Path(__file__).resolve().parent
COLLECTIONS = ("modules", "casepacks")


def _ignore_generated(_directory: str, names: list[str]) -> set[str]:
    ignored = {"tests", "__pycache__"}.intersection(names)
    ignored.update(
        name
        for name in names
        if name.endswith((".pyc", ".pyo")) or name in {".pytest_cache", ".dstlab"}
    )
    return ignored


def _assert_plain_tree(root: Path) -> None:
    root_info = root.lstat()
    root_attributes = getattr(root_info, "st_file_attributes", 0)
    if root.is_symlink() or bool(
        root_attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    ):
        raise RuntimeError(
            f"built-in extension root cannot be a symlink or reparse point: {root}"
        )
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            item = Path(current) / name
            info = item.lstat()
            attributes = getattr(info, "st_file_attributes", 0)
            is_reparse = item.is_symlink() or bool(
                attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
            )
            if is_reparse:
                raise RuntimeError(
                    f"built-in extension tree cannot contain symlinks or reparse points: {item}"
                )
            if not item.is_file() and not item.is_dir():
                raise RuntimeError(
                    f"unsupported file type in built-in extension tree: {item}"
                )


class build_py(_build_py):
    """Stage repository extension trees as wheel package data."""

    def run(self) -> None:
        super().run()
        # PEP 660 editable installs already execute directly from the checkout,
        # where the canonical top-level trees are available.
        if getattr(self, "editable_mode", False):
            return

        destination_root = Path(self.build_lib) / "dst_lua_lab" / "_bundled"
        shutil.rmtree(destination_root, ignore_errors=True)
        for collection in COLLECTIONS:
            source = PROJECT_ROOT / collection
            if not source.is_dir():
                raise RuntimeError(f"missing built-in extension collection: {source}")
            _assert_plain_tree(source)
            shutil.copytree(
                source,
                destination_root / collection,
                ignore=_ignore_generated,
            )


setup(cmdclass={"build_py": build_py})
