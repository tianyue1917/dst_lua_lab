from __future__ import annotations

from pathlib import Path

import pytest

from dst_lua_lab.state import ExtensionState, StateError, StateStore


def test_state_store_rejects_path_outside_lab_root(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    with pytest.raises(StateError, match="inside Lab root"):
        StateStore(lab, path=tmp_path / "outside.json")


def test_state_store_rejects_symlinked_state_directory(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (lab / ".dstlab").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    store = StateStore(lab)
    with pytest.raises(StateError, match="symlinks or reparse"):
        store.load()
    with pytest.raises(StateError, match="symlinks or reparse"):
        store.save(ExtensionState(enabled_modules=("example_trace",)))
    assert not (outside / "state.json").exists()
