from __future__ import annotations

import pytest

from dst_lua_lab.patches import PatchManifest, sort_patches


def manifest(identifier: str, *, dependencies: list[str] | None = None, conflicts: list[str] | None = None):
    return PatchManifest(1, identifier, "1.0.0", dependencies=dependencies or [], conflicts=conflicts or [])


def test_patch_dependencies_sort_before_dependents() -> None:
    ordered = sort_patches([manifest("child", dependencies=["base"]), manifest("base")])
    assert [item.id for item in ordered] == ["base", "child"]


def test_patch_cycle_is_rejected() -> None:
    with pytest.raises(ValueError, match="cycle"):
        sort_patches([manifest("a", dependencies=["b"]), manifest("b", dependencies=["a"])])


def test_patch_conflict_is_rejected() -> None:
    with pytest.raises(ValueError, match="conflict"):
        sort_patches([manifest("a", conflicts=["b"]), manifest("b")])
