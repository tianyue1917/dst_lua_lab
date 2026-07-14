from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dst_lua_lab.manifest import ManifestError, load_case_manifest, load_module_manifest
from dst_lua_lab.planner import ExtensionPlanner, PlannerError
from dst_lua_lab.registry import ExtensionRegistry, RegistryError
from dst_lua_lab.state import ExtensionState, StateError, StateStore


def module(
    lab: Path,
    module_id: str,
    *,
    priority: int = 100,
    dependencies: tuple[str, ...] = (),
    conflicts: tuple[str, ...] = (),
    entry: str | None = None,
) -> Path:
    root = lab / "modules" / module_id
    root.mkdir(parents=True)
    lines = [
        "schema = 1",
        f'id = "{module_id}"',
        f'name = "{module_id}"',
        'version = "1.0.0"',
        'api_version = "1"',
        f"priority = {priority}",
        "dependencies = [" + ", ".join(f'"{x}"' for x in dependencies) + "]",
        "conflicts = [" + ", ".join(f'"{x}"' for x in conflicts) + "]",
    ]
    if entry:
        lines.append(f'entry = "{entry}"')
        (root / entry).write_text("raise RuntimeError('must not execute')", "utf-8")
    (root / "module.toml").write_text("\n".join(lines) + "\n", "utf-8")
    return root


def case(
    root: Path,
    case_id: str,
    *,
    required: tuple[str, ...] = (),
    optional: tuple[str, ...] = (),
    entry: str | None = None,
    match: str = "",
) -> Path:
    root.mkdir(parents=True)
    lines = [
        "schema = 1",
        f'id = "{case_id}"',
        f'name = "{case_id}"',
        'version = "1.0.0"',
        'api_version = "1"',
        "required_modules = [" + ", ".join(f'"{x}"' for x in required) + "]",
        "optional_modules = [" + ", ".join(f'"{x}"' for x in optional) + "]",
    ]
    if entry:
        lines.append(f'entry = "{entry}"')
        (root / entry).write_text("raise RuntimeError('must not execute')", "utf-8")
    if match:
        lines.append(match)
    (root / "case.toml").write_text("\n".join(lines) + "\n", "utf-8")
    return root


def test_manifest_defaults_are_frozen_and_listing_never_executes_entry(tmp_path: Path) -> None:
    root = module(tmp_path, "safe_module", entry="plugin.py")
    manifest = load_module_manifest(root)
    assert manifest.priority == 100
    assert manifest.dependencies == ()
    assert ExtensionRegistry(tmp_path).list_modules()[0].manifest == manifest


@pytest.mark.parametrize(
    "replacement, message",
    [
        ('id = "Wrong"', "must match"),
        ('id = "different"', "does not match directory"),
        ('schema = 2', "unsupported manifest schema"),
        ('api_version = "2"', "unsupported extension api_version"),
        ('priority = 10001', "priority"),
    ],
)
def test_module_manifest_strict_validation(
    tmp_path: Path, replacement: str, message: str
) -> None:
    root = module(tmp_path, "good")
    text = (root / "module.toml").read_text("utf-8")
    key = replacement.split(" =", 1)[0]
    text = "\n".join(
        replacement if line.startswith(f"{key} =") else line for line in text.splitlines()
    )
    (root / "module.toml").write_text(text, "utf-8")
    with pytest.raises(ManifestError, match=message):
        load_module_manifest(root)


def test_manifest_rejects_unknown_duplicate_and_escaping_paths(tmp_path: Path) -> None:
    root = module(tmp_path, "bad")
    path = root / "module.toml"
    path.write_text(path.read_text("utf-8") + "typo = true\n", "utf-8")
    with pytest.raises(ManifestError, match="unknown"):
        load_module_manifest(root)

    case_root = case(tmp_path / "escape", "escape")
    path = case_root / "case.toml"
    path.write_text(path.read_text("utf-8") + 'entry = "../adapter.py"\n', "utf-8")
    with pytest.raises(ManifestError, match="unsafe"):
        load_case_manifest(case_root)

    root = module(tmp_path, "dupe", dependencies=("dep", "dep"))
    with pytest.raises(ManifestError, match="duplicate"):
        load_module_manifest(root)


def test_case_manifest_strict_nested_match(tmp_path: Path) -> None:
    root = case(
        tmp_path / "case_a",
        "case_a",
        match='[match]\nrequired_files = ["modmain.lua"]\nunknown = true',
    )
    with pytest.raises(ManifestError, match="unknown match"):
        load_case_manifest(root)


def test_state_defaults_enable_disable_and_atomic_file(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    assert store.load() == ExtensionState()
    state = store.enable_module("rpc_capture")
    assert state.enabled_modules == ("rpc_capture",)
    assert state.disabled_modules == ()
    state = store.disable_module("rpc_capture")
    assert state.enabled_modules == ()
    assert state.disabled_modules == ("rpc_capture",)
    state = store.enable_module("rpc_capture")
    assert state.enabled_modules == ("rpc_capture",)
    assert state.disabled_modules == ()
    assert not list(store.path.parent.glob("*.tmp"))
    assert json.loads(store.path.read_text("utf-8"))["schema"] == 1


def test_state_rejects_unknown_overlap_and_non_normalized_path(tmp_path: Path) -> None:
    store = StateStore(tmp_path)
    store.path.parent.mkdir()
    base = {
        "schema": 1,
        "enabled_modules": ["same"],
        "disabled_modules": ["same"],
        "external_cases": {},
    }
    store.path.write_text(json.dumps(base), "utf-8")
    with pytest.raises(StateError, match="both enabled and disabled"):
        store.load()
    base["disabled_modules"] = []
    base["unexpected"] = True
    store.path.write_text(json.dumps(base), "utf-8")
    with pytest.raises(StateError, match="unknown fields"):
        store.load()


def test_external_mount_idempotence_collision_and_unmount(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    external_a = case(tmp_path / "outside" / "external", "external")
    external_b = case(tmp_path / "other" / "external", "external")
    registry = ExtensionRegistry(lab)
    first = registry.mount_case(external_a)
    second = registry.mount_case(external_a)
    assert first == second
    assert registry.discover().cases["external"].source == "external"
    with pytest.raises(RegistryError, match="already mounted"):
        registry.mount_case(external_b)
    registry.unmount_case("external")
    assert "external" not in registry.discover().cases
    assert registry.unmount_case("external") == registry.state_store.load()


def test_external_case_cannot_override_or_unmount_builtin(tmp_path: Path) -> None:
    case(tmp_path / "casepacks" / "built", "built")
    outside = case(tmp_path / "outside" / "built", "built")
    registry = ExtensionRegistry(tmp_path)
    with pytest.raises(RegistryError, match="built-in"):
        registry.mount_case(outside)
    with pytest.raises(RegistryError, match="built-in"):
        registry.unmount_case("built")


def test_state_mapping_key_is_rechecked_against_external_manifest(tmp_path: Path) -> None:
    lab = tmp_path / "lab"
    outside = case(tmp_path / "outside" / "real", "real")
    store = StateStore(lab)
    store.save(
        ExtensionState(
            external_cases={"fake": str(outside.resolve())},
        )
    )
    with pytest.raises(RegistryError, match="does not match manifest id"):
        ExtensionRegistry(lab, store).discover()


def test_case_target_validation_is_explicit_and_checks_hash(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    payload = b"known"
    (target / "modmain.lua").write_bytes(payload)
    digest = hashlib.sha256(payload).hexdigest()
    case(
        tmp_path / "casepacks" / "target_case",
        "target_case",
        match=(
            '[match]\nrequired_files = ["modmain.lua"]\n'
            f'[match.file_hashes]\n"modmain.lua" = ["{digest}"]'
        ),
    )
    registry = ExtensionRegistry(tmp_path)
    unchecked = registry.validate_case("target_case")
    assert not unchecked.target_checked and unchecked.target_matched is None
    checked = registry.validate_case("target_case", target)
    assert checked.target_checked and checked.target_matched is True
    (target / "modmain.lua").write_text("drift", "utf-8")
    assert registry.validate_case("target_case", target).target_matched is False


def test_plan_required_optional_dependency_order_and_no_state_mutation(tmp_path: Path) -> None:
    module(tmp_path, "base", priority=999)
    module(tmp_path, "required", dependencies=("base",), priority=0)
    module(tmp_path, "optional", priority=1)
    case(
        tmp_path / "casepacks" / "target",
        "target",
        required=("required",),
        optional=("optional", "not_installed"),
    )
    registry = ExtensionRegistry(tmp_path)
    state = registry.state_store.load()
    plan = ExtensionPlanner(registry.discover(), state).resolve("target")
    assert plan.dependency_order == ("optional", "base", "required")
    assert plan.management_only is True
    assert plan.unavailable_optional_modules == ("not_installed",)
    assert registry.state_store.load().enabled_modules == ()
    assert plan.to_dict()["management_only"] is True


def test_plan_explicit_disabled_required_and_optional(tmp_path: Path) -> None:
    module(tmp_path, "required")
    module(tmp_path, "optional")
    case(
        tmp_path / "casepacks" / "target",
        "target",
        required=("required",),
        optional=("optional",),
    )
    registry = ExtensionRegistry(tmp_path)
    state = registry.state_store.disable_module("optional")
    plan = ExtensionPlanner(registry.discover(), state).resolve("target")
    assert plan.disabled_optional_modules == ("optional",)
    with pytest.raises(PlannerError, match="requires explicitly disabled"):
        ExtensionPlanner(registry.discover(), state).resolve(
            "target", disabled_modules=("required",)
        )


def test_plan_reports_missing_cycle_and_conflict(tmp_path: Path) -> None:
    missing_lab = tmp_path / "missing"
    module(missing_lab, "a", dependencies=("absent",))
    missing_registry = ExtensionRegistry(missing_lab)
    with pytest.raises(PlannerError, match="missing module dependency"):
        ExtensionPlanner(missing_registry.discover(), ExtensionState()).resolve(
            requested_modules=("a",)
        )

    cycle_lab = tmp_path / "cycle"
    module(cycle_lab, "a", dependencies=("b",))
    module(cycle_lab, "b", dependencies=("a",))
    cycle_registry = ExtensionRegistry(cycle_lab)
    with pytest.raises(PlannerError, match="cycle"):
        ExtensionPlanner(cycle_registry.discover(), ExtensionState()).resolve(
            requested_modules=("a",)
        )

    conflict_lab = tmp_path / "conflict"
    module(conflict_lab, "a", conflicts=("b",))
    module(conflict_lab, "b")
    conflict_registry = ExtensionRegistry(conflict_lab)
    with pytest.raises(PlannerError, match="conflict"):
        ExtensionPlanner(conflict_registry.discover(), ExtensionState()).resolve(
            requested_modules=("a", "b")
        )
