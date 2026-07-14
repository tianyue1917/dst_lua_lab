from __future__ import annotations

from pathlib import Path

import pytest

from dst_lua_lab.settings import LabSettings, SettingsError, SettingsStore


def test_settings_round_trip_and_clear(tmp_path: Path) -> None:
    archive = tmp_path / "scripts.zip"
    archive.write_bytes(b"fixture")
    store = SettingsStore(tmp_path / "lab")

    assert store.load() == LabSettings()
    saved = store.set_scripts_zip(archive)
    assert saved.scripts_zip == str(archive.resolve())
    assert store.load() == saved

    assert store.clear_scripts_zip() == LabSettings()
    assert store.load() == LabSettings()


def test_settings_reject_missing_archive(tmp_path: Path) -> None:
    with pytest.raises(SettingsError, match="missing or not a file"):
        SettingsStore(tmp_path / "lab").set_scripts_zip(tmp_path / "missing.zip")


def test_settings_reject_symlinked_state_directory(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (lab / ".dstlab").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")
    archive = tmp_path / "scripts.zip"
    archive.write_bytes(b"fixture")
    with pytest.raises(SettingsError, match="symlinks or reparse"):
        SettingsStore(lab).load()
    with pytest.raises(SettingsError, match="symlinks or reparse"):
        SettingsStore(lab).set_scripts_zip(archive)


@pytest.mark.parametrize(
    "payload, message",
    [
        ("schema = 2\n", "unsupported settings schema"),
        ("schema = 1\nunknown = true\n", "unknown settings fields"),
        ("schema = 1\nscripts_zip = ''\n", "non-empty string"),
    ],
)
def test_settings_reject_malformed_content(
    tmp_path: Path, payload: str, message: str
) -> None:
    store = SettingsStore(tmp_path)
    store.directory.mkdir()
    store.path.write_text(payload, "utf-8")
    with pytest.raises(SettingsError, match=message):
        store.load()
