from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_scheduler_plugin_registers_only_virtual_local_handlers():
    spec = importlib.util.spec_from_file_location("scheduler_trace_plugin", ROOT / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class Context:
        def register_lua_bootstrap(self, phase, path): self.bootstrap = (phase, path)
        def register_native(self, api, handler): self.native = (api, handler)
        def register_after_run(self, handler): self.after = handler

    context = Context()
    module.register(context)
    class Call:
        args = (b"schedule",)
        def emit(self, event_type, source, effect, **data): pass
    context.native[1](Call())
    assert context.bootstrap == ("pre_mod", "lua/bootstrap.lua")
    assert context.native[0] == "DSTLab.Scheduler.Event"
    summary = context.after({"status": "ok"})
    assert summary["events"] == {"schedule": 1}
    assert summary["wall_clock_access"] is False
