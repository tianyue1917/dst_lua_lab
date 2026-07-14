"""Install deterministic, traceable shapes for common DST runtime objects."""
from collections import Counter
from pathlib import Path
from typing import Any

def register(context: Any) -> None:
    events: Counter[str] = Counter()
    allowed_roots = []
    for raw in [context.config.get("mod"), *(context.config.get("dependencies") or [])]:
        if isinstance(raw, str) and raw:
            allowed_roots.append(Path(raw).resolve())

    def runtime_event(call: Any) -> None:
        raw = call.args[0] if call.args else "unknown"
        name = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        events[name] += 1
        call.emit("runtime.fixture", "FIXTURE", "CAPTURED", operation=name, args=call.args[1:])

    def read_file(call: Any) -> Any:
        raw_path = call.args[0] if call.args else None
        raw_mode = call.args[1] if len(call.args) > 1 else b"r"
        path_text = raw_path.decode("utf-8", "replace") if isinstance(raw_path, bytes) else str(raw_path or "")
        mode = raw_mode.decode("ascii", "replace") if isinstance(raw_mode, bytes) else str(raw_mode or "r")
        if mode not in {"r", "rb"}:
            events["file.denied"] += 1
            call.emit(
                "filesystem.fixture_deny",
                "FIXTURE",
                "DENIED",
                path=path_text,
                mode=mode,
                reason="read_only_policy",
            )
            return None, f"DST Lua Lab scoped io.open is read-only: {mode}".encode()
        candidate = Path(path_text)
        if not candidate.is_absolute() and allowed_roots:
            candidate = allowed_roots[0] / candidate
        resolved = candidate.resolve()
        if not any(resolved == root or resolved.is_relative_to(root) for root in allowed_roots):
            events["file.denied"] += 1
            call.emit(
                "filesystem.fixture_deny",
                "FIXTURE",
                "DENIED",
                path=str(resolved),
                mode=mode,
                reason="outside_mounted_roots",
            )
            return None, f"path is outside mounted MOD roots: {resolved}".encode("utf-8")
        if not resolved.is_file():
            return None, f"file not found: {resolved}".encode("utf-8")
        if resolved.stat().st_size > 16 * 1024 * 1024:
            return None, f"file exceeds 16 MiB read limit: {resolved}".encode("utf-8")
        data = resolved.read_bytes()
        events["file.read"] += 1
        call.emit(
            "filesystem.fixture_read",
            "FIXTURE",
            "CAPTURED",
            path=str(resolved),
            length=len(data),
            read_only=True,
        )
        return data, None

    context.register_lua_bootstrap("pre_mod", "lua/bootstrap.lua")
    context.register_native("DSTLab.Runtime.Event", runtime_event)
    context.register_native("DSTLab.Runtime.ReadFile", read_file)
    context.register_after_run(lambda _result: {
        "events": dict(sorted(events.items())), "fixture_calls": sum(events.values()),
        "backend": "lua_shape_fixture", "real_engine": False,
    })
