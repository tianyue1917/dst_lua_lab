from __future__ import annotations

import argparse
from dataclasses import asdict, is_dataclass
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .config import EXIT_CONFIG_ERROR, EXIT_INTERNAL, EXIT_TIMEOUT, RunConfig
from .manifest import ManifestError, validate_extension_id
from .settings import SettingsStore


_CHECKOUT_ROOT = Path(__file__).resolve().parents[2]
_PACKAGE_IMPORT_ROOT = Path(__file__).resolve().parents[1]


def _installed_lab_home() -> Path:
    explicit = os.environ.get("DSTLAB_HOME")
    if explicit:
        return Path(explicit).expanduser().absolute()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        root = Path(base) if base else Path.home() / "AppData" / "Local"
    else:
        root = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
    return (root / "dst-lua-lab").absolute()


PROJECT_ROOT = (
    _CHECKOUT_ROOT
    if (_CHECKOUT_ROOT / "dstlab.py").is_file()
    else _installed_lab_home()
)
MOD_PROFILES = ("modload", "frontend", "server-sim")
RUNTIME_CHOICES = ("lua51", "luajit20", "luajit21")


def _path_is_reparse_point(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _create_generated_run_dir(kind: str, namespace: str, run_id: str) -> Path:
    raw_root = PROJECT_ROOT.expanduser().absolute()
    if _path_is_reparse_point(raw_root):
        raise ValueError(f"Lab root cannot be a symlink or reparse point: {raw_root}")
    raw_root.mkdir(parents=True, exist_ok=True)
    lab_root = raw_root.resolve()
    base = raw_root / kind
    if _path_is_reparse_point(base):
        raise ValueError(f"generated root cannot be a symlink or reparse point: {base}")
    base.mkdir(exist_ok=True)
    if base.resolve().parent != lab_root:
        raise ValueError(f"generated root escapes Lab root: {base.resolve()}")
    namespace_root = base / namespace
    if _path_is_reparse_point(namespace_root):
        raise ValueError(
            f"generated namespace cannot be a symlink or reparse point: {namespace_root}"
        )
    namespace_root.mkdir(exist_ok=True)
    if namespace_root.resolve().parent != base.resolve():
        raise ValueError(f"generated namespace escapes root: {namespace_root.resolve()}")
    target = namespace_root / run_id
    if os.path.lexists(target):
        raise FileExistsError(f"generated run already exists: {target}")
    target.mkdir()
    return target


def _jsonable(value: Any) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def _default_extension_plan() -> dict[str, Any]:
    return {
        "management_only": True,
        "case": None,
        "modules": [],
        "dependency_order": [],
        "disabled_optional_modules": [],
        "unavailable_optional_modules": [],
    }


def _validate_extension_id(value: str) -> str:
    try:
        validate_extension_id(value, "extension id")
    except ManifestError as exc:
        raise ValueError(str(exc)) from exc
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest().upper()


def make_run_id() -> str:
    return time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:8]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


def launch_worker(config: RunConfig, timeout: float) -> tuple[int, Path]:
    run_id = config.run_id or make_run_id()
    config.run_id = run_id
    namespace = _validate_extension_id(config.case_id) if config.case_id else "_core"
    report_dir = _create_generated_run_dir("reports", namespace, run_id)
    work_dir = _create_generated_run_dir("work", namespace, run_id)
    config.report_dir = str(report_dir)
    config.work_dir = str(work_dir)
    if not config.extension_plan:
        config.extension_plan = _default_extension_plan()
    config.management_only = bool(config.extension_plan.get("management_only", True))
    config.absolute_inputs()
    request_path = work_dir / "request.json"
    write_json(request_path, config.to_json())
    input_evidence: dict[str, Any] = {
        "config": config.to_json(),
        "extension_plan": config.extension_plan,
        "management_only": config.management_only,
    }
    if config.scripts_zip:
        scripts_path = Path(config.scripts_zip)
        with zipfile.ZipFile(scripts_path) as archive:
            input_evidence["scripts_zip"] = {
                "path": str(scripts_path),
                "sha256": file_sha256(scripts_path),
                "entries": len(archive.infolist()),
                "uncompressed_bytes": sum(item.file_size for item in archive.infolist()),
            }
    if config.mod:
        mod_path = Path(config.mod)
        input_evidence["mod"] = {
            "path": str(mod_path),
            "key_files": {
                name: file_sha256(mod_path / name)
                for name in ("modinfo.lua", "modmain.lua")
                if (mod_path / name).is_file()
            },
        }
    write_json(report_dir / "inputs.json", input_evidence)
    for artifact, empty in {
        "modules.json": [],
        "patches.json": [],
        "globals_diff.json": {},
        "hooks.json": [],
        "rpc.json": [],
        "registrations.json": [],
        "mod_config.json": {"source": "unavailable", "values": {}},
        "persistence.json": [],
        "http.json": [],
        "scheduler.json": [],
        "native_calls.json": [],
        "unsupported.json": [],
    }.items():
        write_json(report_dir / artifact, empty)

    env = os.environ.copy()
    # Always re-import the same installed/checkout package in the Worker.
    # Never prepend a user-selected Lab workspace's ``src`` directory.
    src = str(_PACKAGE_IMPORT_ROOT)
    env["PYTHONPATH"] = src
    env["PYTHONSAFEPATH"] = "1"
    command = [
        sys.executable,
        "-P",
        "-m",
        "dst_lua_lab.worker",
        "--request",
        str(request_path),
    ]
    started = time.monotonic()
    try:
        completed = subprocess.run(
            command,
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            cwd=work_dir,
        )
        exit_code = completed.returncode
        stdout, stderr = completed.stdout, completed.stderr
    except subprocess.TimeoutExpired as exc:
        exit_code = EXIT_TIMEOUT
        stdout = exc.stdout or ""
        stderr = (exc.stderr or "") + f"\nworker timed out after {timeout:.3f}s"
        write_json(
            report_dir / "result.json",
            {"status": "timeout", "timeout_seconds": timeout, "exit_code": EXIT_TIMEOUT},
        )
    duration = time.monotonic() - started
    (report_dir / "worker.stdout.txt").write_text(stdout or "", "utf-8")
    (report_dir / "worker.stderr.txt").write_text(stderr or "", "utf-8")
    result_path = report_dir / "result.json"
    result = json.loads(result_path.read_text("utf-8")) if result_path.exists() else {"status": "worker_crash"}
    actual_management_only = bool(result.get("management_only", config.management_only))
    environment = {
        "run_id": run_id,
        "python": sys.version,
        "executable": sys.executable,
        "duration_seconds": duration,
        "exit_code": exit_code,
        "command": command,
        "extension_plan": config.extension_plan,
        "management_only": actual_management_only,
        "plan_management_only": config.management_only,
        "extensions": result.get("extensions"),
    }
    write_json(report_dir / "environment.json", environment)
    summary = [
        f"# DST Lua Lab run `{run_id}`",
        "",
        f"- 结果：`{result.get('status', 'unknown')}`",
        f"- Profile：`{config.profile}`",
        f"- Runtime：`{config.runtime}`",
        f"- Case：`{config.case_id or '_core'}`",
        f"- 扩展计划：`management_only={str(config.management_only).lower()}`",
        f"- 扩展执行：`management_only={str(actual_management_only).lower()}`",
        f"- 返回码：`{exit_code}`",
        f"- 耗时：`{duration:.3f}s`",
        "- 证据边界：Lua 源码为 `MOD_REAL`；宿主时间/userid/随机种子为 `FIXTURE`；动态加载仅 `CAPTURED`。",
        "",
        "## 复现",
        "",
        "```powershell",
        " ".join(f'\"{part}\"' if " " in part else part for part in command),
        "```",
    ]
    (report_dir / "summary.md").write_text("\n".join(summary) + "\n", "utf-8")
    return exit_code, report_dir


def inspect_mod(path: Path) -> int:
    if not path.is_dir():
        print(f"MOD directory not found: {path}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    files = []
    for relative in ("modinfo.lua", "modmain.lua"):
        target = path / relative
        if target.is_file():
            files.append({"path": relative, "size": target.stat().st_size, "sha256": file_sha256(target)})
    script_count = sum(1 for _ in (path / "scripts").rglob("*.lua")) if (path / "scripts").is_dir() else 0
    print(json.dumps({"mod": str(path.resolve()), "key_files": files, "script_lua_count": script_count}, ensure_ascii=False, indent=2))
    return 0


def command_run(args: argparse.Namespace) -> int:
    replay_plan = _load_replay_plan(args.replay_plan)
    replay_requested = args.replay_plan is not None
    if replay_requested and args.profile == "algorithm":
        raise ValueError("--replay-plan requires a MOD profile")
    case_id = args.case
    if case_id is None:
        case_id = {
            "frontend": "frontend_mod_debug",
            "server-sim": "server_sim_debug",
        }.get(args.profile)
    requested_modules = list(args.module or [])
    if replay_requested and "controlled_replay" not in requested_modules:
        requested_modules.append("controlled_replay")
    scripts_zip = args.scripts_zip
    if args.profile in MOD_PROFILES:
        if not args.mod:
            raise ValueError(f"{args.profile} profile requires --mod")
        scripts_zip = str(_debug_scripts_zip(args.scripts_zip))
    if case_id and args.mod:
        _, registry, _ = _extension_services()
        validation = registry.validate_case(case_id, Path(args.mod).resolve())
        if validation.target_matched is False:
            raise ValueError(
                f"target MOD does not match case {case_id!r}: "
                + "; ".join(validation.errors)
            )
        record = registry.discover().cases[case_id]
        if record.manifest.profiles and args.profile not in record.manifest.profiles:
            raise ValueError(
                f"case {case_id!r} does not declare profile {args.profile!r}; "
                f"expected one of {', '.join(record.manifest.profiles)}"
            )
    plan = resolve_extension_plan(case_id, requested_modules, profile=args.profile)
    config = RunConfig(
        profile=args.profile,
        runtime=args.runtime,
        entry=args.entry,
        source=args.source,
        scripts_zip=scripts_zip,
        mod=args.mod,
        dependencies=args.dependency or [],
        userid=args.userid,
        fixed_time=args.fixed_time,
        seed=args.seed,
        case_id=case_id,
        requested_modules=requested_modules,
        replay_plan=replay_plan,
        extension_plan=plan,
        management_only=bool(plan.get("management_only", True)),
    )
    code, report = launch_worker(config, args.timeout)
    print(f"report={report}")
    return code


def _scripts_zip_candidate(explicit: str | None) -> tuple[Path, str]:
    if explicit:
        return Path(explicit).expanduser().resolve(), "explicit"
    environment = os.environ.get("DSTLAB_SCRIPTS_ZIP")
    if environment:
        return Path(environment).expanduser().resolve(), "environment"
    configured = SettingsStore(PROJECT_ROOT).load().scripts_zip
    if configured:
        return Path(configured).expanduser().resolve(), "configured"
    return (PROJECT_ROOT.parent / "scripts.zip").resolve(), "default"


def _debug_scripts_zip(explicit: str | None) -> Path:
    candidate, source = _scripts_zip_candidate(explicit)
    candidate = candidate.resolve()
    if not candidate.is_file():
        raise FileNotFoundError(
            f"DST scripts archive not found ({source}): {candidate}; "
            "configure it with 'dstlab config set-scripts-zip PATH' or pass --scripts-zip PATH"
        )
    if not zipfile.is_zipfile(candidate):
        raise ValueError(f"DST scripts archive is not a valid ZIP file: {candidate}")
    return candidate


def _load_replay_plan(path: str | None) -> list[dict[str, Any]]:
    if path is None:
        return []
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(f"replay plan does not exist or is not a file: {source}")
    if source.stat().st_size > 1024 * 1024:
        raise ValueError(f"replay plan exceeds 1 MiB: {source}")
    try:
        value = json.loads(source.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read replay plan {source}: {exc}") from exc
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError("replay plan must be a JSON array of objects")
    if len(value) > 100:
        raise ValueError("replay plan cannot contain more than 100 operations")
    return value


def command_debug_mod(args: argparse.Namespace) -> int:
    """Run the reusable general Case Pack and print a compact triage summary."""
    mod = Path(args.mod).expanduser().resolve()
    if not mod.is_dir():
        raise FileNotFoundError(f"MOD directory not found: {mod}")
    missing = [name for name in ("modinfo.lua", "modmain.lua") if not (mod / name).is_file()]
    if missing:
        raise ValueError(f"MOD directory is missing required file(s): {', '.join(missing)}")
    scripts_zip = _debug_scripts_zip(args.scripts_zip)
    case_id = {
        "modload": "general_mod_debug",
        "frontend": "frontend_mod_debug",
        "server-sim": "server_sim_debug",
    }[args.profile]
    replay_plan = _load_replay_plan(args.replay_plan)
    requested_modules = ["controlled_replay"] if args.replay_plan is not None else []
    plan = resolve_extension_plan(case_id, requested_modules, profile=args.profile)
    config = RunConfig(
        profile=args.profile,
        runtime=args.runtime,
        scripts_zip=str(scripts_zip),
        mod=str(mod),
        dependencies=args.dependency or [],
        userid=args.userid,
        fixed_time=args.fixed_time,
        seed=args.seed,
        case_id=case_id,
        requested_modules=requested_modules,
        replay_plan=replay_plan,
        extension_plan=plan,
        management_only=bool(plan.get("management_only", True)),
    )
    code, report = launch_worker(config, args.timeout)
    result_path = report / "result.json"
    result = json.loads(result_path.read_text("utf-8")) if result_path.is_file() else {}
    def report_list(name: str) -> list[Any]:
        path = report / name
        value = json.loads(path.read_text("utf-8")) if path.is_file() else []
        return value if isinstance(value, list) else []

    loaded_lua_modules = report_list("modules.json")
    captured_hooks = report_list("hooks.json")
    captured_rpc = report_list("rpc.json")
    captured_registrations = report_list("registrations.json")
    unsupported_path = report / "unsupported.json"
    unsupported = json.loads(unsupported_path.read_text("utf-8")) if unsupported_path.is_file() else []
    if not isinstance(unsupported, list):
        unsupported = []
    extension_report = result.get("extensions") if isinstance(result.get("extensions"), dict) else {}
    loaded_extensions = extension_report.get("loaded_extensions", [])
    if not isinstance(loaded_extensions, list):
        loaded_extensions = []
    diagnostic = {
        "status": result.get("status", "worker_crash"),
        "profile": result.get("profile", args.profile),
        "error_type": result.get("error_type"),
        "message": str(result.get("message", ""))[:500] or None,
        "lua_modules": int(result.get("modules_loaded", len(loaded_lua_modules)) or 0),
        "extensions": len(loaded_extensions),
        "extension_ids": [
            str(item.get("id", "unknown"))
            for item in loaded_extensions
            if isinstance(item, dict)
        ],
        "hooks": int(result.get("hooks_registered", len(captured_hooks)) or 0),
        "rpc": int(result.get("rpc_registered", len(captured_rpc)) or 0),
        "registrations": int(result.get("registrations_captured", len(captured_registrations)) or 0),
        "unsupported": len(unsupported),
        "unsupported_apis": [str(item.get("api", "unknown")) for item in unsupported[:5] if isinstance(item, dict)],
    }
    print(f"report={report}")
    print("diagnostic=" + json.dumps(diagnostic, ensure_ascii=False, separators=(",", ":")))
    return code


def _extension_services():
    # Imported only by the management plane. Manifest discovery never imports
    # extension entry points; Worker loading is deliberately a later phase.
    from .planner import ExtensionPlanner
    from .registry import ExtensionRegistry
    from .state import StateStore

    store = StateStore(PROJECT_ROOT)
    registry = ExtensionRegistry(
        PROJECT_ROOT, state_store=store, include_packaged=True
    )
    return store, registry, ExtensionPlanner


def resolve_extension_plan(
    case_id: str | None,
    requested_modules: list[str],
    *,
    profile: str | None = None,
) -> dict[str, Any]:
    if case_id:
        _validate_extension_id(case_id)
    for module_id in requested_modules:
        _validate_extension_id(module_id)
    store, registry, planner_type = _extension_services()
    catalog = registry.discover()
    state = store.load()
    plan = planner_type(catalog, state).resolve(case_id=case_id, requested_modules=requested_modules)
    if profile is not None:
        if case_id is not None:
            declared = catalog.cases[case_id].manifest.profiles
            if declared and profile not in declared:
                raise ValueError(
                    f"case {case_id!r} does not support profile {profile!r}; "
                    f"expected one of {', '.join(declared)}"
                )
        for item in plan.modules:
            declared = catalog.modules[item.id].manifest.profiles
            if declared and profile not in declared:
                raise ValueError(
                    f"module {item.id!r} does not support profile {profile!r}; "
                    f"expected one of {', '.join(declared)}"
                )
    value = _jsonable(plan.to_dict())
    # Phase one is management-plane only. Do not imply that an entry was loaded.
    value["management_only"] = True
    return value


def _record_summary(
    record: Any, *, enabled: bool | None = None, disabled: bool | None = None
) -> dict[str, Any]:
    manifest = record.manifest
    result = {
        "id": manifest.id,
        "name": manifest.name,
        "version": manifest.version,
        "root": str(record.root),
        "source": record.source,
        "manifest": str(record.manifest_path),
        "manifest_sha256": record.manifest_sha256,
        "management_only": True,
    }
    if enabled is not None:
        result["enabled"] = enabled
    if disabled is not None:
        result["disabled"] = disabled
    return result


def command_module(args: argparse.Namespace) -> int:
    if args.module_command == "init":
        from .scaffold import create_module

        module_id = _validate_extension_id(args.module_id)
        _, registry, _ = _extension_services()
        if module_id in registry.discover().modules:
            raise ValueError(f"module id is already reserved: {module_id}")
        PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
        files = create_module(PROJECT_ROOT, module_id)
        print(json.dumps({"id": module_id, "created": files}, ensure_ascii=False, indent=2))
        return 0
    store, registry, planner_type = _extension_services()
    if args.module_command == "doctor":
        try:
            catalog = registry.discover()
            plan = planner_type(catalog, store.load()).resolve()
            output = {
                "ok": True,
                "management_only": True,
                "module_count": len(catalog.modules),
                "case_count": len(catalog.cases),
                "extension_plan": _jsonable(plan.to_dict()),
                "errors": [],
            }
            output["extension_plan"]["management_only"] = True
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0
        except Exception as exc:
            print(json.dumps({"ok": False, "management_only": True, "errors": [str(exc)]}, ensure_ascii=False, indent=2))
            return EXIT_CONFIG_ERROR

    catalog = registry.discover()
    state = store.load()
    if args.module_command == "list":
        items = [
            _record_summary(
                record,
                enabled=module_id in state.enabled_modules,
                disabled=module_id in state.disabled_modules,
            )
            for module_id, record in sorted(catalog.modules.items())
        ]
        print(json.dumps({"management_only": True, "modules": items}, ensure_ascii=False, indent=2))
        return 0
    module_id = _validate_extension_id(args.module_id)
    if module_id not in catalog.modules:
        raise ValueError(f"unknown module: {module_id}")
    new_state = registry.enable_module(module_id) if args.module_command == "enable" else registry.disable_module(module_id)
    print(
        json.dumps(
            {
                "id": module_id,
                "enabled": module_id in new_state.enabled_modules,
                "disabled": module_id in new_state.disabled_modules,
                "management_only": True,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


def _generated_namespace(kind: str, case_id: str) -> Path:
    case_id = _validate_extension_id(case_id)
    lab_root = PROJECT_ROOT.resolve()
    base_path = PROJECT_ROOT / kind
    if _is_reparse_point(base_path):
        raise ValueError(f"refusing to clean through reparse-point root: {base_path}")
    base = base_path.resolve()
    if base.parent != lab_root:
        raise ValueError(f"generated root escapes Lab root: {base}")
    candidate = base_path / case_id
    # Resolve before recursive deletion. A namespace symlink is rejected even
    # when it happens to point back inside the Lab, keeping the policy simple.
    if candidate.is_symlink():
        raise ValueError(f"refusing to clean symlink namespace: {candidate}")
    resolved = candidate.resolve(strict=False)
    if resolved.parent != base or not resolved.is_relative_to(base):
        raise ValueError(f"refusing to clean path outside {base}: {resolved}")
    return candidate


def _is_reparse_point(path: Path) -> bool:
    return _path_is_reparse_point(path)


def _assert_no_reparse_points(root: Path) -> None:
    if _is_reparse_point(root):
        raise ValueError(f"refusing to recursively clean reparse point: {root}")
    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            item = Path(current) / name
            if _is_reparse_point(item):
                raise ValueError(f"refusing to recursively clean tree containing reparse point: {item}")


def clean_case_generated(case_id: str) -> list[str]:
    removed: list[str] = []
    for kind in ("work", "reports"):
        target = _generated_namespace(kind, case_id)
        if target.exists():
            if not target.is_dir():
                raise ValueError(f"generated namespace is not a directory: {target}")
            _assert_no_reparse_points(target)
            shutil.rmtree(target)
            removed.append(str(target))
    return removed


def command_case(args: argparse.Namespace) -> int:
    from .manifest import load_case_manifest

    if args.case_command == "init":
        from .scaffold import create_case

        case_id = _validate_extension_id(args.case_id)
        _, registry, _ = _extension_services()
        if case_id in registry.discover().cases:
            raise ValueError(f"case id is already reserved: {case_id}")
        PROJECT_ROOT.mkdir(parents=True, exist_ok=True)
        files = create_case(PROJECT_ROOT, case_id)
        print(json.dumps({"id": case_id, "created": files}, ensure_ascii=False, indent=2))
        return 0
    store, registry, planner_type = _extension_services()
    if args.case_command == "mount":
        root = Path(args.path).resolve()
        manifest = load_case_manifest(root)
        state = registry.mount_case(root)
        print(
            json.dumps(
                {
                    "id": manifest.id,
                    "root": str(root),
                    "mounted": manifest.id in state.external_cases,
                    "management_only": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0

    catalog = registry.discover()
    if args.case_command == "list":
        items = [_record_summary(record) for _, record in sorted(catalog.cases.items())]
        print(json.dumps({"management_only": True, "cases": items}, ensure_ascii=False, indent=2))
        return 0
    case_id = _validate_extension_id(args.case_id)
    if args.case_command == "validate":
        validation = registry.validate_case(case_id, Path(args.mod).resolve() if args.mod else None)
        plan = planner_type(catalog, store.load()).resolve(case_id=case_id)
        value = _jsonable(plan.to_dict())
        value["management_only"] = True
        valid = validation.manifest_valid and validation.target_matched is not False
        print(
            json.dumps(
                {"valid": valid, "validation": _jsonable(validation), "extension_plan": value},
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0 if valid else EXIT_CONFIG_ERROR
    if args.case_command == "test":
        if case_id not in catalog.cases:
            raise ValueError(f"unknown case: {case_id}")
        validation = registry.validate_case(case_id)
        planner_type(catalog, store.load()).resolve(case_id=case_id)
        tests_dir = catalog.cases[case_id].root / "tests"
        if not tests_dir.is_dir():
            raise ValueError(f"case has no tests directory: {tests_dir}")
        env = os.environ.copy()
        src = str(_PACKAGE_IMPORT_ROOT)
        env["PYTHONPATH"] = src
        env["PYTHONSAFEPATH"] = "1"
        completed = subprocess.run([sys.executable, "-m", "pytest", "-q", str(tests_dir)], cwd=PROJECT_ROOT, env=env)
        if not validation.manifest_valid:
            return EXIT_CONFIG_ERROR
        return completed.returncode
    if args.case_command == "clean":
        if case_id not in catalog.cases:
            raise ValueError(f"unknown case: {case_id}")
        removed = clean_case_generated(case_id)
        print(json.dumps({"id": case_id, "removed": removed, "management_only": True}, ensure_ascii=False, indent=2))
        return 0
    if args.case_command == "unmount":
        record = catalog.cases.get(case_id)
        if record is not None and record.source in {"builtin", "packaged"}:
            raise ValueError(f"cannot unmount built-in case: {case_id}")
        removed = clean_case_generated(case_id) if args.purge_generated else []
        new_state = registry.unmount_case(case_id)
        print(
            json.dumps(
                {
                    "id": case_id,
                    "mounted": case_id in new_state.external_cases,
                    "removed": removed,
                    "management_only": True,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    return EXIT_CONFIG_ERROR


def command_diff(args: argparse.Namespace) -> int:
    outputs: dict[str, Any] = {}
    final_code = 0
    for runtime in args.runtime.split(","):
        config = RunConfig(profile="algorithm", runtime=runtime.strip(), entry=args.entry, source=args.source)
        code, report = launch_worker(config, args.timeout)
        result_path = report / "result.json"
        outputs[runtime.strip()] = {
            "exit_code": code,
            "report": str(report),
            "result": json.loads(result_path.read_text("utf-8")) if result_path.exists() else None,
        }
        final_code = final_code or code
    comparable = [json.dumps(value["result"].get("result"), sort_keys=True) for value in outputs.values() if value["result"]]
    output = {"equal": len(set(comparable)) <= 1, "runs": outputs}
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return final_code if final_code else (0 if output["equal"] else 5)


def command_missing(args: argparse.Namespace) -> int:
    report = Path(args.report)
    unsupported = report / "unsupported.json"
    if unsupported.exists():
        print(unsupported.read_text("utf-8"))
    else:
        print("[]")
    return 0


def command_doctor(args: argparse.Namespace) -> int:
    from .doctor import run_doctor

    archive, source = _scripts_zip_candidate(args.scripts_zip)
    _, registry, _ = _extension_services()
    report = run_doctor(
        PROJECT_ROOT,
        scripts_zip=archive,
        scripts_zip_source=source,
        mod=args.mod,
        dependencies=args.dependency or [],
        runtime=args.runtime,
        registry=registry,
        launcher=("python", "dstlab.py")
        if (PROJECT_ROOT / "dstlab.py").is_file()
        else ("dstlab",),
    )
    if args.json:
        print(report.to_json())
    else:
        for check in report.checks:
            print(f"[{check.status.upper():4}] {check.id}: {check.summary}")
        if report.suggested_debug_command is not None:
            print("suggested=" + report.suggested_debug_command.display)
        print(f"doctor_ok={str(report.ok).lower()}")
    return 0 if report.ok else EXIT_CONFIG_ERROR


def command_config(args: argparse.Namespace) -> int:
    store = SettingsStore(PROJECT_ROOT)
    if args.config_command == "show":
        settings = store.load()
    elif args.config_command == "set-scripts-zip":
        archive = _debug_scripts_zip(args.path)
        settings = store.set_scripts_zip(archive)
    elif args.config_command == "clear-scripts-zip":
        settings = store.clear_scripts_zip()
    else:
        return EXIT_CONFIG_ERROR
    print(json.dumps(settings.to_dict(), ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dstlab")
    sub = parser.add_subparsers(dest="command", required=True)
    inspect = sub.add_parser("inspect-mod")
    inspect.add_argument("--mod", required=True)

    debug = sub.add_parser("debug-mod", help="debug a MOD with the general_mod_debug Case Pack")
    debug.add_argument("--mod", required=True)
    debug.add_argument("--profile", default="modload", choices=MOD_PROFILES)
    debug.add_argument("--scripts-zip")
    debug.add_argument("--replay-plan")
    debug.add_argument("--dependency", action="append")
    debug.add_argument("--runtime", default="luajit20", choices=RUNTIME_CHOICES)
    debug.add_argument("--userid", default="KU_OFFLINE")
    debug.add_argument("--fixed-time", default="2099-01-01T00:00:00Z")
    debug.add_argument("--seed", type=int, default=12345)
    debug.add_argument("--timeout", type=float, default=10.0)

    run = sub.add_parser("run")
    run.add_argument("--profile", default="algorithm", choices=["algorithm", *MOD_PROFILES])
    run.add_argument("--runtime", default="luajit20", choices=RUNTIME_CHOICES)
    run.add_argument("--entry")
    run.add_argument("--source")
    run.add_argument("--scripts-zip")
    run.add_argument("--mod")
    run.add_argument("--dependency", action="append")
    run.add_argument("--case")
    run.add_argument("--module", action="append")
    run.add_argument("--replay-plan")
    run.add_argument("--userid", default="KU_OFFLINE")
    run.add_argument("--fixed-time", default="2099-01-01T00:00:00Z")
    run.add_argument("--seed", type=int, default=12345)
    run.add_argument("--timeout", type=float, default=10.0)

    diff = sub.add_parser("diff-runtime")
    diff.add_argument("--runtime", default="lua51,luajit20,luajit21")
    diff.add_argument("--entry")
    diff.add_argument("--source")
    diff.add_argument("--timeout", type=float, default=10.0)

    missing = sub.add_parser("list-missing-api")
    missing.add_argument("--report", required=True)

    doctor = sub.add_parser("doctor", help="check runtimes, scripts.zip, MOD inputs, and extensions")
    doctor.add_argument("--scripts-zip")
    doctor.add_argument("--mod")
    doctor.add_argument("--dependency", action="append")
    doctor.add_argument("--runtime", default="luajit20", choices=RUNTIME_CHOICES)
    doctor.add_argument("--json", action="store_true")

    config = sub.add_parser("config", help="manage local untracked Lab settings")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_sub.add_parser("show")
    config_set_scripts = config_sub.add_parser("set-scripts-zip")
    config_set_scripts.add_argument("path")
    config_sub.add_parser("clear-scripts-zip")

    module = sub.add_parser("module")
    module_sub = module.add_subparsers(dest="module_command", required=True)
    module_sub.add_parser("list")
    module_enable = module_sub.add_parser("enable")
    module_enable.add_argument("module_id")
    module_disable = module_sub.add_parser("disable")
    module_disable.add_argument("module_id")
    module_sub.add_parser("doctor")
    module_init = module_sub.add_parser("init")
    module_init.add_argument("module_id")

    case = sub.add_parser("case")
    case_sub = case.add_subparsers(dest="case_command", required=True)
    case_sub.add_parser("list")
    case_init = case_sub.add_parser("init")
    case_init.add_argument("case_id")
    case_mount = case_sub.add_parser("mount")
    case_mount.add_argument("path")
    case_validate = case_sub.add_parser("validate")
    case_validate.add_argument("case_id")
    case_validate.add_argument("--mod")
    case_test = case_sub.add_parser("test")
    case_test.add_argument("case_id")
    case_clean = case_sub.add_parser("clean")
    case_clean.add_argument("case_id")
    case_unmount = case_sub.add_parser("unmount")
    case_unmount.add_argument("case_id")
    case_unmount.add_argument("--purge-generated", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "inspect-mod":
            return inspect_mod(Path(args.mod))
        if args.command == "debug-mod":
            return command_debug_mod(args)
        if args.command == "run":
            return command_run(args)
        if args.command == "diff-runtime":
            return command_diff(args)
        if args.command == "list-missing-api":
            return command_missing(args)
        if args.command == "doctor":
            return command_doctor(args)
        if args.command == "config":
            return command_config(args)
        if args.command == "module":
            return command_module(args)
        if args.command == "case":
            return command_case(args)
        return EXIT_CONFIG_ERROR
    except (ValueError, FileNotFoundError) as exc:
        print(f"configuration error: {exc}", file=sys.stderr)
        return EXIT_CONFIG_ERROR
    except Exception:
        import traceback

        traceback.print_exc()
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
