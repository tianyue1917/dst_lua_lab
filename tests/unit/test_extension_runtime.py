from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest

from dst_lua_lab.extension_runtime import (
    ExtensionContext,
    ExtensionRuntimeError,
    ExtensionSession,
)


def _plan_item(root: Path, extension_id: str, *, dependencies: list[str] | None = None) -> dict[str, object]:
    manifest = root / "module.toml"
    return {
        "id": extension_id,
        "api_version": "1",
        "root": str(root.resolve()),
        "manifest_path": str(manifest.resolve()),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest().upper(),
        "entry_path": str((root / "plugin.py").resolve()),
        "entry_sha256": hashlib.sha256((root / "plugin.py").read_bytes()).hexdigest().upper(),
        "dependencies": dependencies or [],
        "profiles": ["algorithm"],
    }


def _module(tmp_path: Path, extension_id: str, plugin: str = "def register(context):\n    pass\n") -> Path:
    root = tmp_path / extension_id
    root.mkdir()
    (root / "module.toml").write_text(f'id = "{extension_id}"\n', "utf-8")
    (root / "plugin.py").write_text(plugin, "utf-8")
    return root


@pytest.mark.parametrize("extension_id", ["1first", "with.dot", "with-dash"])
def test_runtime_accepts_the_manifest_identifier_language(tmp_path: Path, extension_id: str) -> None:
    root = _module(tmp_path, extension_id)
    session = ExtensionSession.from_plan(
        {"modules": [_plan_item(root, extension_id)]}, profile="algorithm"
    )
    assert session.loaded_extensions[0]["id"] == extension_id


def test_runtime_rejects_extension_profile_mismatch(tmp_path: Path) -> None:
    root = _module(tmp_path, "profile_test")
    item = _plan_item(root, "profile_test")
    item["profiles"] = ["modload"]
    with pytest.raises(ExtensionRuntimeError, match="does not support profile"):
        ExtensionSession.from_plan({"modules": [item]}, profile="algorithm")


def test_global_names_and_scoped_reads_are_restricted(tmp_path: Path) -> None:
    root = _module(
        tmp_path,
        "scope_test",
        "def register(context):\n"
        "    context.register_global('bad.name', 1)\n",
    )
    with pytest.raises(ExtensionRuntimeError, match="invalid Lua global"):
        ExtensionSession.from_plan({"modules": [_plan_item(root, "scope_test")]}, profile="algorithm")

    (root / "plugin.py").write_text(
        "def register(context):\n    context.read_bytes('../outside.bin')\n", "utf-8"
    )
    item = _plan_item(root, "scope_test")
    with pytest.raises(ExtensionRuntimeError, match="escapes its root"):
        ExtensionSession.from_plan({"modules": [item]}, profile="algorithm")


def test_manifest_change_after_planning_is_rejected(tmp_path: Path) -> None:
    root = _module(tmp_path, "tamper_test")
    item = _plan_item(root, "tamper_test")
    (root / "module.toml").write_text('id = "tampered"\n', "utf-8")
    with pytest.raises(ExtensionRuntimeError, match="manifest changed after planning"):
        ExtensionSession.from_plan({"modules": [item]}, profile="algorithm")


def test_entry_does_not_pollute_sys_path(tmp_path: Path) -> None:
    root = _module(
        tmp_path,
        "path_test",
        "import sys\n"
        "def register(context):\n"
        "    sys.path.append('EXTENSION_SENTINEL')\n",
    )
    before = list(sys.path)
    ExtensionSession.from_plan({"modules": [_plan_item(root, "path_test")]}, profile="algorithm")
    assert sys.path == before


def test_extension_config_view_cannot_mutate_shared_session(tmp_path: Path) -> None:
    session = ExtensionSession(
        profile="algorithm", config={"nested": {"value": 1}}
    )
    context = ExtensionContext(
        "config_test", "module", tmp_path, "1", "algorithm", session
    )
    view = context.config
    with pytest.raises(TypeError):
        view["new"] = True  # type: ignore[index]
    view["nested"]["value"] = 2
    assert context.config["nested"]["value"] == 1
