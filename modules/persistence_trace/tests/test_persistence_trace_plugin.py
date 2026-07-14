from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_persistence_plugin_is_process_local_and_replays_callbacks():
    spec = importlib.util.spec_from_file_location("persistence_trace_plugin", ROOT / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class Context:
        config = {}
        def __init__(self): self.natives = {}
        def register_native(self, api, handler): self.natives[api] = handler
        def register_after_run(self, handler): self.after = handler

    context = Context()
    module.register(context)
    class Call:
        def __init__(self, *args): self.args = args
        def emit(self, event_type, source, effect, **data): pass
    callbacks = []
    context.natives["TheSim.SetPersistentString"](Call(b"key", b"value", False, lambda ok: callbacks.append(ok)))
    context.natives["TheSim.GetPersistentString"](Call(b"key", lambda ok, data: callbacks.append((ok, data))))
    assert callbacks == [True, (True, b"value")]
    summary = context.after({"status": "ok"})
    assert summary["backend"] == "isolated_memory"
    assert summary["real_save_access"] is False
