"""Replay selected MOD callbacks against finite, local DST fixture shapes."""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Mapping
from typing import Any


SUPPORTED_KINDS = {
    "prefab_postinit",
    "component_postinit",
    "prefab_constructor",
    "mod_rpc",
    "stategraph_state",
}
RPC_TYPES = {"server", "client", "shard"}
STATE_CALLBACKS = {"onenter", "onexit", "onupdate", "ontimeout", "timeline", "event"}
MAX_PLAN_ITEMS = 100


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    return str(value)


def _nonempty_text(item: Mapping[str, Any], field: str, index: int) -> str:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"replay_plan[{index}].{field} must be a non-empty string")
    return value


def _validate_plan(raw_plan: Any) -> list[dict[str, Any]]:
    if raw_plan is None:
        return []
    if not isinstance(raw_plan, list):
        raise ValueError("replay_plan must be a JSON array")
    if len(raw_plan) > MAX_PLAN_ITEMS:
        raise ValueError(f"replay_plan exceeds the {MAX_PLAN_ITEMS} item limit")

    try:
        # Make the registered global independent from any mutable config object
        # retained by the caller and reject NaN/Infinity/non-JSON values.
        plan = json.loads(json.dumps(raw_plan, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"replay_plan must be JSON-safe: {exc}") from exc

    for index, raw_item in enumerate(plan, 1):
        if not isinstance(raw_item, dict):
            raise ValueError(f"replay_plan[{index}] must be a JSON object")
        kind = _nonempty_text(raw_item, "kind", index)
        if kind not in SUPPORTED_KINDS:
            choices = ", ".join(sorted(SUPPORTED_KINDS))
            raise ValueError(f"replay_plan[{index}].kind must be one of: {choices}")
        if "strict" in raw_item and type(raw_item["strict"]) is not bool:
            raise ValueError(f"replay_plan[{index}].strict must be a boolean")
        if "args" in raw_item and not isinstance(raw_item["args"], list):
            raise ValueError(f"replay_plan[{index}].args must be an array")
        for fixture_field in ("entity", "component", "player"):
            if fixture_field in raw_item and not isinstance(raw_item[fixture_field], dict):
                raise ValueError(
                    f"replay_plan[{index}].{fixture_field} must be an object"
                )

        if kind in {"prefab_postinit", "component_postinit", "prefab_constructor"}:
            _nonempty_text(raw_item, "target", index)
        elif kind == "mod_rpc":
            _nonempty_text(raw_item, "namespace", index)
            _nonempty_text(raw_item, "name", index)
            rpc_type = raw_item.get("rpc_type", "server")
            if not isinstance(rpc_type, str) or rpc_type not in RPC_TYPES:
                choices = ", ".join(sorted(RPC_TYPES))
                raise ValueError(
                    f"replay_plan[{index}].rpc_type must be one of: {choices}"
                )
        elif kind == "stategraph_state":
            _nonempty_text(raw_item, "stategraph", index)
            _nonempty_text(raw_item, "state", index)
            callback = raw_item.get("callback", "onenter")
            if not isinstance(callback, str) or callback not in STATE_CALLBACKS:
                choices = ", ".join(sorted(STATE_CALLBACKS))
                raise ValueError(
                    f"replay_plan[{index}].callback must be one of: {choices}"
                )
            if callback == "timeline" and "timeline_index" in raw_item:
                value = raw_item["timeline_index"]
                if type(value) is not int or value < 1:
                    raise ValueError(
                        f"replay_plan[{index}].timeline_index must be a positive integer"
                    )
            if callback == "event":
                _nonempty_text(raw_item, "event", index)
    return plan


def register(context: Any) -> None:
    plan = _validate_plan(context.config.get("replay_plan", []))
    counts: Counter[str] = Counter()
    events: list[dict[str, Any]] = []

    valid_statuses = {
        "capture": {"captured"},
        "plan": {"started", "finished"},
        "item": {"executed", "skipped", "failed"},
        "callback": {"executed", "failed"},
    }

    def replay_event(call: Any) -> None:
        if len(call.args) != 7:
            raise ValueError(
                "DSTLab.ControlledReplay.Event expects exactly 7 arguments"
            )
        operation = _text(call.args[0])
        if operation not in valid_statuses:
            raise ValueError(f"unknown controlled replay operation: {operation}")
        raw_index = call.args[1]
        if type(raw_index) not in (int, float) or int(raw_index) != raw_index or raw_index < 0:
            raise ValueError("controlled replay event index must be a non-negative integer")
        index = int(raw_index)
        kind = _text(call.args[2])
        status = _text(call.args[3])
        if status not in valid_statuses[operation]:
            raise ValueError(
                f"invalid controlled replay status {status!r} for {operation!r}"
            )
        target = _text(call.args[4])
        callback = _text(call.args[5])
        detail = _text(call.args[6])
        event = {
            "operation": operation,
            "index": index,
            "kind": kind,
            "status": status,
            "target": target,
            "callback": callback,
            "detail": detail,
        }
        events.append(event)
        counts[f"{operation}.{status}"] += 1
        effect = {
            "captured": "CAPTURED",
            "started": "CAPTURED",
            "finished": "EXECUTED",
            "executed": "EXECUTED",
            "skipped": "SKIPPED",
            "failed": "FAILED",
        }[status]
        call.emit(
            f"replay.{operation}",
            "MOD_REAL" if operation == "capture" else "FIXTURE",
            effect,
            index=index,
            kind=kind,
            status=status,
            target=target,
            callback=callback,
            detail=detail,
            explicit_plan=operation != "capture",
            real_engine=False,
        )

    def summarize(_result: dict[str, Any]) -> dict[str, Any]:
        return {
            "configured": bool(plan),
            "plan_items": len(plan),
            "strict_items": sum(1 for item in plan if item.get("strict") is True),
            "registrations_captured": counts["capture.captured"],
            "items_executed": counts["item.executed"],
            "items_skipped": counts["item.skipped"],
            "items_failed": counts["item.failed"],
            "callbacks_executed": counts["callback.executed"],
            "callbacks_failed": counts["callback.failed"],
            "event_counts": dict(sorted(counts.items())),
            "events": events,
            "implicit_callback_execution": False,
            "synthetic_entities": True,
            "network_access": False,
            "persistence_access": False,
            "real_engine": False,
        }

    context.register_global("DSTLAB_REPLAY_PLAN", plan)
    context.register_lua_bootstrap("pre_mod", "lua/capture.lua")
    context.register_native("DSTLab.ControlledReplay.Event", replay_event)
    context.register_after_run(summarize)
