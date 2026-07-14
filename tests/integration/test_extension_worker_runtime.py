from __future__ import annotations

import hashlib
import json
from pathlib import Path

from dst_lua_lab.cli import launch_worker
from dst_lua_lab.config import EXIT_CONFIG_ERROR, EXIT_OK, RunConfig


def _make_plan(tmp_path: Path, plugin: str) -> dict[str, object]:
    root = tmp_path / "runtime_test"
    root.mkdir()
    manifest = root / "module.toml"
    manifest.write_text('id = "runtime_test"\n', "utf-8")
    entry = root / "plugin.py"
    entry.write_text(plugin, "utf-8")
    (root / "boot.lua").write_text(
        'NATIVE_RESULT = DSTLAB_NATIVE("Example.Double", 6)\n'
        'DSTLAB_RPC_OBSERVE("send", "synthetic", "payload")\n'
        'BOOTSTRAPPED = true\n',
        "utf-8",
    )
    item = {
        "id": "runtime_test",
        "api_version": "1",
        "root": str(root.resolve()),
        "manifest_path": str(manifest.resolve()),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest().upper(),
        "entry_path": str(entry.resolve()),
        "dependencies": [],
    }
    return {"modules": [item], "case": None, "dependency_order": ["runtime_test"]}


def test_worker_executes_selected_extension_and_reports_contributions(tmp_path: Path) -> None:
    plan = _make_plan(
        tmp_path,
        "def register(context):\n"
        "    context.register_global('FIXTURE', {'answer': 21})\n"
        "    context.register_lua_bootstrap('pre_runtime', 'boot.lua')\n"
        "    context.register_native('Example.Double', lambda call: call.args[0] * 2)\n"
        "    context.register_rpc_observer(lambda event: None)\n"
        "    context.register_after_run(lambda result: {'observed': result['status']})\n",
    )
    code, report_dir = launch_worker(
        RunConfig(
            source="return FIXTURE.answer + NATIVE_RESULT, BOOTSTRAPPED",
            extension_plan=plan,
        ),
        5,
    )
    assert code == EXIT_OK
    result = json.loads((report_dir / "result.json").read_text("utf-8"))
    extensions = json.loads((report_dir / "extensions.json").read_text("utf-8"))
    assert result["result"] == [33, True]
    assert result["management_only"] is False
    assert extensions["extensions_loaded"] is True
    assert extensions["loaded_extensions"][0]["entry_sha256"]
    assert extensions["after_run_outputs"] == [
        {"extension_id": "runtime_test", "value": {"observed": "ok"}}
    ]
    assert {item["type"] for item in extensions["contributions"]} == {
        "global",
        "lua_bootstrap",
        "native",
        "rpc_observer",
        "after_run",
    }


def test_register_exception_is_an_explicit_config_failure(tmp_path: Path) -> None:
    plan = _make_plan(tmp_path, "def register(context):\n    raise RuntimeError('register boom')\n")
    code, report_dir = launch_worker(RunConfig(source="return 1", extension_plan=plan), 5)
    result = json.loads((report_dir / "result.json").read_text("utf-8"))
    assert code == EXIT_CONFIG_ERROR
    assert result["error_type"] == "ExtensionRuntimeError"
    assert "register(context) failed" in result["message"]
