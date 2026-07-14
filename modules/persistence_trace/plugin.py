"""In-memory implementations of common DST persistence native APIs."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def _callback(args: tuple[Any, ...], index: int) -> Any:
    if len(args) > index and callable(args[index]):
        return args[index]
    return None


def register(context: Any) -> None:
    store: dict[tuple[Any, ...], Any] = {}
    reads = 0
    writes = 0
    erases = 0

    initial = context.config.get("initial", {}) if isinstance(context.config, Mapping) else {}
    if isinstance(initial, Mapping):
        for name, data in initial.items():
            if isinstance(name, str) and isinstance(data, str):
                store[(name.encode("utf-8"),)] = data.encode("utf-8")

    def set_persistent(call: Any) -> None:
        nonlocal writes
        args = call.args
        name = args[0] if args else None
        data = args[1] if len(args) > 1 else None
        store[(name,)] = data
        writes += 1
        call.emit("persistence.fixture_write", "FIXTURE", "CAPTURED", name=name)
        callback = _callback(args, 3)
        if callback is not None:
            callback(True)

    def get_persistent(call: Any) -> None:
        nonlocal reads
        args = call.args
        name = args[0] if args else None
        callback = _callback(args, 1)
        reads += 1
        call.emit("persistence.fixture_read", "FIXTURE", "CAPTURED", name=name, found=(name,) in store)
        if callback is not None:
            key = (name,)
            callback(key in store, store.get(key))

    def erase_persistent(call: Any) -> None:
        nonlocal erases
        args = call.args
        name = args[0] if args else None
        store.pop((name,), None)
        erases += 1
        call.emit("persistence.fixture_erase", "FIXTURE", "CAPTURED", name=name)
        callback = next((value for value in reversed(args) if callable(value)), None)
        if callback is not None:
            callback(True)

    def set_cluster(call: Any) -> None:
        nonlocal writes
        args = call.args
        # slot, shard, name, data, encode, callback
        key = tuple(args[:3])
        store[key] = args[3] if len(args) > 3 else None
        writes += 1
        call.emit("persistence.fixture_cluster_write", "FIXTURE", "CAPTURED", slot=args[0] if args else None)
        callback = _callback(args, 5)
        if callback is not None:
            callback(True)

    def get_cluster(call: Any) -> None:
        nonlocal reads
        args = call.args
        # slot, shard, name, callback
        key = tuple(args[:3])
        reads += 1
        call.emit(
            "persistence.fixture_cluster_read",
            "FIXTURE",
            "CAPTURED",
            slot=args[0] if args else None,
            found=key in store,
        )
        callback = _callback(args, 3)
        if callback is not None:
            callback(key in store, store.get(key))

    def summarize(_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "reads": reads,
            "writes": writes,
            "erases": erases,
            "keys_in_fixture": len(store),
            "backend": "isolated_memory",
            "real_save_access": False,
        }

    context.register_native("TheSim.SetPersistentString", set_persistent)
    context.register_native("TheSim.GetPersistentString", get_persistent)
    context.register_native("TheSim.ErasePersistentString", erase_persistent)
    context.register_native("TheSim.SetPersistentStringInClusterSlot", set_cluster)
    context.register_native("TheSim.GetPersistentStringInClusterSlot", get_cluster)
    context.register_after_run(summarize)
