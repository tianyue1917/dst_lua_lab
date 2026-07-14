from __future__ import annotations

import importlib
from dataclasses import dataclass
from typing import Any


RUNTIME_MODULES = {
    "lua51": "lupa.lua51",
    "luajit20": "lupa.luajit20",
    "luajit21": "lupa.luajit21",
    "lua52": "lupa.lua52",
    "lua53": "lupa.lua53",
    "lua54": "lupa.lua54",
}


class UnsupportedRuntime(ValueError):
    pass


def _deny_python_attribute(_obj: Any, attribute: Any, _is_setting: bool) -> None:
    raise AttributeError(
        f"Python attribute access is disabled in DST Lua Lab: {attribute!r}"
    )


@dataclass(slots=True)
class RuntimeAdapter:
    runtime_id: str

    def create(self):
        module_name = RUNTIME_MODULES.get(self.runtime_id)
        if not module_name:
            raise UnsupportedRuntime(f"unsupported runtime: {self.runtime_id}")
        module = importlib.import_module(module_name)
        lua = module.LuaRuntime(
            unpack_returned_tuples=True,
            encoding=None,
            register_eval=False,
            register_builtins=False,
            attribute_filter=_deny_python_attribute,
        )
        lua.execute(
            b"python=nil; python_eval=nil; debug=nil; ffi=nil; "
            b"if package then package.preload={}; package.loaded.ffi=nil end"
        )
        return lua

    @staticmethod
    def metadata(lua: Any) -> dict[str, Any]:
        globals_ = lua.globals()
        version = globals_[b"_VERSION"]
        jit = globals_[b"jit"]
        jit_version = None if jit is None else jit[b"version"]
        return {
            "lua_version": version.decode("ascii", "replace") if isinstance(version, bytes) else str(version),
            "jit_version": jit_version.decode("ascii", "replace") if isinstance(jit_version, bytes) else jit_version,
        }
