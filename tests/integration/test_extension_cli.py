from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dst_lua_lab import cli
from dst_lua_lab.config import EXIT_OK, RunConfig


@pytest.mark.parametrize("profile", ["frontend", "server-sim"])
def test_run_parser_rejects_unimplemented_profiles(profile: str) -> None:
    with pytest.raises(SystemExit) as exc_info:
        cli.build_parser().parse_args(
            ["run", "--profile", profile, "--source", "return 1"]
        )
    assert exc_info.value.code == 2


def test_core_run_uses_core_namespace_and_records_management_plan() -> None:
    config = RunConfig(source="return 7")
    code, report = cli.launch_worker(config, 5)
    work = Path(config.work_dir)
    try:
        assert code == EXIT_OK
        assert report.parent.name == "_core"
        assert work.parent.name == "_core"
        request = json.loads((work / "request.json").read_text("utf-8"))
        inputs = json.loads((report / "inputs.json").read_text("utf-8"))
        environment = json.loads((report / "environment.json").read_text("utf-8"))
        assert request["extension_plan"]["management_only"] is True
        assert inputs["extension_plan"] == request["extension_plan"]
        assert environment["extension_plan"] == request["extension_plan"]
        assert inputs["management_only"] is True
        assert environment["plan_management_only"] is True
        assert environment["management_only"] is False
        assert environment["extensions"]["management_only"] is False
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def test_case_run_uses_case_namespace_and_preserves_plan() -> None:
    plan = {
        "schema": 1,
        "management_only": True,
        "case": {"id": "fixture_case", "version": "1.0.0"},
        "modules": [{"id": "rpc_capture", "reason": ["case-required"]}],
        "disabled_optional_modules": [],
    }
    config = RunConfig(source="return 8", case_id="fixture_case", extension_plan=plan)
    code, report = cli.launch_worker(config, 5)
    work = Path(config.work_dir)
    try:
        assert code == EXIT_OK
        assert report.parent.name == "fixture_case"
        assert work.parent.name == "fixture_case"
        request = json.loads((work / "request.json").read_text("utf-8"))
        environment = json.loads((report / "environment.json").read_text("utf-8"))
        assert request["extension_plan"] == plan
        assert environment["extension_plan"] == plan
    finally:
        shutil.rmtree(report, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def test_clean_case_generated_is_confined(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    for kind in ("work", "reports"):
        target = tmp_path / kind / "fixture_case"
        target.mkdir(parents=True)
        (target / "artifact.txt").write_text("generated", "utf-8")
    removed = cli.clean_case_generated("fixture_case")
    assert len(removed) == 2
    assert not (tmp_path / "work" / "fixture_case").exists()
    assert not (tmp_path / "reports" / "fixture_case").exists()


def test_clean_rejects_namespace_symlink(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    work = tmp_path / "work"
    work.mkdir()
    link = work / "fixture_case"
    try:
        link.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")
    with pytest.raises(ValueError, match="symlink|reparse|outside"):
        cli.clean_case_generated("fixture_case")
    assert outside.is_dir()


def test_clean_rejects_traversal_id(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    with pytest.raises(ValueError, match="extension id"):
        cli.clean_case_generated("../outside")
