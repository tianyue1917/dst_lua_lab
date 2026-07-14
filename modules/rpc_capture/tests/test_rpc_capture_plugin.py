from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_rpc_plugin_declares_bootstrap_and_summarizes_events():
    spec = importlib.util.spec_from_file_location("rpc_capture_plugin", ROOT / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class Context:
        def register_lua_bootstrap(self, phase, path): self.bootstrap = (phase, path)
        def register_rpc_observer(self, handler): self.observer = handler
        def register_after_run(self, handler): self.after = handler

    context = Context()
    module.register(context)
    context.observer({"operation": "register", "kind": "AddModRPCHandler"})
    context.observer({"operation": "send", "kind": "SendModRPCToServer"})
    assert context.bootstrap == ("pre_mod", "lua/bootstrap.lua")
    assert context.after({"status": "ok"})["sends"] == 1
    assert context.after({"status": "ok"})["network_access"] is False
