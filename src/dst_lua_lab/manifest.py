from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping


_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_MODULE_FIELDS = {
    "schema",
    "id",
    "name",
    "version",
    "api_version",
    "priority",
    "dependencies",
    "conflicts",
    "profiles",
    "entry",
}
_CASE_FIELDS = {
    "schema",
    "id",
    "name",
    "version",
    "api_version",
    "workshop_id",
    "required_modules",
    "optional_modules",
    "profiles",
    "entry",
    "match",
}
_REQUIRED_FIELDS = {"schema", "id", "name", "version", "api_version"}


class ManifestError(ValueError):
    """A manifest is malformed or unsafe to use."""


def validate_extension_id(value: str, field: str = "id") -> str:
    """Validate and return an extension identifier."""
    if type(value) is not str:
        raise ManifestError(f"{field} must be a string")
    if not _ID_RE.fullmatch(value):
        raise ManifestError(
            f"invalid extension id for {field}: {value!r}; expected "
            "[a-z0-9][a-z0-9._-]{0,63}"
        )
    return value


@dataclass(frozen=True, slots=True)
class ModuleManifest:
    schema: int
    id: str
    name: str
    version: str
    api_version: str
    priority: int = 100
    dependencies: tuple[str, ...] = ()
    conflicts: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    entry: str | None = None


@dataclass(frozen=True, slots=True)
class CaseMatch:
    required_files: tuple[str, ...] = ()
    file_hashes: Mapping[str, tuple[str, ...]] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class CaseManifest:
    schema: int
    id: str
    name: str
    version: str
    api_version: str
    workshop_id: str | None = None
    required_modules: tuple[str, ...] = ()
    optional_modules: tuple[str, ...] = ()
    profiles: tuple[str, ...] = ()
    entry: str | None = None
    match: CaseMatch = CaseMatch()


def _load_toml(path: Path) -> dict[str, Any]:
    try:
        with path.open("rb") as stream:
            value = tomllib.load(stream)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    if not isinstance(value, dict):  # defensive; tomllib currently always returns dict
        raise ManifestError(f"manifest root must be a table: {path}")
    return value


def _check_common(data: dict[str, Any], allowed: set[str], root: Path) -> None:
    missing = sorted(_REQUIRED_FIELDS - data.keys())
    unknown = sorted(data.keys() - allowed)
    if missing:
        raise ManifestError(f"missing required fields: {', '.join(missing)}")
    if unknown:
        raise ManifestError(f"unknown manifest fields: {', '.join(unknown)}")
    if type(data["schema"]) is not int or data["schema"] != 1:
        raise ManifestError(f"unsupported manifest schema: {data['schema']!r}")
    if type(data["api_version"]) is not str or data["api_version"] != "1":
        raise ManifestError(f"unsupported extension api_version: {data['api_version']!r}")
    extension_id = _string(data, "id")
    _check_id(extension_id, "id")
    if root.name != extension_id:
        raise ManifestError(
            f"manifest id {extension_id!r} does not match directory {root.name!r}"
        )
    _nonempty_string(data, "name")
    _nonempty_string(data, "version")


def _check_id(value: str, field: str) -> None:
    if not _ID_RE.fullmatch(value):
        raise ManifestError(
            f"{field} must match [a-z0-9][a-z0-9._-]{{0,63}}: {value!r}"
        )


def _string(data: Mapping[str, Any], field: str) -> str:
    value = data.get(field)
    if type(value) is not str:
        raise ManifestError(f"{field} must be a string")
    return value


def _nonempty_string(data: Mapping[str, Any], field: str) -> str:
    value = _string(data, field)
    if not value.strip():
        raise ManifestError(f"{field} must not be empty")
    return value


def _optional_string(data: Mapping[str, Any], field: str) -> str | None:
    if field not in data:
        return None
    return _nonempty_string(data, field)


def _id_list(data: Mapping[str, Any], field: str) -> tuple[str, ...]:
    values = data.get(field, [])
    if type(values) is not list:
        raise ManifestError(f"{field} must be an array")
    result: list[str] = []
    for value in values:
        if type(value) is not str:
            raise ManifestError(f"{field} items must be strings")
        _check_id(value, f"{field} item")
        if value in result:
            raise ManifestError(f"{field} contains duplicate item: {value}")
        result.append(value)
    return tuple(result)


def _string_list(data: Mapping[str, Any], field: str) -> tuple[str, ...]:
    values = data.get(field, [])
    if type(values) is not list:
        raise ManifestError(f"{field} must be an array")
    result: list[str] = []
    for value in values:
        if type(value) is not str or not value.strip():
            raise ManifestError(f"{field} items must be non-empty strings")
        if value in result:
            raise ManifestError(f"{field} contains duplicate item: {value}")
        result.append(value)
    return tuple(result)


def _relative_path(value: str, field: str) -> str:
    if "\\" in value:
        raise ManifestError(f"{field} must use portable '/' separators: {value!r}")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ":" in path.parts[0]:
        raise ManifestError(f"{field} must be a relative path: {value!r}")
    if any(part in ("", ".", "..") for part in path.parts):
        raise ManifestError(f"{field} contains an unsafe segment: {value!r}")
    return path.as_posix()


def _entry(data: Mapping[str, Any]) -> str | None:
    value = _optional_string(data, "entry")
    return None if value is None else _relative_path(value, "entry")


def load_module_manifest(root: Path | str) -> ModuleManifest:
    root = Path(root).resolve()
    data = _load_toml(root / "module.toml")
    _check_common(data, _MODULE_FIELDS, root)
    priority = data.get("priority", 100)
    if type(priority) is not int or not 0 <= priority <= 10_000:
        raise ManifestError("priority must be an integer in range 0..10000")
    dependencies = _id_list(data, "dependencies")
    conflicts = _id_list(data, "conflicts")
    overlap = set(dependencies) & set(conflicts)
    if overlap:
        raise ManifestError(f"dependencies also listed as conflicts: {sorted(overlap)!r}")
    extension_id = _string(data, "id")
    if extension_id in dependencies or extension_id in conflicts:
        raise ManifestError("module cannot depend on or conflict with itself")
    return ModuleManifest(
        schema=1,
        id=extension_id,
        name=_nonempty_string(data, "name"),
        version=_nonempty_string(data, "version"),
        api_version="1",
        priority=priority,
        dependencies=dependencies,
        conflicts=conflicts,
        profiles=_string_list(data, "profiles"),
        entry=_entry(data),
    )


def _load_match(value: Any) -> CaseMatch:
    if value is None:
        return CaseMatch()
    if type(value) is not dict:
        raise ManifestError("match must be a table")
    unknown = sorted(value.keys() - {"required_files", "file_hashes"})
    if unknown:
        raise ManifestError(f"unknown match fields: {', '.join(unknown)}")
    files = tuple(
        _relative_path(item, "match.required_files item")
        for item in _string_list(value, "required_files")
    )
    raw_hashes = value.get("file_hashes", {})
    if type(raw_hashes) is not dict:
        raise ManifestError("match.file_hashes must be a table")
    hashes: dict[str, tuple[str, ...]] = {}
    for raw_path, raw_values in raw_hashes.items():
        if type(raw_path) is not str:
            raise ManifestError("match.file_hashes keys must be paths")
        path = _relative_path(raw_path, "match.file_hashes key")
        values = _string_list({"value": raw_values}, "value")
        hashes[path] = values
    return CaseMatch(files, MappingProxyType(hashes))


def load_case_manifest(root: Path | str) -> CaseManifest:
    root = Path(root).resolve()
    data = _load_toml(root / "case.toml")
    _check_common(data, _CASE_FIELDS, root)
    required = _id_list(data, "required_modules")
    optional = _id_list(data, "optional_modules")
    overlap = set(required) & set(optional)
    if overlap:
        raise ManifestError(f"modules cannot be both required and optional: {sorted(overlap)!r}")
    workshop_id = _optional_string(data, "workshop_id")
    return CaseManifest(
        schema=1,
        id=_string(data, "id"),
        name=_nonempty_string(data, "name"),
        version=_nonempty_string(data, "version"),
        api_version="1",
        workshop_id=workshop_id,
        required_modules=required,
        optional_modules=optional,
        profiles=_string_list(data, "profiles"),
        entry=_entry(data),
        match=_load_match(data.get("match")),
    )
