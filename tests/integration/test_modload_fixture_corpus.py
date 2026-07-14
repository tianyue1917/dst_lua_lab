from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

import pytest

from dst_lua_lab.cli import PROJECT_ROOT, launch_worker
from dst_lua_lab.config import EXIT_LUA_ERROR, EXIT_MISSING_NATIVE, EXIT_OK, RunConfig
from dst_lua_lab.planner import ExtensionPlanner
from dst_lua_lab.registry import ExtensionRegistry
from dst_lua_lab.state import ExtensionState


SCRIPTS_ZIP = PROJECT_ROOT / ".pytest-generated" / "scripts.zip"
FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "mods"


def _optional_path(variable: str) -> Path | None:
    value = os.environ.get(variable)
    return Path(value).expanduser().resolve() if value else None


SMOKE_MOD = _optional_path("DSTLAB_SMOKE_MOD")
SMOKE_SCRIPTS_ZIP = _optional_path("DSTLAB_SCRIPTS_ZIP")


def _tree_hash(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _lua_tree_hash(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*.lua"))
        if path.is_file()
    }


def _extension_plan(
    *module_ids: str, case_id: str | None = None
) -> dict[str, Any]:
    catalog = ExtensionRegistry(PROJECT_ROOT).discover()
    plan = ExtensionPlanner(catalog, ExtensionState()).resolve(
        case_id=case_id,
        requested_modules=list(module_ids)
    ).to_dict()
    # The planner's first milestone emitted management-only plans. Explicitly
    # opt this integration run into execution while retaining the exact roots,
    # hashes, dependency order, and entry paths selected by the planner.
    plan["management_only"] = False
    return plan


def _run_fixture(
    fixture: str,
    *,
    modules: tuple[str, ...] = (),
    dependencies: tuple[Path, ...] = (),
    case_id: str | None = None,
) -> tuple[int, Path, Path]:
    plan = (
        _extension_plan(*modules, case_id=case_id)
        if modules or case_id is not None
        else {}
    )
    config = RunConfig(
        profile="modload",
        scripts_zip=str(SCRIPTS_ZIP),
        mod=str(FIXTURE_ROOT / fixture),
        dependencies=[str(path) for path in dependencies],
        requested_modules=list(modules),
        extension_plan=plan,
        management_only=not bool(modules or case_id),
        case_id=case_id,
    )
    code, report = launch_worker(config, 10)
    return code, report, Path(config.work_dir)


def _read_json(report: Path, name: str) -> Any:
    return json.loads((report / name).read_text("utf-8"))


def _extension_output(report: Path, module_id: str) -> dict[str, Any]:
    artifact = report / "extensions.json"
    assert artifact.is_file(), "Worker did not emit the executable extension report"
    extensions = _read_json(report, "extensions.json")
    for item in extensions.get("after_run_outputs", []):
        if item.get("extension_id") == module_id:
            value = item.get("value")
            assert isinstance(value, dict)
            return value
    pytest.fail(f"missing after-run output for extension {module_id!r}")


def _cleanup(report: Path, work: Path) -> None:
    shutil.rmtree(report, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)


def test_fixture_corpus_is_synthetic_and_self_contained() -> None:
    expected = {
        "basic_hooks_rpc",
        "persistence",
        "scheduler_entity",
        "strict_env",
        "cross_mod_target",
        "cross_mod_dependency",
        "prefab_asset",
        "recipe_action_stategraph",
        "world_entity_rpc",
    }
    assert expected <= {path.name for path in FIXTURE_ROOT.iterdir() if path.is_dir()}
    combined = b"\n".join(path.read_bytes() for path in FIXTURE_ROOT.rglob("*.lua"))
    assert b"KU_" not in combined
    assert b"workshop-" not in combined.lower()
    assert b"http://" not in combined.lower()
    assert b"https://" not in combined.lower()


def test_basic_hook_rpc_fixture_loads_without_mutating_source() -> None:
    fixture = FIXTURE_ROOT / "basic_hooks_rpc"
    before = _tree_hash(fixture)
    code, report, work = _run_fixture("basic_hooks_rpc")
    try:
        assert code == EXIT_OK
        result = _read_json(report, "result.json")
        assert result["hooks_registered"] == 4
        assert result["rpc_registered"] == 3
        modules = _read_json(report, "modules.json")
        assert [item["request"] for item in modules] == ["class", "fixture.helper"]
        assert before == _tree_hash(fixture)
    finally:
        _cleanup(report, work)


def test_rpc_capture_reports_registration_without_network_access() -> None:
    code, report, work = _run_fixture("basic_hooks_rpc", modules=("rpc_capture",))
    try:
        summary = _extension_output(report, "rpc_capture")
        assert code == EXIT_OK
        assert summary["registrations"] == 3
        assert summary["sends"] == 4
        assert summary["network_access"] is False
        assert sum(summary["kinds"].values()) == 7
    finally:
        _cleanup(report, work)


def test_persistence_fixture_is_captured_without_real_save_access() -> None:
    code, report, work = _run_fixture("persistence")
    try:
        assert code == EXIT_OK
        operations = _read_json(report, "persistence.json")
        assert [item["operation"] for item in operations] == ["read", "write"]
        assert operations[1]["data"]["hex"] == "66697874757265007061796c6f6164"
    finally:
        _cleanup(report, work)


def test_persistence_module_uses_only_isolated_memory() -> None:
    code, report, work = _run_fixture(
        "persistence", modules=("persistence_trace",)
    )
    try:
        summary = _extension_output(report, "persistence_trace")
        assert code == EXIT_OK
        assert summary == {
            "reads": 1,
            "writes": 1,
            "erases": 0,
            "keys_in_fixture": 1,
            "backend": "isolated_memory",
            "real_save_access": False,
        }
    finally:
        _cleanup(report, work)


def test_cross_mod_require_resolves_declared_dependency_and_caches_result() -> None:
    dependency = FIXTURE_ROOT / "cross_mod_dependency"
    code, report, work = _run_fixture(
        "cross_mod_target", dependencies=(dependency,)
    )
    try:
        assert code == EXIT_OK
        modules = _read_json(report, "modules.json")
        assert [item["request"] for item in modules] == ["class", "shared.fixture"]
        shared = modules[1]
        assert shared["mount"] == "dependency_0"
        assert shared["uri"].startswith("dep://0/")
    finally:
        _cleanup(report, work)


def test_strict_env_denies_selected_bare_globals_but_preserves_global() -> None:
    code, report, work = _run_fixture("strict_env", modules=("strict_env",))
    try:
        summary = _extension_output(report, "strict_env")
        assert code == EXIT_OK
        assert summary["denied_mod_globals"] == ["pcall", "xpcall"]
        assert summary["global_table_preserved"] is True
    finally:
        _cleanup(report, work)


def test_scheduler_runs_entity_tasks_on_virtual_time_only() -> None:
    code, report, work = _run_fixture(
        "scheduler_entity", modules=("scheduler_trace",)
    )
    try:
        summary = _extension_output(report, "scheduler_trace")
        assert code == EXIT_OK
        assert summary["clock"] == "virtual"
        assert summary["wall_clock_access"] is False
        assert summary["events"] == {
            "cancel": 2,
            "run": 3,
            "schedule": 2,
            "schedule_periodic": 1,
        }
        hooks = _read_json(report, "hooks.json")
        assert any(item["kind"] == "AddPrefabPostInit" for item in hooks)
    finally:
        _cleanup(report, work)


def test_general_mod_debug_case_includes_runtime_baseline() -> None:
    plan = _extension_plan(case_id="general_mod_debug")
    assert plan["case"]["id"] == "general_mod_debug"
    assert plan["dependency_order"] == [
        "dst_runtime_baseline",
        "strict_env",
        "rpc_capture",
        "persistence_trace",
        "scheduler_trace",
    ]


def test_prefab_asset_constructor_runs_against_shape_fixture() -> None:
    code, report, work = _run_fixture(
        "prefab_asset", case_id="general_mod_debug"
    )
    try:
        assert code == EXIT_OK
        summary = _extension_output(report, "dst_runtime_baseline")
        assert summary["backend"] == "lua_shape_fixture"
        assert summary["real_engine"] is False
        assert summary["events"]["entity.CreateEntity"] == 1
        assert summary["events"]["entity.AddTransform"] == 1
        assert summary["events"]["entity.AddAnimState"] == 1
        assert summary["events"]["entity.AddNetwork"] == 1
        assert summary["events"]["network.SetPristine"] == 1
        registrations = _read_json(report, "registrations.json")
        assert sum(item["api"] == "Asset" for item in registrations) == 4
        assert sum(item["api"] == "Prefab" for item in registrations) == 1
        assert all(item["effect"] == "captured_only" for item in registrations)
        assert all(item["callback_executed"] is False for item in registrations)
        assert _read_json(report, "unsupported.json") == []
    finally:
        _cleanup(report, work)


def test_recipe_action_stategraph_captures_declarations_without_callbacks() -> None:
    code, report, work = _run_fixture(
        "recipe_action_stategraph", case_id="general_mod_debug"
    )
    try:
        assert code == EXIT_OK
        summary = _extension_output(report, "dst_runtime_baseline")
        assert summary["events"]["construct.Ingredient"] == 2
        assert summary["events"]["construct.Recipe"] == 1
        assert summary["events"]["construct.Action"] == 1
        assert summary["events"]["construct.State"] == 1
        assert summary["events"]["construct.StateGraph"] == 1
        assert summary["events"]["construct.EventHandler"] == 1
        assert summary["events"]["construct.TimeEvent"] == 1
        assert summary["events"]["construct.ActionHandler"] == 1

        registrations = _read_json(report, "registrations.json")
        by_api = {item["api"]: item for item in registrations}
        assert set(by_api) == {
            "AddRecipe2",
            "AddAction",
            "AddComponentAction",
            "AddStategraph",
            "AddStategraphState",
            "AddStategraphEventHandler",
        }
        assert all(item["effect"] == "captured_only" for item in registrations)
        assert all(item["callback_executed"] is False for item in registrations)
        assert by_api["AddRecipe2"]["return_contract"] == "descriptor"
        assert (
            by_api["AddStategraphState"]["member"]["text_preview"]
            == "dstlab_idle"
        )
    finally:
        _cleanup(report, work)


def test_world_entity_and_rpc_identity_are_offline_and_traceable() -> None:
    code, report, work = _run_fixture(
        "world_entity_rpc", case_id="general_mod_debug"
    )
    try:
        assert code == EXIT_OK
        runtime = _extension_output(report, "dst_runtime_baseline")
        rpc = _extension_output(report, "rpc_capture")
        assert runtime["real_engine"] is False
        assert runtime["events"]["world.AddTag"] == 1
        assert runtime["events"]["entity.CreateEntity"] == 2
        assert runtime["events"]["entity.SpawnPrefab"] == 1
        assert runtime["events"]["entity.ListenForEvent"] == 1
        assert runtime["events"]["entity.PushEvent"] == 1
        assert runtime["events"]["rpc_identity.register"] == 3
        assert runtime["events"]["rpc_identity.get"] == 3
        assert rpc["registrations"] == 3
        assert rpc["sends"] == 4
        assert rpc["network_access"] is False
        assert _read_json(report, "unsupported.json") == []
    finally:
        _cleanup(report, work)


def test_runtime_baseline_preserves_unknown_thenet_native_failure() -> None:
    code, report, work = _run_fixture(
        "world_unknown_native", case_id="general_mod_debug"
    )
    try:
        assert code == EXIT_MISSING_NATIVE
        unsupported = _read_json(report, "unsupported.json")
        assert [item["api"] for item in unsupported] == [
            "TheNet.DefinitelyMissingFromFixture"
        ]
        assert "verified Native Shim" in unsupported[0]["recommendation"]
    finally:
        _cleanup(report, work)


def test_runtime_baseline_scopes_io_to_read_only_mod_roots() -> None:
    fixture = FIXTURE_ROOT / "scoped_io"
    before = _tree_hash(fixture)
    code, report, work = _run_fixture("scoped_io", case_id="general_mod_debug")
    try:
        assert code == EXIT_OK
        runtime = _extension_output(report, "dst_runtime_baseline")
        assert runtime["events"]["file.read"] == 1
        assert not (fixture / "forbidden.txt").exists()
        assert before == _tree_hash(fixture)
    finally:
        _cleanup(report, work)


@pytest.mark.skipif(
    SMOKE_MOD is None
    or SMOKE_SCRIPTS_ZIP is None
    or not (SMOKE_MOD / "modmain.lua").is_file()
    or not SMOKE_SCRIPTS_ZIP.is_file(),
    reason="set DSTLAB_SMOKE_MOD and DSTLAB_SCRIPTS_ZIP for the optional local smoke test",
)
def test_existing_mod_entry_smoke_is_read_only_and_reports_earliest_gap() -> None:
    assert SMOKE_MOD is not None
    assert SMOKE_SCRIPTS_ZIP is not None
    mod = SMOKE_MOD
    before = _lua_tree_hash(mod)
    plan = _extension_plan(case_id="general_mod_debug")
    config = RunConfig(
        profile="modload",
        scripts_zip=str(SMOKE_SCRIPTS_ZIP),
        mod=str(mod),
        case_id="general_mod_debug",
        extension_plan=plan,
        management_only=False,
    )
    code, report = launch_worker(config, 30)
    work = Path(config.work_dir)
    try:
        # A smoke run may stop at a truthful Lua/native compatibility gap, but
        # it must never fail as an internal/config/timeout error.
        assert code in {EXIT_OK, EXIT_LUA_ERROR, EXIT_MISSING_NATIVE}
        result = _read_json(report, "result.json")
        loaded = {
            item["id"] for item in result["extensions"]["loaded_extensions"]
        }
        assert "dst_runtime_baseline" in loaded
        assert "rpc_capture" in loaded
        assert "persistence_trace" in loaded
        assert report.parent.name == "general_mod_debug"
        assert _read_json(report, "persistence.json") == []
        trace_text = (report / "trace.jsonl").read_text("utf-8")
        assert '"type": "mod.entry"' in trace_text
        assert before == _lua_tree_hash(mod)
    finally:
        _cleanup(report, work)
