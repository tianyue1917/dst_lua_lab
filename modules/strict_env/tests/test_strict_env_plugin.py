from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_strict_env_denies_bare_protected_calls_only():
    spec = importlib.util.spec_from_file_location("strict_env_plugin", ROOT / "plugin.py")
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)

    class Context:
        config = {}
        def __init__(self): self.denied = []
        def deny_mod_global(self, name): self.denied.append(name)
        def register_global(self, name, value): self.global_value = (name, value)
        def register_after_run(self, handler): self.after = handler

    context = Context()
    module.register(context)
    assert context.denied == ["pcall", "xpcall"]
    assert context.global_value == ("DSTLAB_STRICT_ENV", True)
    assert context.after({})["global_table_preserved"] is True
