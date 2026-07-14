from __future__ import annotations

import json
import zipfile
from pathlib import Path

from dst_lua_lab.doctor import (
    REQUIRED_RUNTIMES,
    REQUIRED_SCRIPTS_MEMBERS,
    build_debug_mod_command,
    check_dependency_directories,
    check_extension_registry,
    check_lupa_runtimes,
    check_mod_directory,
    check_python,
    check_scripts_zip,
    resolve_scripts_zip,
    run_doctor,
)


def _scripts_zip(path: Path, *, missing: str | None = None) -> Path:
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
        for member in REQUIRED_SCRIPTS_MEMBERS:
            if member != missing:
                archive.writestr(member, "return nil\n")
    return path


def _mod(path: Path) -> Path:
    path.mkdir()
    (path / "modinfo.lua").write_text('name = "fixture"\n', "utf-8")
    (path / "modmain.lua").write_text("return nil\n", "utf-8")
    return path


def _runtime_probe(runtime_id: str) -> dict[str, str | None]:
    return {
        "lua_version": "Lua 5.1",
        "jit_version": "LuaJIT fixture" if runtime_id.startswith("luajit") else None,
    }


def test_healthy_doctor_report_is_json_safe_and_builds_replay_command(
    tmp_path: Path,
) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    scripts = _scripts_zip(tmp_path / "official-scripts.zip")
    mod = _mod(tmp_path / "fixture mod")
    dependency = tmp_path / "dependency mod"
    dependency.mkdir()

    report = run_doctor(
        lab,
        scripts_zip=scripts,
        mod=mod,
        dependencies=[dependency],
        version_info=(3, 11, 8),
        runtime_probe=_runtime_probe,
    )

    assert report.ok
    value = report.to_dict()
    assert json.loads(json.dumps(value)) == value
    assert value["summary"] == {
        "total": 8,
        "passed": 8,
        "failed": 0,
        "skipped": 0,
        "warnings": 0,
    }
    assert value["scripts_zip_source"] == "explicit"
    command = value["suggested_debug_command"]
    assert isinstance(command, dict)
    assert command["argv"] == [
        "python",
        "dstlab.py",
        "debug-mod",
        "--mod",
        str(mod.resolve()),
        "--scripts-zip",
        str(scripts.resolve()),
        "--runtime",
        "luajit20",
        "--dependency",
        str(dependency.resolve()),
    ]
    assert str(mod.resolve()) in str(command["display"])
    assert json.loads(report.to_json())["ok"] is True


def test_python_and_runtime_failures_are_isolated() -> None:
    assert check_python((3, 10, 14)).status == "fail"
    assert check_python((3, 11, 0)).status == "pass"

    def probe(runtime_id: str) -> dict[str, str]:
        if runtime_id == "luajit20":
            raise ImportError("fixture missing binary")
        return {"lua_version": "fixture"}

    checks = check_lupa_runtimes(probe=probe)
    assert tuple(check.id for check in checks) == tuple(
        f"runtime.{runtime_id}" for runtime_id in REQUIRED_RUNTIMES
    )
    failed = [check for check in checks if not check.ok]
    assert len(failed) == 1
    assert failed[0].id == "runtime.luajit20"
    assert failed[0].details["error_type"] == "ImportError"


def test_scripts_zip_checks_missing_invalid_and_required_members(tmp_path: Path) -> None:
    missing = check_scripts_zip(tmp_path / "missing.zip")
    assert missing.status == "fail"
    assert "does not exist" in missing.summary

    invalid_path = tmp_path / "invalid.zip"
    invalid_path.write_text("not a zip", "utf-8")
    invalid = check_scripts_zip(invalid_path)
    assert invalid.status == "fail"
    assert "not a valid ZIP" in invalid.summary

    incomplete_path = _scripts_zip(
        tmp_path / "incomplete.zip", missing="scripts/strings.lua"
    )
    incomplete = check_scripts_zip(incomplete_path)
    assert incomplete.status == "fail"
    assert incomplete.details["missing_members"] == ["scripts/strings.lua"]

    complete = check_scripts_zip(_scripts_zip(tmp_path / "complete.zip"))
    assert complete.status == "pass"
    assert complete.details["missing_members"] == []

    absolute_path = tmp_path / "absolute-members.zip"
    with zipfile.ZipFile(absolute_path, "w") as archive:
        for member in REQUIRED_SCRIPTS_MEMBERS:
            archive.writestr("/" + member, "return nil\n")
    absolute = check_scripts_zip(absolute_path)
    assert absolute.status == "fail"
    assert absolute.details["missing_members"] == list(REQUIRED_SCRIPTS_MEMBERS)

    corrupt_path = tmp_path / "corrupt.zip"
    with zipfile.ZipFile(corrupt_path, "w", zipfile.ZIP_STORED) as archive:
        for member in REQUIRED_SCRIPTS_MEMBERS:
            archive.writestr(member, f"-- payload for {member}\n")
    payload = bytearray(corrupt_path.read_bytes())
    marker = b"-- payload for scripts/class.lua\n"
    offset = payload.find(marker)
    assert offset >= 0
    payload[offset] ^= 0x01
    corrupt_path.write_bytes(payload)
    corrupt = check_scripts_zip(corrupt_path)
    assert corrupt.status == "fail"
    assert "could not be read" in corrupt.summary


def test_mod_is_optional_but_supplied_mod_requires_both_entries(tmp_path: Path) -> None:
    skipped = check_mod_directory(None)
    assert skipped.status == "skip" and skipped.ok

    target = tmp_path / "mod"
    target.mkdir()
    (target / "modinfo.lua").write_text("return nil\n", "utf-8")
    failed = check_mod_directory(target)
    assert failed.status == "fail"
    assert failed.details["missing_files"] == ["modmain.lua"]

    (target / "modmain.lua").write_text("return nil\n", "utf-8")
    assert check_mod_directory(target).status == "pass"


def test_dependency_check_requires_existing_directories(tmp_path: Path) -> None:
    directory = tmp_path / "directory"
    directory.mkdir()
    regular_file = tmp_path / "file.lua"
    regular_file.write_text("", "utf-8")
    checks = check_dependency_directories(
        [directory, regular_file, tmp_path / "missing"]
    )
    assert [check.status for check in checks] == ["pass", "fail", "fail"]
    assert [check.id for check in checks] == [
        "dependency.0",
        "dependency.1",
        "dependency.2",
    ]


def test_extension_registry_failure_is_reported_not_raised(tmp_path: Path) -> None:
    root = tmp_path / "modules" / "broken"
    root.mkdir(parents=True)
    (root / "module.toml").write_text("not valid toml = [", "utf-8")

    check = check_extension_registry(tmp_path)

    assert check.status == "fail"
    assert check.details["error_type"]
    assert "invalid" in check.summary.lower()


def test_default_scripts_resolution_and_report_without_mod(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    expected = _scripts_zip(tmp_path / "scripts.zip")
    resolved, source = resolve_scripts_zip(lab, None)
    assert resolved == expected.resolve()
    assert source == "default"

    report = run_doctor(
        lab,
        version_info=(3, 12, 0),
        runtime_probe=_runtime_probe,
    )
    assert report.ok
    assert report.scripts_zip_source == "default"
    assert report.suggested_debug_command is None
    assert next(check for check in report.checks if check.id == "mod").status == "skip"


def test_doctor_does_not_suggest_command_for_invalid_inputs(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    lab.mkdir()
    mod = _mod(tmp_path / "mod")
    report = run_doctor(
        lab,
        scripts_zip=tmp_path / "missing.zip",
        mod=mod,
        version_info=(3, 11, 0),
        runtime_probe=_runtime_probe,
    )
    assert report.ok is False
    assert report.suggested_debug_command is None


def test_command_builder_accepts_custom_launcher_and_runtime(tmp_path: Path) -> None:
    command = build_debug_mod_command(
        tmp_path / "mod",
        tmp_path / "scripts.zip",
        runtime="lua51",
        launcher=("py", "-3.11", "dstlab.py"),
    )
    assert command.argv[:5] == (
        "py",
        "-3.11",
        "dstlab.py",
        "debug-mod",
        "--mod",
    )
    assert command.argv[-2:] == ("--runtime", "lua51")
