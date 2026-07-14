"""Model selected globals that DST does not expose as bare MOD_ENV names."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


DEFAULT_DENIED = ("pcall", "xpcall")


def register(context: Any) -> None:
    denied = list(DEFAULT_DENIED)
    configured = context.config.get("deny_globals", []) if isinstance(context.config, Mapping) else []
    if isinstance(configured, list):
        for name in configured:
            if isinstance(name, str) and name and name not in denied:
                denied.append(name)

    for name in denied:
        context.deny_mod_global(name)
    context.register_global("DSTLAB_STRICT_ENV", True)
    context.register_after_run(
        lambda _result: {
            "denied_mod_globals": denied,
            "global_table_preserved": True,
        }
    )
