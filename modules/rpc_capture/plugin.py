"""Capture RPC registration and send boundaries without network access."""

from __future__ import annotations

from collections import Counter
from typing import Any


def register(context: Any) -> None:
    counts: Counter[str] = Counter()
    kinds: Counter[str] = Counter()

    def observe(event: dict[str, Any]) -> None:
        operation = str(event.get("operation", "unknown"))
        kind = str(event.get("kind", "unknown"))
        counts[operation] += 1
        kinds[kind] += 1

    def summarize(_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "registrations": counts["register"],
            "sends": counts["send"],
            "kinds": dict(sorted(kinds.items())),
            "network_access": False,
        }

    context.register_lua_bootstrap("pre_mod", "lua/bootstrap.lua")
    context.register_rpc_observer(observe)
    context.register_after_run(summarize)
