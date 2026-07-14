from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

from dst_lua_lab.runtime import RuntimeAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODULE_ROOT = PROJECT_ROOT / "modules" / "controlled_replay"
FIXTURE = PROJECT_ROOT / "tests" / "fixtures" / "mods" / "controlled_replay" / "modmain.lua"


def _load_plugin():
    spec = importlib.util.spec_from_file_location(
        "controlled_replay_plugin", MODULE_ROOT / "plugin.py"
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _to_lua(lua: Any, value: Any) -> Any:
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, list):
        table = lua.table()
        for index, item in enumerate(value, 1):
            table[index] = _to_lua(lua, item)
        return table
    if isinstance(value, dict):
        table = lua.table()
        for key, item in value.items():
            table[key.encode("utf-8")] = _to_lua(lua, item)
        return table
    return value


LUA_BASELINE = br"""
GLOBAL = _G
env = _G
local next_guid = 100
local Entity = {}
Entity.__index = Entity
function Entity:AddTag(tag) self.tags[tag] = true end
function Entity:HasTag(tag) return self.tags[tag] == true end
function Entity:AddComponent(name)
    local component = { inst = self }
    self.components[name] = component
    return component
end
function Entity:AddTransform()
    local transform = {}
    function transform:SetPosition(x, y, z) self.position = {x, y, z} end
    self.Transform = transform
    return transform
end
function CreateEntity()
    next_guid = next_guid + 1
    return setmetatable({GUID=next_guid, tags={}, components={}}, Entity)
end
function Prefab(name, fn, assets, deps) return {name=name, fn=fn, assets=assets or {}, deps=deps or {}} end
function AddPrefabPostInit(...) end
function AddComponentPostInit(...) end
function AddModRPCHandler(...) return {kind="server"} end
function AddClientModRPCHandler(...) return {kind="client"} end
function AddShardModRPCHandler(...) return {kind="shard"} end
function State(data) return data end
function StateGraph(name, states) return {name=name, states=states or {}} end
function AddStategraph(...) end
function AddStategraphState(...) end
"""


def _runtime(plan: list[dict[str, Any]]):
    lua = RuntimeAdapter("lua51").create()
    lua.execute(LUA_BASELINE)
    globals_ = lua.globals()
    events: list[tuple[str, tuple[Any, ...]]] = []

    def native(api: Any, *args: Any) -> None:
        name = api.decode("utf-8") if isinstance(api, bytes) else str(api)
        events.append((name, args))

    globals_[b"DSTLAB_NATIVE"] = native
    globals_[b"DSTLAB_REPLAY_PLAN"] = _to_lua(lua, plan)
    runner = lua.execute((MODULE_ROOT / "lua" / "capture.lua").read_bytes())
    assert callable(runner)
    return lua, events, runner


def test_empty_plan_captures_registrations_but_never_executes_callbacks() -> None:
    lua, events, runner = _runtime([])
    lua.execute(FIXTURE.read_bytes())
    runner()
    counters = lua.execute(
        b"return DSTLAB_REPLAY_FIXTURE.prefab_postinit, "
        b"DSTLAB_REPLAY_FIXTURE.component_postinit, "
        b"DSTLAB_REPLAY_FIXTURE.prefab_constructor, "
        b"DSTLAB_REPLAY_FIXTURE.mod_rpc, DSTLAB_REPLAY_FIXTURE.stategraph_state"
    )
    assert counters == (0, 0, 0, 0, 0)
    operations = [args[0] for api, args in events if api == "DSTLab.ControlledReplay.Event"]
    assert operations
    assert set(operations) == {b"capture"}


def test_explicit_plan_replays_each_supported_callback_against_fixtures() -> None:
    plan = [
        {"kind": "prefab_postinit", "target": "dstlab_replay_prefab", "strict": True},
        {"kind": "component_postinit", "target": "dstlab_replay_component", "strict": True},
        {"kind": "prefab_constructor", "target": "dstlab_replay_prefab", "strict": True},
        {
            "kind": "mod_rpc",
            "rpc_type": "server",
            "namespace": "dstlab_replay",
            "name": "ping",
            "args": ["fixture_payload"],
            "strict": True,
        },
        {
            "kind": "stategraph_state",
            "stategraph": "dstlab_replay_graph",
            "state": "dstlab_replay_idle",
            "callback": "onenter",
            "args": [{"source": "fixture"}],
            "strict": True,
        },
    ]
    lua, events, runner = _runtime(plan)
    lua.execute(FIXTURE.read_bytes())
    assert lua.globals()[b"DSTLAB_CONTROLLED_REPLAY_RUN"] is None
    lua.execute(b"DSTLAB_NATIVE=nil; GLOBAL.xpcall=nil")
    runner()
    counters = lua.execute(
        b"return DSTLAB_REPLAY_FIXTURE.prefab_postinit, "
        b"DSTLAB_REPLAY_FIXTURE.component_postinit, "
        b"DSTLAB_REPLAY_FIXTURE.prefab_constructor, "
        b"DSTLAB_REPLAY_FIXTURE.mod_rpc, DSTLAB_REPLAY_FIXTURE.stategraph_state"
    )
    assert counters == (1, 1, 1, 1, 1)
    callback_statuses = [
        args[3]
        for api, args in events
        if api == "DSTLab.ControlledReplay.Event" and args[0] == b"callback"
    ]
    assert callback_statuses == [b"executed"] * 5


def test_strict_missing_registration_records_failure_then_raises() -> None:
    lua, events, runner = _runtime(
        [{"kind": "prefab_postinit", "target": "missing_prefab", "strict": True}]
    )
    with pytest.raises(Exception, match="strict item 1 failed"):
        runner()
    assert any(
        api == "DSTLab.ControlledReplay.Event"
        and args[0] == b"item"
        and args[3] == b"failed"
        for api, args in events
    )


def test_plugin_registers_exact_bridges_and_summarizes_events() -> None:
    module = _load_plugin()

    class Context:
        config = {
            "replay_plan": [
                {"kind": "prefab_constructor", "target": "fixture", "strict": True}
            ]
        }

        def __init__(self) -> None:
            self.globals = {}
            self.bootstraps = []

        def register_global(self, name, value): self.globals[name] = value
        def register_lua_bootstrap(self, phase, path): self.bootstraps.append((phase, path))
        def register_native(self, api, handler): self.native = (api, handler)
        def register_after_run(self, handler): self.after = handler

    context = Context()
    module.register(context)
    emitted = []

    class Call:
        args = (b"callback", 1, b"prefab_constructor", b"executed", b"fixture", b"constructor", b"return_type=table")

        def emit(self, event_type, source, effect, **data):
            emitted.append((event_type, source, effect, data))

    context.native[1](Call())
    summary = context.after({"status": "ok"})
    assert context.globals["DSTLAB_REPLAY_PLAN"][0]["target"] == "fixture"
    assert context.bootstraps == [
        ("pre_mod", "lua/capture.lua"),
    ]
    assert context.native[0] == "DSTLab.ControlledReplay.Event"
    assert summary["callbacks_executed"] == 1
    assert summary["strict_items"] == 1
    assert summary["network_access"] is False
    assert emitted[0][:3] == ("replay.callback", "FIXTURE", "EXECUTED")


def test_plugin_rejects_non_explicit_or_malformed_plans() -> None:
    module = _load_plugin()

    class Context:
        def __init__(self, plan): self.config = {"replay_plan": plan}

    with pytest.raises(ValueError, match="JSON array"):
        module.register(Context({"kind": "prefab_constructor"}))
    with pytest.raises(ValueError, match="must be one of"):
        module.register(Context([{"kind": "unknown", "target": "fixture"}]))


def test_private_runner_is_single_use() -> None:
    _lua, _events, runner = _runtime([])
    assert runner() == 0
    with pytest.raises(Exception, match="already consumed"):
        runner()


def test_private_runner_uses_captured_fixture_constructor() -> None:
    lua, _events, runner = _runtime(
        [
            {
                "kind": "prefab_postinit",
                "target": "dstlab_replay_prefab",
                "strict": True,
            }
        ]
    )
    lua.execute(FIXTURE.read_bytes())
    lua.execute(b"CreateEntity=nil")
    assert runner() == 1
