from __future__ import annotations

import json
import shutil
from pathlib import Path

from dst_lua_lab import cli
from dst_lua_lab.config import EXIT_CONFIG_ERROR, EXIT_MISSING_NATIVE, EXIT_OK


LAB_ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mods" / "basic_hooks_rpc"
SCRIPTS_ZIP = LAB_ROOT / ".pytest-generated" / "scripts.zip"


def test_debug_mod_runs_general_case_with_explicit_scripts_zip(capsys) -> None:
    code = cli.main(
        [
            "debug-mod",
            "--mod",
            str(FIXTURE),
            "--scripts-zip",
            str(SCRIPTS_ZIP),
            "--timeout",
            "10",
        ]
    )
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == EXIT_OK
    assert len(lines) == 2
    assert lines[0].startswith("report=")
    report = Path(lines[0].removeprefix("report="))
    diagnostic = json.loads(lines[1].removeprefix("diagnostic="))
    try:
        assert report.parent.name == "general_mod_debug"
        assert diagnostic["status"] == "ok"
        assert diagnostic["lua_modules"] >= 2  # class + real DST foundations
        assert diagnostic["extensions"] == 6
        assert diagnostic["extension_ids"] == [
            "dst_runtime_baseline",
            "strict_env",
            "rpc_capture",
            "persistence_trace",
            "scheduler_trace",
            "general_mod_debug",
        ]
        assert diagnostic["hooks"] == 4
        assert diagnostic["rpc"] == 3
        assert diagnostic["registrations"] == 7
        assert diagnostic["unsupported"] == 0
        assert diagnostic["unsupported_apis"] == []
        request = json.loads(
            (LAB_ROOT / "work" / "general_mod_debug" / report.name / "request.json").read_text("utf-8")
        )
        assert request["profile"] == "modload"
        assert request["case_id"] == "general_mod_debug"
        assert Path(request["scripts_zip"]) == SCRIPTS_ZIP.resolve()
        assert {
            "dst_runtime_baseline",
            "strict_env",
            "rpc_capture",
            "persistence_trace",
            "scheduler_trace",
        } <= {item["id"] for item in request["extension_plan"]["modules"]}
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(LAB_ROOT / "work" / "general_mod_debug" / report.name, ignore_errors=True)


def test_debug_mod_missing_automatic_scripts_zip_is_a_clear_config_error(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "modinfo.lua").write_text('name = "fixture"\n', "utf-8")
    (mod / "modmain.lua").write_text("return nil\n", "utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", lab)
    code = cli.main(["debug-mod", "--mod", str(mod)])
    error = capsys.readouterr().err
    assert code == EXIT_CONFIG_ERROR
    assert "DST scripts archive not found" in error
    assert "--scripts-zip PATH" in error


def test_debug_mod_rejects_a_non_zip_scripts_file(tmp_path: Path, capsys) -> None:
    bad_zip = tmp_path / "scripts.zip"
    bad_zip.write_text("not a zip", "utf-8")
    code = cli.main(
        ["debug-mod", "--mod", str(FIXTURE), "--scripts-zip", str(bad_zip)]
    )
    assert code == EXIT_CONFIG_ERROR
    assert "not a valid ZIP" in capsys.readouterr().err


def test_debug_mod_summary_surfaces_unknown_native_api(tmp_path: Path, capsys) -> None:
    mod = tmp_path / "unknown-native-mod"
    mod.mkdir()
    (mod / "modinfo.lua").write_text('name = "Unknown native fixture"\n', "utf-8")
    (mod / "modmain.lua").write_text("TheSim:FixtureUnknownNative(123)\n", "utf-8")
    code = cli.main(
        [
            "debug-mod",
            "--mod",
            str(mod),
            "--scripts-zip",
            str(SCRIPTS_ZIP),
            "--timeout",
            "10",
        ]
    )
    lines = capsys.readouterr().out.strip().splitlines()
    assert code == EXIT_MISSING_NATIVE
    report = Path(lines[0].removeprefix("report="))
    diagnostic = json.loads(lines[1].removeprefix("diagnostic="))
    try:
        assert diagnostic["status"] == "error"
        assert diagnostic["unsupported"] == 1
        assert diagnostic["unsupported_apis"] == ["TheSim.FixtureUnknownNative"]
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(LAB_ROOT / "work" / "general_mod_debug" / report.name, ignore_errors=True)
