from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from dst_lua_lab import cli
from dst_lua_lab.registry import ExtensionRegistry, RegistryError
from dst_lua_lab.state import StateStore


LAB_ROOT = Path(__file__).resolve().parents[2]


def _copy_examples(root: Path, *, include_case: bool = True) -> None:
    shutil.copytree(
        LAB_ROOT / "modules" / "example_trace",
        root / "modules" / "example_trace",
    )
    if include_case:
        shutil.copytree(
            LAB_ROOT / "casepacks" / "example_case",
            root / "casepacks" / "example_case",
        )


def _write_external_case(parent: Path, case_id: str = "external_case") -> Path:
    root = parent / case_id
    root.mkdir(parents=True)
    (root / "case.toml").write_text(
        "\n".join(
            [
                "schema = 1",
                f'id = "{case_id}"',
                'name = "Synthetic external case"',
                'version = "1.0.0"',
                'api_version = "1"',
                "required_modules = []",
                "",
            ]
        ),
        "utf-8",
    )
    return root


def test_builtin_examples_are_discoverable_and_contain_no_target_identity() -> None:
    catalog = ExtensionRegistry(LAB_ROOT).discover()
    assert "example_trace" in catalog.modules
    assert "example_case" in catalog.cases
    case_text = (LAB_ROOT / "casepacks" / "example_case" / "case.toml").read_text(
        "utf-8"
    )
    assert "workshop_id" not in case_text
    assert "KU_" not in case_text


def test_module_list_does_not_execute_a_malicious_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sentinel = tmp_path / "entry-executed.txt"
    module = tmp_path / "modules" / "malicious_example"
    module.mkdir(parents=True)
    (module / "module.toml").write_text(
        "\n".join(
            [
                "schema = 1",
                'id = "malicious_example"',
                'name = "Must not execute during discovery"',
                'version = "1.0.0"',
                'api_version = "1"',
                'entry = "plugin.py"',
                "",
            ]
        ),
        "utf-8",
    )
    (module / "plugin.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(sentinel)!r}).write_text('executed', encoding='utf-8')\n",
        "utf-8",
    )
    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)

    assert cli.main(["module", "list"]) == 0
    output = json.loads(capsys.readouterr().out)
    assert output["management_only"] is True
    assert [item["id"] for item in output["modules"]] == ["malicious_example"]
    assert not sentinel.exists()


def test_case_required_module_is_plan_only_and_not_persisted(tmp_path: Path) -> None:
    # Import here so this test also catches accidental planner import side effects
    # without making collection depend on an extension implementation detail.
    from dst_lua_lab.planner import ExtensionPlanner

    _copy_examples(tmp_path)
    store = StateStore(tmp_path)
    catalog = ExtensionRegistry(tmp_path, store).discover()
    before = store.load()

    plan = ExtensionPlanner(catalog, before).resolve(case_id="example_case")
    serialized = plan.to_dict()

    assert serialized["dependency_order"] == ["example_trace"]
    assert serialized["modules"][0]["reasons"] == ["case_required"]
    assert store.load() == before
    assert store.load().enabled_modules == ()


def test_external_mount_unmount_is_idempotent_and_protects_identity(
    tmp_path: Path,
) -> None:
    _copy_examples(tmp_path)
    external_parent = tmp_path.parent / f"{tmp_path.name}-external"
    first_root = _write_external_case(external_parent / "one")
    second_root = _write_external_case(external_parent / "two")
    store = StateStore(tmp_path)
    registry = ExtensionRegistry(tmp_path, store)

    first = registry.mount_case(first_root)
    again = registry.mount_case(first_root)
    assert first == again
    assert first.external_cases["external_case"] == str(first_root.resolve())

    with pytest.raises(RegistryError, match="already mounted"):
        registry.mount_case(second_root)
    with pytest.raises(RegistryError, match="built-in"):
        registry.unmount_case("example_case")

    removed = registry.unmount_case("external_case")
    removed_again = registry.unmount_case("external_case")
    assert removed == removed_again
    assert "external_case" not in removed.external_cases
    assert first_root.is_dir()


def test_core_run_survives_external_case_removal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    external_root = _write_external_case(tmp_path.parent / f"{tmp_path.name}-source")
    store = StateStore(tmp_path)
    registry = ExtensionRegistry(tmp_path, store)
    registry.mount_case(external_root)
    registry.unmount_case("external_case")
    shutil.rmtree(external_root)

    monkeypatch.setattr(cli, "PROJECT_ROOT", tmp_path)
    # Worker is a fresh process. Preserve the real Core source while the run and
    # state directories remain isolated under tmp_path.
    monkeypatch.setenv("PYTHONPATH", str(LAB_ROOT / "src"))
    assert cli.main(["run", "--source", "return 6 * 7", "--timeout", "5"]) == 0
    report_line = capsys.readouterr().out.strip().splitlines()[-1]
    report = Path(report_line.removeprefix("report="))
    assert report.parent == tmp_path / "reports" / "_core"
    assert json.loads((report / "result.json").read_text("utf-8"))["result"] == 42
    state = json.loads((tmp_path / ".dstlab" / "state.json").read_text("utf-8"))
    assert state["external_cases"] == {}
