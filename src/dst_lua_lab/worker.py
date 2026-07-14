from __future__ import annotations

import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .config import EXIT_CONFIG_ERROR, EXIT_INTERNAL, EXIT_LUA_ERROR, EXIT_MISSING_NATIVE, EXIT_OK, RunConfig
from .extension_runtime import ExtensionRuntimeError, ExtensionSession, NativeCallContext
from .runtime import RuntimeAdapter
from .trace import TraceRecorder, safe_value, sha256_bytes
from .vfs import VfsFileNotFound, build_default_vfs


CAPTURE_BOOTSTRAP = br"""
return function(capture, fixed_epoch)
    local original_load = load
    local original_loadstring = loadstring
    if original_loadstring then
        loadstring = function(source, chunkname)
            capture("loadstring", source, chunkname or "=(loadstring)")
            return original_loadstring(source, chunkname)
        end
    end
    if original_load then
        load = function(source, chunkname, mode, env)
            if type(source) == "string" then
                capture("load", source, chunkname or "=(load)")
            end
            return original_load(source, chunkname, mode, env)
        end
    end
    local original_date = os.date
    os.time = function(_) return fixed_epoch end
    os.date = function(format, time)
        return original_date(format, time or fixed_epoch)
    end
    os.execute = nil
    os.remove = nil
    os.rename = nil
    os.tmpname = nil
    os.getenv = nil
    io.popen = nil
    io.open = nil
    io.input = nil
    io.output = nil
    package.loadlib = nil
    package.path = ""
    package.cpath = ""
    require = function(name)
        error("UNSUPPORTED require outside VFS: " .. tostring(name), 2)
    end
    dofile = nil
    loadfile = function(path)
        error("UNSUPPORTED loadfile outside VFS: " .. tostring(path), 2)
    end
end
"""


SECURITY_BOOTSTRAP = br"""
return function(fixed_epoch)
    local original_date = os.date
    os.time = function(_) return fixed_epoch end
    os.date = function(format, time) return original_date(format, time or fixed_epoch) end
    os.execute = nil
    os.remove = nil
    os.rename = nil
    os.tmpname = nil
    os.getenv = nil
    io.popen = nil
    io.open = nil
    io.input = nil
    io.output = nil
    package.loadlib = nil
    package.path = ""
    package.cpath = ""
    dofile = nil
    loadfile = nil
end
"""


class MissingNativeRunError(RuntimeError):
    pass


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def _lua_value(lua: Any, value: Any) -> Any:
    """Convert JSON-safe host data for an encoding=None Lua runtime."""
    if isinstance(value, str):
        return value.encode("utf-8")
    if isinstance(value, list):
        table = lua.table()
        for index, item in enumerate(value, 1):
            table[index] = _lua_value(lua, item)
        return table
    if isinstance(value, dict):
        table = lua.table()
        for key, item in value.items():
            table[str(key).encode("utf-8")] = _lua_value(lua, item)
        return table
    return value


def _apply_extension_globals(lua: Any, globals_: Any, session: ExtensionSession) -> None:
    for name, value in session.globals.items():
        globals_[name.encode("utf-8")] = _lua_value(lua, value)


def _run_extension_bootstraps(
    lua: Any,
    session: ExtensionSession,
    phase: str,
    trace: TraceRecorder,
    executor: Any | None = None,
) -> None:
    for bootstrap in session.bootstraps(phase):
        trace.emit(
            "extension.bootstrap",
            "EXTENSION",
            "EXECUTED",
            extension_id=bootstrap.extension_id,
            phase=phase,
            path=str(bootstrap.path),
            sha256=sha256_bytes(bootstrap.data),
        )
        result = (
            lua.execute(bootstrap.data)
            if executor is None
            else executor(bootstrap.data, ("@extension:" + str(bootstrap.path)).encode("utf-8"))
        )
        if callable(result):
            result()


def _extension_native_dispatch(
    session: ExtensionSession,
    trace: TraceRecorder,
    profile: str,
    api: str,
    args: tuple[Any, ...],
) -> tuple[bool, Any]:
    handler = session.native_handlers.get(api)
    if handler is None:
        return False, None
    owner = session.native_owners[api]
    trace.emit(
        "extension.native_call",
        "EXTENSION",
        "EXECUTED",
        extension_id=owner,
        api=api,
        args=args,
    )
    call = NativeCallContext(api=api, profile=profile, args=args, _emit=trace.emit)
    try:
        return True, handler(call)
    except Exception as exc:
        raise ExtensionRuntimeError(
            f"native handler for {api} from {owner} failed: {type(exc).__name__}: {exc}"
        ) from exc


def run_algorithm(config: RunConfig, trace: TraceRecorder, session: ExtensionSession) -> dict[str, Any]:
    lua = RuntimeAdapter(config.runtime).create()
    runtime_metadata = RuntimeAdapter.metadata(lua)
    report_dir = Path(config.report_dir)
    chunks_dir = report_dir / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)
    chunk_count = 0

    def capture(kind: bytes, source: bytes, chunkname: bytes) -> None:
        nonlocal chunk_count
        chunk_count += 1
        digest = sha256_bytes(source)
        path = chunks_dir / f"{chunk_count:03d}-{digest}.bin"
        path.write_bytes(source)
        trace.emit(
            "dynamic_chunk.capture",
            "MOD_REAL",
            "CAPTURED",
            kind=kind,
            chunkname=chunkname,
            length=len(source),
            sha256=digest,
            artifact=str(path),
        )

    fixed_epoch = int(datetime.fromisoformat(config.fixed_time.replace("Z", "+00:00")).timestamp())
    lua.execute(CAPTURE_BOOTSTRAP)(capture, fixed_epoch)
    globals_ = lua.globals()
    globals_[b"DSTLAB_USERID"] = config.userid.encode("utf-8")
    globals_[b"DSTLAB_FIXED_TIME"] = config.fixed_time.encode("utf-8")
    globals_[b"DSTLAB_SEED"] = config.seed
    _apply_extension_globals(lua, globals_, session)

    def extension_native(name: Any, *args: Any) -> Any:
        api = name.decode("utf-8", "replace") if isinstance(name, bytes) else str(name)
        handled, value = _extension_native_dispatch(session, trace, "algorithm", api, args)
        if not handled:
            raise RuntimeError(f"MissingNativeAPI: {api} in profile algorithm")
        return _lua_value(lua, value)

    def observe_rpc(operation: Any, kind: Any, *args: Any) -> None:
        event = {
            "operation": operation.decode("utf-8", "replace") if isinstance(operation, bytes) else str(operation),
            "kind": kind.decode("utf-8", "replace") if isinstance(kind, bytes) else str(kind),
            "args": safe_value(args),
            "profile": "algorithm",
        }
        session.notify_rpc(event)

    globals_[b"DSTLAB_NATIVE"] = extension_native
    globals_[b"DSTLAB_RPC_OBSERVE"] = observe_rpc
    _run_extension_bootstraps(lua, session, "pre_runtime", trace)
    lua.execute(f"math.randomseed({config.seed})".encode("ascii"))

    if config.entry:
        source = Path(config.entry).read_bytes()
        display = config.entry
    elif config.source is not None:
        source = config.source.encode("utf-8")
        display = "=(cli-source)"
    else:
        raise ValueError("algorithm profile requires --entry or --source")

    digest = sha256_bytes(source)
    trace.emit("chunk.execute", "MOD_REAL", "EXECUTED", path=display, sha256=digest, length=len(source))
    result = lua.execute(source)
    _run_extension_bootstraps(lua, session, "post_mod", trace)
    return {
        "status": "ok",
        "runtime": config.runtime,
        "runtime_metadata": runtime_metadata,
        "entry": display,
        "entry_sha256": digest,
        "result": safe_value(result),
        "dynamic_chunks": chunk_count,
        "management_only": False,
        "extensions_loaded": len(session.loaded_extensions),
        "fixtures": {
            "userid": config.userid,
            "fixed_time": config.fixed_time,
            "seed": config.seed,
        },
    }


CHUNK_RUNNER = br"""
return function(source, chunkname, environment)
    local loader, err = loadstring(source, chunkname)
    if not loader then error(err, 0) end
    setfenv(loader, environment)
    return loader()
end
"""


ENV_FACTORY = br"""
return function(global_table)
    local environment = {}
    local denied = {}
    setmetatable(environment, {
        __index = function(_, key)
            if denied[key] then return nil end
            return global_table[key]
        end
    })
    environment.GLOBAL = global_table
    environment.env = environment
    return environment, function(key)
        denied[key] = true
        rawset(environment, key, nil)
    end
end
"""


def run_modload(config: RunConfig, trace: TraceRecorder, session: ExtensionSession) -> dict[str, Any]:
    if not config.mod or not config.scripts_zip:
        raise ValueError("modload profile requires --mod and --scripts-zip")
    lua = RuntimeAdapter(config.runtime).create()
    runtime_metadata = RuntimeAdapter.metadata(lua)
    fixed_epoch = int(datetime.fromisoformat(config.fixed_time.replace("Z", "+00:00")).timestamp())
    lua.execute(SECURITY_BOOTSTRAP)(fixed_epoch)
    globals_ = lua.globals()
    runner = lua.execute(CHUNK_RUNNER)
    make_env = lua.execute(ENV_FACTORY)
    mod_env, deny_mod_global = make_env(globals_)
    vfs = build_default_vfs(Path(config.scripts_zip), Path(config.mod), [Path(p) for p in config.dependencies])
    modules: list[dict[str, Any]] = []
    hooks: list[dict[str, Any]] = []
    rpc: list[dict[str, Any]] = []
    persistence: list[dict[str, Any]] = []
    native_calls: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    registrations: list[dict[str, Any]] = []
    mod_config_defaults: dict[str, Any] = {}
    loaded: dict[str, Any] = {}
    loading: set[str] = set()

    def text(value: Any) -> str:
        return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)

    def require_module(request: Any) -> Any:
        name = text(request)
        if name in loaded:
            trace.emit("module.cache_hit", "DST_LUA_REAL", "EXECUTED", request=name)
            return loaded[name]
        if name in loading:
            raise RuntimeError(f"circular require: {name}")
        loading.add(name)
        try:
            resolution = vfs.read_module(name, caller="require")
            environment = globals_ if resolution.mount_name == "dst_scripts" else mod_env
            trace.emit(
                "module.resolve",
                "DST_LUA_REAL" if resolution.mount_name == "dst_scripts" else "MOD_REAL",
                "EXECUTED",
                request=name,
                uri=resolution.uri,
                sha256=resolution.sha256,
                mount=resolution.mount_name,
            )
            result = runner(resolution.data, ("@" + resolution.uri).encode("utf-8"), environment)
            if result is None:
                result = True
            loaded[name] = result
            modules.append(
                {"request": name, "uri": resolution.uri, "sha256": resolution.sha256, "mount": resolution.mount_name}
            )
            return result
        finally:
            loading.discard(name)

    def modimport(request: Any) -> Any:
        name = text(request)
        try:
            resolution = vfs.resolve(name, caller="modimport")
        except VfsFileNotFound:
            resolution = vfs.resolve(name + ("" if name.endswith(".lua") else ".lua"), caller="modimport")
        trace.emit("module.modimport", "MOD_REAL", "EXECUTED", request=name, uri=resolution.uri, sha256=resolution.sha256)
        return runner(resolution.data, ("@" + resolution.uri).encode("utf-8"), mod_env)

    def get_config(name: Any, *_: Any) -> Any:
        config_name = text(name)
        value = mod_config_defaults.get(config_name)
        trace.emit(
            "fixture.mod_config",
            "FIXTURE",
            "CAPTURED",
            name=config_name,
            value=safe_value(value),
            config_source="modinfo.default" if config_name in mod_config_defaults else "missing",
        )
        return value

    def lua_field(value: Any, name: str) -> Any:
        try:
            return value[name.encode("utf-8")]
        except Exception:
            try:
                return value[name]
            except Exception:
                return None

    def capture_mod_config_defaults() -> None:
        options = mod_env[b"configuration_options"]
        if options is None:
            return
        try:
            entries = list(options.items())
        except Exception as exc:
            raise RuntimeError("modinfo configuration_options is not a Lua table") from exc
        for _, option in entries:
            name = lua_field(option, "name")
            if not isinstance(name, (bytes, str)):
                continue
            mod_config_defaults[text(name)] = lua_field(option, "default")

    def registration_target(api: str, args: tuple[Any, ...]) -> tuple[Any, dict[str, Any]]:
        first = text(args[0]) if args and isinstance(args[0], (bytes, str)) else None
        details: dict[str, Any] = {}
        if api == "Asset":
            details["asset_type"] = first
            return text(args[1]) if len(args) > 1 else None, details
        if api == "AddComponentAction":
            details["action_type"] = first
            return text(args[1]) if len(args) > 1 else None, details
        if api in ("AddStategraphState", "AddStategraphEventHandler"):
            nested = lua_field(args[1], "name") if len(args) > 1 else None
            details["member"] = safe_value(nested)
            return first, details
        return first, details

    def descriptor(api: str, args: tuple[Any, ...]) -> Any:
        value = lua.table()
        value[b"dstlab_descriptor"] = True
        value[b"api"] = api.encode("utf-8")
        if args:
            value[b"name"] = args[0]
            value[b"id"] = args[0]
        if api == "Asset":
            if len(args) > 1:
                value[b"file"] = args[1]
            value[b"type"] = args[0] if args else None
            if len(args) > 2:
                value[b"param"] = args[2]
        elif api == "Prefab":
            for index, key in enumerate((b"name", b"fn", b"assets", b"deps")):
                if len(args) > index:
                    value[key] = args[index]
        elif api in ("AddRecipe", "AddRecipe2"):
            value[b"product"] = args[0] if args else None
        elif api == "AddAction":
            for index, key in enumerate((b"id", b"str", b"fn")):
                if len(args) > index:
                    value[key] = args[index]
        return value

    def capture_registration(api: str, category: str, args: tuple[Any, ...], *, returns: str = "none") -> Any:
        target, details = registration_target(api, args)
        item = {
            "seq": len(registrations) + 1,
            "api": api,
            "category": category,
            "target": target,
            "args": safe_value(args),
            "callback_executed": False,
            "effect": "captured_only",
            "return_contract": returns,
            **details,
        }
        registrations.append(item)
        trace.emit(
            "registration.capture",
            "MOD_REAL",
            "CAPTURED",
            **{key: value for key, value in item.items() if key != "effect"},
        )
        if returns == "descriptor":
            result = descriptor(api, args)
            if api == "AddAction" and args:
                globals_[b"ACTIONS"][args[0]] = result
            elif api in ("AddRecipe", "AddRecipe2") and args:
                globals_[b"AllRecipes"][args[0]] = result
            return result
        return None

    def register(kind: str, category: str = "hook"):
        def handler(*args: Any) -> None:
            item = {"kind": kind, "args": safe_value(args)}
            (rpc if "RPC" in kind else hooks).append(item)
            trace.emit("rpc.register" if "RPC" in kind else "hook.register", "MOD_REAL", "CAPTURED", **item)
            capture_registration(kind, "rpc" if "RPC" in kind else category, args)
            if "RPC" in kind:
                session.notify_rpc(
                    {"operation": "register", "kind": kind, "args": item["args"], "profile": "modload"}
                )
            return None

        return handler

    def declarative(api: str, category: str, *, returns: str = "none"):
        def handler(*args: Any) -> Any:
            return capture_registration(api, category, args, returns=returns)

        return handler

    def native_dispatch(name: Any, *args: Any) -> Any:
        api = text(name)
        call = {"api": api, "args": safe_value(args), "profile": "modload"}
        native_calls.append(call)
        handled, value = _extension_native_dispatch(session, trace, "modload", api, args)
        if handled:
            call["extension_id"] = session.native_owners[api]
            call["handled"] = True
            return _lua_value(lua, value)
        if api == "TheSim.SetPersistentString":
            item = {"operation": "write", "name": safe_value(args[0] if args else None), "data": safe_value(args[1] if len(args) > 1 else None)}
            persistence.append(item)
            trace.emit("persistence.write", "NATIVE_STUB", "CAPTURED", **item)
            callback = args[3] if len(args) > 3 else None
            if callable(callback):
                callback(True)
            return None
        if api == "TheSim.GetPersistentString":
            item = {"operation": "read", "name": safe_value(args[0] if args else None), "fixture": "missing"}
            persistence.append(item)
            trace.emit("persistence.read", "FIXTURE", "CAPTURED", **item)
            callback = args[1] if len(args) > 1 else None
            if callable(callback):
                callback(False, None)
            return None
        item = {
            "api": api,
            "args": safe_value(args),
            "profile": "modload",
            "active_patches": [],
            "recommendation": "add a verified Native Shim, Patch, or mark the call unsupported",
        }
        unsupported.append(item)
        trace.emit("native.missing", "UNSUPPORTED", "FAILED", **item)
        raise RuntimeError(f"MissingNativeAPI: {api} in profile modload")

    proxy_factory = lua.execute(
        br"return function(root, dispatch) return setmetatable({}, {__index=function(_, key) return function(_, ...) return dispatch(root .. '.' .. key, ...) end end}) end"
    )

    globals_[b"GLOBAL"] = globals_
    globals_[b"TUNING"] = lua.table()
    globals_[b"STRINGS"] = lua.table()
    globals_[b"PrefabFiles"] = lua.table()
    globals_[b"Assets"] = lua.table()
    globals_[b"ACTIONS"] = lua.table()
    globals_[b"AllRecipes"] = lua.table()
    globals_[b"DSTLAB_USERID"] = config.userid.encode("utf-8")
    globals_[b"DSTLAB_FIXED_TIME"] = config.fixed_time.encode("utf-8")
    globals_[b"DSTLAB_SEED"] = config.seed
    lua.execute(f"math.randomseed({config.seed})".encode("ascii"))
    globals_[b"TheSim"] = proxy_factory(b"TheSim", native_dispatch)
    globals_[b"TheNet"] = proxy_factory(b"TheNet", native_dispatch)
    globals_[b"modname"] = Path(config.mod).name.encode("utf-8")
    globals_[b"modroot"] = (str(Path(config.mod)) + os.sep).encode("utf-8")
    globals_[b"MODROOT"] = globals_[b"modroot"]
    globals_[b"require"] = require_module
    globals_[b"modimport"] = modimport
    globals_[b"GetModConfigData"] = get_config

    def observe_rpc(operation: Any, kind: Any, *args: Any) -> None:
        session.notify_rpc(
            {
                "operation": text(operation),
                "kind": text(kind),
                "args": safe_value(args),
                "profile": "modload",
            }
        )

    globals_[b"DSTLAB_NATIVE"] = native_dispatch
    globals_[b"DSTLAB_RPC_OBSERVE"] = observe_rpc
    hook_apis = (
        "AddPrefabPostInit",
        "AddPrefabPostInitAny",
        "AddComponentPostInit",
        "AddClassPostConstruct",
        "AddSimPostInit",
        "AddGamePostInit",
        "AddPlayerPostInit",
        "AddWorldPostInit",
        "AddRecipePostInit",
        "AddRecipePostInitAny",
        "AddStategraphPostInit",
        "AddBrainPostInit",
    )
    rpc_apis = ("AddModRPCHandler", "AddClientModRPCHandler", "AddShardModRPCHandler")
    for name in hook_apis + rpc_apis:
        globals_[name.encode("ascii")] = register(name, "lifecycle_hook")
        mod_env[name.encode("ascii")] = globals_[name.encode("ascii")]
    declaration_apis = {
        "Prefab": ("prefab", "descriptor"),
        "Asset": ("asset", "descriptor"),
        "AddRecipe2": ("recipe", "descriptor"),
        "AddRecipe": ("recipe", "descriptor"),
        "AddAction": ("action", "descriptor"),
        "AddComponentAction": ("component_action", "none"),
        "AddStategraph": ("stategraph", "none"),
        "AddStategraphState": ("stategraph_state", "none"),
        "AddStategraphEventHandler": ("stategraph_event_handler", "none"),
        "AddUserCommand": ("user_command", "none"),
        "AddMinimapAtlas": ("atlas", "none"),
        "RegisterInventoryItemAtlas": ("atlas", "none"),
        "RegisterInventoryItemAtlas2": ("atlas", "none"),
        "RegisterSkilltreeIconsAtlas": ("atlas", "none"),
        "AddReplicableComponent": ("replica", "none"),
    }
    for name, (category, returns) in declaration_apis.items():
        globals_[name.encode("ascii")] = declarative(name, category, returns=returns)
        mod_env[name.encode("ascii")] = globals_[name.encode("ascii")]
    for key in (
        b"modname",
        b"modroot",
        b"MODROOT",
        b"require",
        b"modimport",
        b"GetModConfigData",
        b"DSTLAB_NATIVE",
        b"DSTLAB_RPC_OBSERVE",
    ):
        mod_env[key] = globals_[key]

    _apply_extension_globals(lua, globals_, session)
    for name in session.globals:
        key = name.encode("utf-8")
        mod_env[key] = globals_[key]
    for name in session.denied_mod_globals:
        deny_mod_global(name.encode("utf-8"))
    _run_extension_bootstraps(lua, session, "pre_runtime", trace)

    # DST's real scripts/class.lua installs Class in the global table and does
    # not return it. require_module therefore yields the Lua require sentinel
    # ``true``; never overwrite the real constructor with that sentinel.
    require_module("class")
    class_value = globals_[b"Class"]
    if not callable(class_value):
        raise RuntimeError("DST scripts/class.lua did not install callable Class")
    mod_env[b"Class"] = class_value

    extension_executor = lambda source, chunkname: runner(source, chunkname, mod_env)
    _run_extension_bootstraps(lua, session, "pre_mod", trace, extension_executor)

    modinfo = vfs.resolve("modinfo.lua", caller="modload")
    trace.emit("mod.entry", "MOD_REAL", "EXECUTED", kind="modinfo", uri=modinfo.uri, sha256=modinfo.sha256)
    runner(modinfo.data, ("@" + modinfo.uri).encode("utf-8"), mod_env)
    capture_mod_config_defaults()
    modmain = vfs.resolve("modmain.lua", caller="modload")
    trace.emit("mod.entry", "MOD_REAL", "EXECUTED", kind="modmain", uri=modmain.uri, sha256=modmain.sha256)
    report_dir = Path(config.report_dir)
    try:
        runner(modmain.data, ("@" + modmain.uri).encode("utf-8"), mod_env)
        _run_extension_bootstraps(lua, session, "post_mod", trace, extension_executor)
    except Exception as exc:
        if unsupported:
            raise MissingNativeRunError(str(exc)) from exc
        raise
    finally:
        _write_json(report_dir / "modules.json", modules)
        _write_json(report_dir / "hooks.json", hooks)
        _write_json(report_dir / "rpc.json", rpc)
        _write_json(report_dir / "persistence.json", persistence)
        _write_json(report_dir / "native_calls.json", native_calls)
        _write_json(report_dir / "unsupported.json", unsupported)
        _write_json(report_dir / "registrations.json", registrations)
        _write_json(
            report_dir / "mod_config.json",
            {
                "source": "modinfo.default",
                "values": {
                    name: safe_value(value)
                    for name, value in sorted(mod_config_defaults.items())
                },
            },
        )
    return {
        "status": "ok",
        "profile": "modload",
        "runtime": config.runtime,
        "runtime_metadata": runtime_metadata,
        "mod": config.mod,
        "modules_loaded": len(modules),
        "hooks_registered": len(hooks),
        "rpc_registered": len(rpc),
        "registrations_captured": len(registrations),
        "management_only": False,
        "extensions_loaded": len(session.loaded_extensions),
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) != 2 or argv[0] != "--request":
        print("usage: python -m dst_lua_lab.worker --request REQUEST.json", file=sys.stderr)
        return EXIT_INTERNAL
    request_path = Path(argv[1])
    config = RunConfig.from_json(json.loads(request_path.read_text("utf-8")))
    report_dir = Path(config.report_dir)
    trace = TraceRecorder(report_dir / "trace.jsonl", config.max_trace_events)
    result_path = report_dir / "result.json"
    session = ExtensionSession(
        profile=config.profile,
        config={
            "profile": config.profile,
            "runtime": config.runtime,
            "case_id": config.case_id,
            "mod": config.mod,
            "dependencies": list(config.dependencies),
            "scripts_zip": config.scripts_zip,
            "work_dir": config.work_dir,
            "report_dir": config.report_dir,
        },
    )
    try:
        session.load_plan(config.extension_plan or {})
        if config.profile == "algorithm":
            result = run_algorithm(config, trace, session)
        elif config.profile == "modload":
            result = run_modload(config, trace, session)
        else:
            raise ValueError(f"profile not implemented: {config.profile}")
        session.run_after(result)
        result["management_only"] = False
        result["extensions"] = session.report()
        _write_json(result_path, result)
        return EXIT_OK
    except Exception as exc:
        tb = traceback.format_exc()
        trace.emit("runtime.error", "UNSUPPORTED", "FAILED", error_type=type(exc).__name__, message=str(exc))
        _write_json(
            result_path,
            {
                "status": "error",
                "runtime": config.runtime,
                "management_only": False,
                "extensions": session.report(),
                "error_type": type(exc).__name__,
                "message": str(exc),
                "traceback": tb,
            },
        )
        (report_dir / "errors.txt").write_text(tb, "utf-8")
        if isinstance(exc, MissingNativeRunError):
            return EXIT_MISSING_NATIVE
        if isinstance(exc, ValueError):
            return EXIT_CONFIG_ERROR
        return EXIT_LUA_ERROR if "Lua" in type(exc).__name__ else EXIT_INTERNAL
    finally:
        _write_json(report_dir / "extensions.json", session.report())
        trace.flush()


if __name__ == "__main__":
    raise SystemExit(main())
