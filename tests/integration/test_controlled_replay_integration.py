from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from dst_lua_lab.cli import PROJECT_ROOT, launch_worker
from dst_lua_lab.config import EXIT_LUA_ERROR, EXIT_OK, RunConfig
from dst_lua_lab.planner import ExtensionPlanner
from dst_lua_lab.registry import ExtensionRegistry
from dst_lua_lab.state import ExtensionState


SCRIPTS_ZIP = PROJECT_ROOT / ".pytest-generated" / "scripts.zip"
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mods" / "controlled_replay"


def _plan() -> dict[str, Any]:
    value = ExtensionPlanner(
        ExtensionRegistry(PROJECT_ROOT).discover(), ExtensionState()
    ).resolve(requested_modules=["controlled_replay"]).to_dict()
    value["management_only"] = False
    return value


def _run(replay_plan: list[dict[str, Any]]) -> tuple[int, Path, Path]:
    config = RunConfig(
        profile="modload",
        scripts_zip=str(SCRIPTS_ZIP),
        mod=str(FIXTURE),
        requested_modules=["controlled_replay"],
        replay_plan=replay_plan,
        extension_plan=_plan(),
        management_only=False,
    )
    code, report = launch_worker(config, 10)
    return code, report, Path(config.work_dir)


def _output(report: Path) -> dict[str, Any]:
    extensions = json.loads((report / "extensions.json").read_text("utf-8"))
    return next(
        item["value"]
        for item in extensions["after_run_outputs"]
        if item["extension_id"] == "controlled_replay"
    )


def test_worker_empty_replay_plan_keeps_all_registered_callbacks_capture_only() -> None:
    code, report, work = _run([])
    try:
        assert code == EXIT_OK
        output = _output(report)
        assert output["configured"] is False
        assert output["registrations_captured"] == 5
        assert output["callbacks_executed"] == 0
        assert output["implicit_callback_execution"] is False
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def test_worker_runs_only_the_five_explicit_replay_items() -> None:
    replay_plan = [
        {"kind": "prefab_postinit", "target": "dstlab_replay_prefab", "strict": True},
        {"kind": "component_postinit", "target": "dstlab_replay_component", "strict": True},
        {"kind": "prefab_constructor", "target": "dstlab_replay_prefab", "strict": True},
        {
            "kind": "mod_rpc",
            "rpc_type": "server",
            "namespace": "dstlab_replay",
            "name": "ping",
            "args": ["fixture_payload"],
            "strict": True,
        },
        {
            "kind": "stategraph_state",
            "stategraph": "dstlab_replay_graph",
            "state": "dstlab_replay_idle",
            "callback": "onenter",
            "args": [{"source": "fixture"}],
            "strict": True,
        },
    ]
    code, report, work = _run(replay_plan)
    try:
        assert code == EXIT_OK
        output = _output(report)
        assert output["plan_items"] == 5
        assert output["items_executed"] == 5
        assert output["callbacks_executed"] == 5
        assert output["callbacks_failed"] == 0
        assert output["network_access"] is False
        assert output["persistence_access"] is False
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def test_worker_strict_replay_failure_keeps_after_run_evidence() -> None:
    code, report, work = _run(
        [
            {
                "kind": "prefab_postinit",
                "target": "missing_fixture",
                "strict": True,
            }
        ]
    )
    try:
        assert code == EXIT_LUA_ERROR
        output = _output(report)
        assert output["plan_items"] == 1
        assert output["items_failed"] == 1
        assert output["callbacks_executed"] == 0
        result = json.loads((report / "result.json").read_text("utf-8"))
        assert result["status"] == "error"
        assert result["profile"] == "modload"
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
