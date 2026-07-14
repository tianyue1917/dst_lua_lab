from __future__ import annotations

import json
import shutil
from pathlib import Path
from zipfile import ZipFile

import pytest

from dst_lua_lab import cli
from dst_lua_lab.config import EXIT_CONFIG_ERROR, EXIT_OK, RunConfig
from dst_lua_lab.settings import SettingsStore


LAB_ROOT = Path(__file__).resolve().parents[2]
SYNTHETIC_SCRIPTS_ZIP = LAB_ROOT / ".pytest-generated" / "scripts.zip"
REPLAY_FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "mods" / "controlled_replay"


def _scripts_zip(path: Path) -> Path:
    with ZipFile(path, "w") as archive:
        archive.writestr("scripts/class.lua", "function Class(fn) return fn end\n")
        archive.writestr("scripts/constants.lua", "return nil\n")
        archive.writestr("scripts/tuning.lua", "return nil\n")
        archive.writestr("scripts/strings.lua", "return nil\n")
    return path


def test_configured_scripts_zip_is_used_when_no_flag_is_supplied(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    archive = _scripts_zip(tmp_path / "scripts.zip")
    monkeypatch.setattr(cli, "PROJECT_ROOT", lab)

    assert cli.main(["config", "set-scripts-zip", str(archive)]) == EXIT_OK
    saved = json.loads(capsys.readouterr().out)
    assert saved["scripts_zip"] == str(archive.resolve())
    assert cli._debug_scripts_zip(None) == archive.resolve()
    assert SettingsStore(lab).path.is_file()

    assert cli.main(["config", "clear-scripts-zip"]) == EXIT_OK
    cleared = json.loads(capsys.readouterr().out)
    assert cleared["scripts_zip"] is None


def test_environment_scripts_zip_overrides_local_config(
    tmp_path: Path, monkeypatch
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    configured = _scripts_zip(tmp_path / "configured.zip")
    environment = _scripts_zip(tmp_path / "environment.zip")
    SettingsStore(lab).set_scripts_zip(configured)
    monkeypatch.setattr(cli, "PROJECT_ROOT", lab)
    monkeypatch.setenv("DSTLAB_SCRIPTS_ZIP", str(environment))

    candidate, source = cli._scripts_zip_candidate(None)
    assert candidate == environment.resolve()
    assert source == "environment"


def test_doctor_json_reports_a_copyable_command(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    archive = _scripts_zip(tmp_path / "scripts.zip")
    mod = tmp_path / "mod"
    mod.mkdir()
    (mod / "modinfo.lua").write_text('name = "fixture"\n', "utf-8")
    (mod / "modmain.lua").write_text("return nil\n", "utf-8")
    monkeypatch.setattr(cli, "PROJECT_ROOT", lab)

    code = cli.main(
        [
            "doctor",
            "--scripts-zip",
            str(archive),
            "--mod",
            str(mod),
            "--json",
        ]
    )
    report = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK
    assert report["ok"] is True
    suggested = report["suggested_debug_command"]["argv"]
    debug_index = suggested.index("debug-mod")
    assert suggested[debug_index : debug_index + 2] == ["debug-mod", "--mod"]


def test_doctor_parser_rejects_unknown_runtime() -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(["doctor", "--runtime", "not-a-runtime"])
    assert exc_info.value.code == 2


def test_module_and_case_init_create_discoverable_templates(
    tmp_path: Path, monkeypatch, capsys
) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    assert cli.main(["module", "init", "sample_capability"]) == EXIT_OK
    module_output = json.loads(capsys.readouterr().out)
    assert "modules/sample_capability/module.toml" in module_output["created"]

    assert cli.main(["case", "init", "sample_case"]) == EXIT_OK
    case_output = json.loads(capsys.readouterr().out)
    assert "casepacks/sample_case/case.toml" in case_output["created"]

    assert cli.main(["module", "list"]) == EXIT_OK
    modules = json.loads(capsys.readouterr().out)["modules"]
    assert [item["id"] for item in modules] == ["sample_capability"]

    assert cli.main(["case", "list"]) == EXIT_OK
    cases = json.loads(capsys.readouterr().out)["cases"]
    assert [item["id"] for item in cases] == ["sample_case"]


@pytest.mark.parametrize(
    "payload",
    [[], [{"kind": "prefab_constructor", "target": "fixture"}]],
)
def test_algorithm_profile_rejects_replay_plan(
    tmp_path: Path, capsys, payload: list[dict[str, object]]
) -> None:
    plan = tmp_path / "replay.json"
    plan.write_text(json.dumps(payload), "utf-8")
    code = cli.main(
        [
            "run",
            "--profile",
            "algorithm",
            "--source",
            "return 1",
            "--replay-plan",
            str(plan),
        ]
    )
    assert code == EXIT_CONFIG_ERROR
    assert "requires a MOD profile" in capsys.readouterr().err


def test_algorithm_profile_rejects_modload_only_module(capsys) -> None:
    code = cli.main(
        [
            "run",
            "--profile",
            "algorithm",
            "--module",
            "rpc_capture",
            "--source",
            "return 1",
        ]
    )
    assert code == EXIT_CONFIG_ERROR
    assert "does not support profile 'algorithm'" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("payload", "expected_callbacks"),
    [
        ([], 0),
        (
            [
                {
                    "kind": "prefab_postinit",
                    "target": "dstlab_replay_prefab",
                    "strict": True,
                }
            ],
            1,
        ),
    ],
)
def test_debug_mod_replay_plan_selects_controlled_replay(
    tmp_path: Path,
    capsys,
    payload: list[dict[str, object]],
    expected_callbacks: int,
) -> None:
    plan = tmp_path / "replay.json"
    plan.write_text(
        json.dumps(payload),
        "utf-8",
    )
    code = cli.main(
        [
            "debug-mod",
            "--mod",
            str(REPLAY_FIXTURE),
            "--scripts-zip",
            str(SYNTHETIC_SCRIPTS_ZIP),
            "--replay-plan",
            str(plan),
        ]
    )
    lines = capsys.readouterr().out.strip().splitlines()
    report = Path(lines[0].removeprefix("report="))
    work = LAB_ROOT / "work" / "general_mod_debug" / report.name
    try:
        assert code == EXIT_OK
        diagnostic = json.loads(lines[1].removeprefix("diagnostic="))
        assert "controlled_replay" in diagnostic["extension_ids"]
        extensions = json.loads((report / "extensions.json").read_text("utf-8"))
        output = next(
            item["value"]
            for item in extensions["after_run_outputs"]
            if item["extension_id"] == "controlled_replay"
        )
        assert output["plan_items"] == len(payload)
        assert output["callbacks_executed"] == expected_callbacks
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def test_worker_ignores_shadow_package_in_lab_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    lab = tmp_path / "lab"
    shadow = lab / "dst_lua_lab"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("", "utf-8")
    marker = lab / "shadow-executed.txt"
    (shadow / "worker.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        "utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", lab)
    monkeypatch.chdir(lab)

    code, report = cli.launch_worker(RunConfig(source="return 42"), 5)
    work = lab / "work" / "_core" / report.name
    try:
        assert code == EXIT_OK
        assert not marker.exists()
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)
