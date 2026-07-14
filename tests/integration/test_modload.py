from __future__ import annotations

import json
from pathlib import Path

from dst_lua_lab.cli import PROJECT_ROOT, file_sha256, launch_worker
from dst_lua_lab.config import EXIT_MISSING_NATIVE, EXIT_OK, RunConfig


SCRIPTS_ZIP = PROJECT_ROOT / ".pytest-generated" / "scripts.zip"


def test_minimal_mod_loads_with_require_cache_hooks_and_rpc(tmp_path: Path) -> None:
    mod = tmp_path / "workshop-123"
    scripts = mod / "scripts"
    scripts.mkdir(parents=True)
    (mod / "modinfo.lua").write_text('name = "DST Lab Fixture"\nversion = "1.0.0"\n', "utf-8")
    (mod / "modmain.lua").write_text(
        """
local first = require("helper")
local second = require("helper")
assert(first == second)
modimport("scripts/imported.lua")
assert(IMPORTED_VALUE == 9)
assert(type(Class) == "function")
local FixtureClass = Class(function(self) self.value = 17 end)
assert(FixtureClass().value == 17)
AddPrefabPostInit("fixture_prefab", function(inst) end)
AddModRPCHandler("dstlab", "ping", function(player, value) end)
""",
        "utf-8",
    )
    (scripts / "helper.lua").write_text("return { value = 42 }\n", "utf-8")
    (scripts / "imported.lua").write_text("IMPORTED_VALUE = 9\n", "utf-8")
    before = {path: file_sha256(path) for path in mod.rglob("*.lua")}

    code, report = launch_worker(
        RunConfig(profile="modload", scripts_zip=str(SCRIPTS_ZIP), mod=str(mod)),
        10,
    )
    assert code == EXIT_OK
    result = json.loads((report / "result.json").read_text("utf-8"))
    assert result["modules_loaded"] == 2  # official class + target helper
    assert result["hooks_registered"] == 1
    assert result["rpc_registered"] == 1
    modules = json.loads((report / "modules.json").read_text("utf-8"))
    assert [item["request"] for item in modules] == ["class", "helper"]
    assert before == {path: file_sha256(path) for path in mod.rglob("*.lua")}


def make_mod(tmp_path: Path, modmain: str) -> Path:
    mod = tmp_path / "workshop-native"
    mod.mkdir()
    (mod / "modinfo.lua").write_text('name = "Native Fixture"\n', "utf-8")
    (mod / "modmain.lua").write_text(modmain, "utf-8")
    return mod


def test_persistence_is_captured_without_real_save_write(tmp_path: Path) -> None:
    mod = make_mod(tmp_path, 'TheSim:SetPersistentString("lab_data", "A\\0B", false, function(ok) assert(ok) end)\n')
    code, report = launch_worker(RunConfig(profile="modload", scripts_zip=str(SCRIPTS_ZIP), mod=str(mod)), 10)
    assert code == EXIT_OK
    writes = json.loads((report / "persistence.json").read_text("utf-8"))
    assert writes[0]["operation"] == "write"
    assert writes[0]["data"]["hex"] == "410042"


def test_modload_receives_deterministic_worker_fixtures(tmp_path: Path) -> None:
    mod = make_mod(
        tmp_path,
        '''
assert(DSTLAB_USERID == "KU_SYNTHETIC")
assert(DSTLAB_FIXED_TIME == "2088-02-03T04:05:06Z")
assert(DSTLAB_SEED == 9876)
assert(GLOBAL.DSTLAB_USERID == DSTLAB_USERID)
''',
    )
    code, _report = launch_worker(
        RunConfig(
            profile="modload",
            scripts_zip=str(SCRIPTS_ZIP),
            mod=str(mod),
            userid="KU_SYNTHETIC",
            fixed_time="2088-02-03T04:05:06Z",
            seed=9876,
        ),
        10,
    )
    assert code == EXIT_OK


def test_mod_config_uses_defaults_declared_by_modinfo(tmp_path: Path) -> None:
    mod = make_mod(
        tmp_path,
        '''
assert(GetModConfigData("enabled") == true)
assert(GetModConfigData("amount") == 2.5)
assert(GetModConfigData("missing") == nil)
''',
    )
    (mod / "modinfo.lua").write_text(
        '''
name = "Config fixture"
configuration_options = {
    { name = "enabled", default = true },
    { name = "amount", default = 2.5 },
}
''',
        "utf-8",
    )
    code, report = launch_worker(
        RunConfig(profile="modload", scripts_zip=str(SCRIPTS_ZIP), mod=str(mod)),
        10,
    )
    assert code == EXIT_OK
    captured = json.loads((report / "mod_config.json").read_text("utf-8"))
    assert captured == {
        "source": "modinfo.default",
        "values": {"amount": 2.5, "enabled": True},
    }


def test_missing_native_fails_strictly_and_is_reported(tmp_path: Path) -> None:
    mod = make_mod(tmp_path, "TheSim:DefinitelyNotImplemented(123)\n")
    code, report = launch_worker(RunConfig(profile="modload", scripts_zip=str(SCRIPTS_ZIP), mod=str(mod)), 10)
    assert code == EXIT_MISSING_NATIVE
    unsupported = json.loads((report / "unsupported.json").read_text("utf-8"))
    assert unsupported[0]["api"] == "TheSim.DefinitelyNotImplemented"
    assert "recommendation" in unsupported[0]


def test_common_registration_surface_is_captured_without_running_callbacks(tmp_path: Path) -> None:
    mod = make_mod(
        tmp_path,
        r'''
local callback_ran = false
local asset = Asset("ANIM", "anim/fixture.zip")
assert(asset.type == "ANIM" and asset.file == "anim/fixture.zip")
local prefab = Prefab("fixture_prefab", function() callback_ran = true end, {asset}, {"dep"})
assert(prefab.name == "fixture_prefab")
local recipe2 = AddRecipe2("fixture_recipe2", {}, nil, {}, {"TOOLS"})
local recipe1 = AddRecipe("fixture_recipe1", {}, nil, nil)
assert(AllRecipes.fixture_recipe2 == recipe2)
assert(AllRecipes.fixture_recipe1 == recipe1)
local action = AddAction("FIXTURE_ACTION", "Fixture", function() callback_ran = true end)
assert(ACTIONS.FIXTURE_ACTION == action)
AddComponentAction("SCENE", "fixture_component", function() callback_ran = true end)
AddStategraph("wilson", {}, {}, {})
AddStategraphState("wilson", {name = "fixture_idle"})
AddStategraphEventHandler("wilson", {name = "fixture_attacked"})
AddPrefabPostInitAny(function() callback_ran = true end)
AddGamePostInit(function() callback_ran = true end)
AddWorldPostInit(function() callback_ran = true end)
AddRecipePostInit("fixture_recipe2", function() callback_ran = true end)
AddStategraphPostInit("wilson", function() callback_ran = true end)
AddBrainPostInit("fixture_brain", function() callback_ran = true end)
AddUserCommand("fixture_command", {prettyname = "Fixture"})
assert(not callback_ran)
''',
    )
    code, report = launch_worker(
        RunConfig(profile="modload", scripts_zip=str(SCRIPTS_ZIP), mod=str(mod)), 10
    )
    assert code == EXIT_OK
    registrations = json.loads((report / "registrations.json").read_text("utf-8"))
    assert len(registrations) == 16
    assert all(item["effect"] == "captured_only" for item in registrations)
    assert all(item["callback_executed"] is False for item in registrations)
    by_api = {item["api"]: item for item in registrations}
    assert by_api["Asset"]["asset_type"] == "ANIM"
    assert by_api["Asset"]["target"] == "anim/fixture.zip"
    assert by_api["AddComponentAction"]["action_type"] == "SCENE"
    assert by_api["AddComponentAction"]["target"] == "fixture_component"
    assert by_api["AddStategraphState"]["target"] == "wilson"
    assert by_api["AddUserCommand"]["target"] == "fixture_command"
    result = json.loads((report / "result.json").read_text("utf-8"))
    assert result["registrations_captured"] == 16
