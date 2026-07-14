from __future__ import annotations

import json
import runpy
from pathlib import Path

import pytest

from dst_lua_lab.manifest import ManifestError, load_case_manifest, load_module_manifest
from dst_lua_lab.registry import ExtensionRegistry
from dst_lua_lab.scaffold import ScaffoldError, create_case, create_module


def _run_generated_tests(path: Path) -> None:
    namespace = runpy.run_path(str(path))
    namespace["test_manifest_contract"]()
    namespace["test_entry_contract"]()


def test_scaffolds_are_serializable_discoverable_and_executable(tmp_path: Path) -> None:
    module_files = create_module(tmp_path, "weather_trace")
    case_files = create_case(tmp_path, "weather_case")

    # CLI callers may JSON-encode the return value without Path conversion.
    assert json.loads(json.dumps(module_files)) == module_files
    assert json.loads(json.dumps(case_files)) == case_files
    assert module_files == sorted(
        [
            "modules/weather_trace/README.md",
            "modules/weather_trace/module.toml",
            "modules/weather_trace/plugin.py",
            "modules/weather_trace/tests/test_module_weather_utrace.py",
        ]
    )
    assert case_files == sorted(
        [
            "casepacks/weather_case/README.md",
            "casepacks/weather_case/adapter.py",
            "casepacks/weather_case/case.toml",
            "casepacks/weather_case/tests/test_case_weather_ucase.py",
        ]
    )

    assert load_module_manifest(tmp_path / "modules" / "weather_trace").id == "weather_trace"
    case_manifest = load_case_manifest(tmp_path / "casepacks" / "weather_case")
    assert case_manifest.id == "weather_case"
    assert case_manifest.workshop_id is None

    catalog = ExtensionRegistry(tmp_path).discover()
    assert "weather_trace" in catalog.modules
    assert "weather_case" in catalog.cases
    assert ExtensionRegistry(tmp_path).validate_case("weather_case").manifest_valid

    _run_generated_tests(
        tmp_path
        / "modules"
        / "weather_trace"
        / "tests"
        / "test_module_weather_utrace.py"
    )
    _run_generated_tests(
        tmp_path
        / "casepacks"
        / "weather_case"
        / "tests"
        / "test_case_weather_ucase.py"
    )


@pytest.mark.parametrize("factory", [create_module, create_case])
@pytest.mark.parametrize(
    "extension_id",
    [
        "../escape",
        "Bad_ID",
        "12345",
        "1234567890",
        "target_1234567890",
        "k" + "u_exampleuser",
        "con",
        "portable.",
    ],
)
def test_scaffold_rejects_unsafe_or_private_identifiers(
    tmp_path: Path, factory, extension_id: str
) -> None:
    with pytest.raises((ManifestError, ScaffoldError)):
        factory(tmp_path, extension_id)
    assert not (tmp_path / "escape").exists()


@pytest.mark.parametrize(
    "factory, collection", [(create_module, "modules"), (create_case, "casepacks")]
)
def test_scaffold_never_overwrites_existing_destination(
    tmp_path: Path, factory, collection: str
) -> None:
    destination = tmp_path / collection / "already_here"
    destination.mkdir(parents=True)
    marker = destination / "keep.txt"
    marker.write_text("keep", "utf-8")

    with pytest.raises(ScaffoldError, match="already exists"):
        factory(tmp_path, "already_here")
    assert marker.read_text("utf-8") == "keep"


def test_scaffold_rejects_collection_path_escape(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    lab = tmp_path / "lab"
    lab.mkdir()
    try:
        (lab / "modules").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks are unavailable on this host")

    with pytest.raises(ScaffoldError, match="symlink|reparse|escapes"):
        create_module(lab, "safe_name")
    assert not (outside / "safe_name").exists()
