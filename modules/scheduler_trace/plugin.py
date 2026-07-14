"""Install a deterministic Lua virtual-time task queue."""

from __future__ import annotations

from collections import Counter
from typing import Any


def register(context: Any) -> None:
    events: Counter[str] = Counter()

    def scheduler_event(call: Any) -> None:
        args = call.args
        name = args[0] if args else "unknown"
        if isinstance(name, bytes):
            name = name.decode("utf-8", "replace")
        events[str(name)] += 1
        call.emit("scheduler.virtual_event", "FIXTURE", "CAPTURED", operation=str(name))

    context.register_lua_bootstrap("pre_mod", "lua/bootstrap.lua")
    context.register_native("DSTLab.Scheduler.Event", scheduler_event)
    context.register_after_run(
        lambda _result: {
            "events": dict(sorted(events.items())),
            "clock": "virtual",
            "wall_clock_access": False,
        }
    )
