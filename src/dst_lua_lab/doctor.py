from __future__ import annotations

import importlib
import json
import os
import shlex
import subprocess
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Literal, Mapping, Sequence

from .planner import ExtensionPlanner
from .registry import ExtensionRegistry
from .runtime import RUNTIME_MODULES, RuntimeAdapter
from .vfs import InvalidVfsPath, normalize_path


CheckStatus = Literal["pass", "fail", "skip", "warn"]
ScriptsZipSource = Literal["explicit", "environment", "configured", "default"]
RuntimeProbe = Callable[[str], Mapping[str, object]]

REQUIRED_PYTHON = (3, 11)
REQUIRED_RUNTIMES = ("lua51", "luajit20", "luajit21")
REQUIRED_SCRIPTS_MEMBERS = (
    "scripts/class.lua",
    "scripts/constants.lua",
    "scripts/tuning.lua",
    "scripts/strings.lua",
)
REQUIRED_MOD_FILES = ("modinfo.lua", "modmain.lua")


def _json_safe(value: Any) -> Any:
    """Return a value that the standard JSON encoder can always serialize."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_safe(item) for item in value]
    return str(value)


@dataclass(frozen=True, slots=True)
class DoctorCheck:
    """One independently actionable environment diagnostic."""

    id: str
    status: CheckStatus
    summary: str
    details: Mapping[str, object] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status != "fail"

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "ok": self.ok,
            "summary": self.summary,
            "details": _json_safe(self.details),
        }


@dataclass(frozen=True, slots=True)
class SuggestedCommand:
    """A canonical argv plus a shell-friendly rendering for humans."""

    argv: tuple[str, ...]
    display: str

    def to_dict(self) -> dict[str, object]:
        return {"argv": list(self.argv), "display": self.display}


@dataclass(frozen=True, slots=True)
class DoctorReport:
    checks: tuple[DoctorCheck, ...]
    scripts_zip: str
    scripts_zip_source: ScriptsZipSource
    suggested_debug_command: SuggestedCommand | None = None
    schema: int = 1

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        counts = Counter(check.status for check in self.checks)
        value: dict[str, object] = {
            "schema": self.schema,
            "ok": self.ok,
            "summary": {
                "total": len(self.checks),
                "passed": counts["pass"],
                "failed": counts["fail"],
                "skipped": counts["skip"],
                "warnings": counts["warn"],
            },
            "scripts_zip": self.scripts_zip,
            "scripts_zip_source": self.scripts_zip_source,
            "checks": [check.to_dict() for check in self.checks],
            "suggested_debug_command": (
                None
                if self.suggested_debug_command is None
                else self.suggested_debug_command.to_dict()
            ),
        }
        # Keep the JSON-safe contract explicit rather than relying on dataclass
        # fields continuing to contain only primitive values in the future.
        return _json_safe(value)

    def to_json(self, *, indent: int | None = 2) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=indent)


def resolve_scripts_zip(
    lab_root: Path | str, scripts_zip: Path | str | None
) -> tuple[Path, Literal["explicit", "default"]]:
    """Resolve the same default archive location used by ``debug-mod``."""
    root = Path(lab_root).expanduser().resolve()
    if scripts_zip is None:
        return (root.parent / "scripts.zip").resolve(), "default"
    return Path(scripts_zip).expanduser().resolve(), "explicit"


def check_python(version_info: Sequence[int] | None = None) -> DoctorCheck:
    version = tuple(version_info or sys.version_info)
    actual = tuple(int(item) for item in version[:3])
    ok = actual[:2] >= REQUIRED_PYTHON
    required_text = ".".join(str(item) for item in REQUIRED_PYTHON)
    actual_text = ".".join(str(item) for item in actual)
    return DoctorCheck(
        id="python",
        status="pass" if ok else "fail",
        summary=(
            f"Python {actual_text} satisfies >= {required_text}"
            if ok
            else f"Python {actual_text} is too old; >= {required_text} is required"
        ),
        details={"actual": actual_text, "required_minimum": required_text},
    )


def probe_lupa_runtime(runtime_id: str) -> Mapping[str, object]:
    """Import and instantiate a Lupa runtime, proving its native module loads."""
    module_name = RUNTIME_MODULES[runtime_id]
    module = importlib.import_module(module_name)
    factory = getattr(module, "LuaRuntime")
    lua = factory(unpack_returned_tuples=True, encoding=None)
    return RuntimeAdapter.metadata(lua)


def check_lupa_runtimes(
    runtime_ids: Iterable[str] = REQUIRED_RUNTIMES,
    *,
    probe: RuntimeProbe = probe_lupa_runtime,
) -> tuple[DoctorCheck, ...]:
    checks: list[DoctorCheck] = []
    for runtime_id in runtime_ids:
        try:
            metadata = dict(probe(runtime_id))
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    id=f"runtime.{runtime_id}",
                    status="fail",
                    summary=f"Lupa runtime {runtime_id} is unavailable",
                    details={
                        "runtime": runtime_id,
                        "module": RUNTIME_MODULES.get(runtime_id),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    },
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    id=f"runtime.{runtime_id}",
                    status="pass",
                    summary=f"Lupa runtime {runtime_id} loaded successfully",
                    details={
                        "runtime": runtime_id,
                        "module": RUNTIME_MODULES.get(runtime_id),
                        "metadata": metadata,
                    },
                )
            )
    return tuple(checks)


def check_scripts_zip(path: Path | str, *, source: str = "explicit") -> DoctorCheck:
    archive = Path(path).expanduser().resolve()
    details: dict[str, object] = {"path": str(archive), "source": source}
    if not archive.exists():
        return DoctorCheck(
            "scripts_zip",
            "fail",
            "DST scripts archive does not exist",
            details,
        )
    if not archive.is_file():
        return DoctorCheck(
            "scripts_zip",
            "fail",
            "DST scripts archive path is not a file",
            details,
        )
    if not zipfile.is_zipfile(archive):
        return DoctorCheck(
            "scripts_zip",
            "fail",
            "DST scripts archive is not a valid ZIP file",
            details,
        )
    try:
        with zipfile.ZipFile(archive) as bundle:
            members: dict[str, zipfile.ZipInfo] = {}
            invalid_members: list[str] = []
            for info in bundle.infolist():
                if info.is_dir():
                    continue
                try:
                    normalized = normalize_path(info.filename)
                except InvalidVfsPath:
                    invalid_members.append(info.filename)
                    continue
                members.setdefault(normalized, info)
            missing = [name for name in REQUIRED_SCRIPTS_MEMBERS if name not in members]
            if not missing:
                for name in REQUIRED_SCRIPTS_MEMBERS:
                    bundle.read(members[name])
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        details.update({"error_type": type(exc).__name__, "error": str(exc)})
        return DoctorCheck(
            "scripts_zip",
            "fail",
            "DST scripts archive central directory could not be read",
            details,
        )

    details.update(
        {
            "member_count": len(members),
            "required_members": list(REQUIRED_SCRIPTS_MEMBERS),
            "missing_members": missing,
            "invalid_members": invalid_members,
        }
    )
    if missing:
        return DoctorCheck(
            "scripts_zip",
            "fail",
            "DST scripts archive is missing required Lua files",
            details,
        )
    return DoctorCheck(
        "scripts_zip",
        "pass",
        "DST scripts archive is valid and contains the runtime baseline",
        details,
    )


def check_mod_directory(mod: Path | str | None) -> DoctorCheck:
    if mod is None:
        return DoctorCheck(
            "mod",
            "skip",
            "No target MOD was supplied; target checks were skipped",
            {"required_files": list(REQUIRED_MOD_FILES)},
        )
    root = Path(mod).expanduser().resolve()
    details: dict[str, object] = {
        "path": str(root),
        "required_files": list(REQUIRED_MOD_FILES),
    }
    if not root.exists():
        return DoctorCheck("mod", "fail", "Target MOD directory does not exist", details)
    if not root.is_dir():
        return DoctorCheck("mod", "fail", "Target MOD path is not a directory", details)
    missing = [name for name in REQUIRED_MOD_FILES if not (root / name).is_file()]
    details["missing_files"] = missing
    if missing:
        return DoctorCheck(
            "mod", "fail", "Target MOD is missing required entry files", details
        )
    return DoctorCheck(
        "mod", "pass", "Target MOD directory contains modinfo.lua and modmain.lua", details
    )


def check_dependency_directories(
    dependencies: Iterable[Path | str],
) -> tuple[DoctorCheck, ...]:
    checks: list[DoctorCheck] = []
    for index, dependency in enumerate(dependencies):
        root = Path(dependency).expanduser().resolve()
        details = {"index": index, "path": str(root)}
        if not root.exists():
            status: CheckStatus = "fail"
            summary = "Dependency directory does not exist"
        elif not root.is_dir():
            status = "fail"
            summary = "Dependency path is not a directory"
        else:
            status = "pass"
            summary = "Dependency directory is readable"
        checks.append(DoctorCheck(f"dependency.{index}", status, summary, details))
    return tuple(checks)


def check_extension_registry(
    lab_root: Path | str,
    *,
    registry: ExtensionRegistry | None = None,
) -> DoctorCheck:
    root = Path(lab_root).expanduser().resolve()
    registry = registry or ExtensionRegistry(root)
    try:
        catalog = registry.discover()
        state = registry.state_store.load()
        plan = ExtensionPlanner(catalog, state).resolve()
    except Exception as exc:
        return DoctorCheck(
            "extensions",
            "fail",
            "Extension registry or active extension plan is invalid",
            {
                "lab_root": str(root),
                "error_type": type(exc).__name__,
                "error": str(exc),
            },
        )
    return DoctorCheck(
        "extensions",
        "pass",
        "Extension registry and active extension plan are valid",
        {
            "lab_root": str(root),
            "module_count": len(catalog.modules),
            "case_count": len(catalog.cases),
            "enabled_module_count": len(state.enabled_modules),
            "disabled_module_count": len(state.disabled_modules),
            "external_case_count": len(state.external_cases),
            "dependency_order": list(plan.dependency_order),
        },
    )


def _display_command(argv: Sequence[str]) -> str:
    if os.name == "nt":
        return subprocess.list2cmdline(list(argv))
    return shlex.join(argv)


def build_debug_mod_command(
    mod: Path | str,
    scripts_zip: Path | str,
    dependencies: Iterable[Path | str] = (),
    *,
    runtime: str = "luajit20",
    launcher: Sequence[str] = ("python", "dstlab.py"),
) -> SuggestedCommand:
    mod_root = Path(mod).expanduser().resolve()
    archive = Path(scripts_zip).expanduser().resolve()
    argv = [
        *(str(item) for item in launcher),
        "debug-mod",
        "--mod",
        str(mod_root),
        "--scripts-zip",
        str(archive),
        "--runtime",
        runtime,
    ]
    for dependency in dependencies:
        argv.extend(("--dependency", str(Path(dependency).expanduser().resolve())))
    return SuggestedCommand(tuple(argv), _display_command(argv))


def run_doctor(
    lab_root: Path | str,
    *,
    scripts_zip: Path | str | None = None,
    scripts_zip_source: ScriptsZipSource | None = None,
    mod: Path | str | None = None,
    dependencies: Iterable[Path | str] = (),
    runtime: str = "luajit20",
    registry: ExtensionRegistry | None = None,
    version_info: Sequence[int] | None = None,
    runtime_probe: RuntimeProbe = probe_lupa_runtime,
    launcher: Sequence[str] = ("python", "dstlab.py"),
) -> DoctorReport:
    """Run all non-mutating environment diagnostics and return JSON-safe data."""
    root = Path(lab_root).expanduser().resolve()
    archive, resolved_source = resolve_scripts_zip(root, scripts_zip)
    archive_source = scripts_zip_source or resolved_source
    dependency_paths = tuple(dependencies)
    checks = [check_python(version_info)]
    checks.extend(check_lupa_runtimes(probe=runtime_probe))
    checks.append(check_scripts_zip(archive, source=archive_source))
    checks.append(check_mod_directory(mod))
    checks.extend(check_dependency_directories(dependency_paths))
    checks.append(check_extension_registry(root, registry=registry))
    command = (
        build_debug_mod_command(
            mod,
            archive,
            dependency_paths,
            runtime=runtime,
            launcher=launcher,
        )
        if mod is not None and all(check.ok for check in checks)
        else None
    )
    return DoctorReport(
        checks=tuple(checks),
        scripts_zip=str(archive),
        scripts_zip_source=archive_source,
        suggested_debug_command=command,
    )
