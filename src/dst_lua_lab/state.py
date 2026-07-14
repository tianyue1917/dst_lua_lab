from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping

from .manifest import ManifestError, validate_extension_id


class StateError(ValueError):
    """The local extension state is malformed or cannot be updated safely."""


@dataclass(frozen=True, slots=True)
class ExtensionState:
    schema: int = 1
    enabled_modules: tuple[str, ...] = ()
    disabled_modules: tuple[str, ...] = ()
    external_cases: Mapping[str, str] = field(
        default_factory=lambda: MappingProxyType({})
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "enabled_modules": list(self.enabled_modules),
            "disabled_modules": list(self.disabled_modules),
            "external_cases": dict(self.external_cases),
        }


class StateStore:
    def __init__(self, lab_root: Path | str, path: Path | str | None = None) -> None:
        self.lab_root = Path(lab_root).resolve()
        self.path = (
            Path(path).resolve()
            if path is not None
            else self.lab_root / ".dstlab" / "state.json"
        )

    def load(self) -> ExtensionState:
        if not self.path.exists():
            return ExtensionState()
        try:
            value = json.loads(self.path.read_text("utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise StateError(f"cannot read extension state {self.path}: {exc}") from exc
        if type(value) is not dict:
            raise StateError("extension state root must be an object")
        allowed = {"schema", "enabled_modules", "disabled_modules", "external_cases"}
        unknown = sorted(value.keys() - allowed)
        missing = sorted(allowed - value.keys())
        if missing:
            raise StateError(f"extension state missing fields: {', '.join(missing)}")
        if unknown:
            raise StateError(f"extension state has unknown fields: {', '.join(unknown)}")
        if type(value["schema"]) is not int or value["schema"] != 1:
            raise StateError(f"unsupported extension state schema: {value['schema']!r}")
        enabled = self._module_list(value["enabled_modules"], "enabled_modules")
        disabled = self._module_list(value["disabled_modules"], "disabled_modules")
        overlap = set(enabled) & set(disabled)
        if overlap:
            raise StateError(f"modules are both enabled and disabled: {sorted(overlap)!r}")
        raw_cases = value["external_cases"]
        if type(raw_cases) is not dict:
            raise StateError("external_cases must be an object")
        cases: dict[str, str] = {}
        for case_id, raw_path in raw_cases.items():
            try:
                validate_extension_id(case_id, "external case id")
            except ManifestError as exc:
                raise StateError(str(exc)) from exc
            if type(raw_path) is not str or not raw_path:
                raise StateError(f"external case path for {case_id!r} must be a string")
            path = Path(raw_path)
            if not path.is_absolute():
                raise StateError(f"external case path must be absolute: {raw_path!r}")
            normalized = str(path.resolve())
            if normalized != raw_path:
                raise StateError(
                    f"external case path is not normalized: {raw_path!r} != {normalized!r}"
                )
            cases[case_id] = normalized
        return ExtensionState(1, enabled, disabled, MappingProxyType(cases))

    @staticmethod
    def _module_list(value: object, field_name: str) -> tuple[str, ...]:
        if type(value) is not list:
            raise StateError(f"{field_name} must be an array")
        result: list[str] = []
        for item in value:
            try:
                validate_extension_id(item, f"{field_name} item")  # type: ignore[arg-type]
            except ManifestError as exc:
                raise StateError(str(exc)) from exc
            if item in result:
                raise StateError(f"{field_name} contains duplicate item: {item}")
            result.append(item)  # type: ignore[arg-type]
        return tuple(sorted(result))

    def save(self, state: ExtensionState) -> None:
        payload = json.dumps(
            state.to_dict(), ensure_ascii=False, indent=2, sort_keys=True
        ) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise StateError(f"cannot atomically write extension state: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink()
                except OSError:
                    pass

    def enable_module(self, module_id: str) -> ExtensionState:
        validate_extension_id(module_id, "module id")
        state = self.load()
        enabled = set(state.enabled_modules)
        disabled = set(state.disabled_modules)
        enabled.add(module_id)
        disabled.discard(module_id)
        updated = ExtensionState(
            enabled_modules=tuple(sorted(enabled)),
            disabled_modules=tuple(sorted(disabled)),
            external_cases=state.external_cases,
        )
        if updated != state:
            self.save(updated)
        return updated

    def disable_module(self, module_id: str) -> ExtensionState:
        validate_extension_id(module_id, "module id")
        state = self.load()
        enabled = set(state.enabled_modules)
        disabled = set(state.disabled_modules)
        enabled.discard(module_id)
        disabled.add(module_id)
        updated = ExtensionState(
            enabled_modules=tuple(sorted(enabled)),
            disabled_modules=tuple(sorted(disabled)),
            external_cases=state.external_cases,
        )
        if updated != state:
            self.save(updated)
        return updated

    def mount_case(self, case_id: str, root: Path | str) -> ExtensionState:
        validate_extension_id(case_id, "case id")
        normalized = str(Path(root).resolve())
        state = self.load()
        cases = dict(state.external_cases)
        current = cases.get(case_id)
        if current is not None and current != normalized:
            raise StateError(
                f"case {case_id!r} is already mounted from a different path: {current}"
            )
        for other_id, other_path in cases.items():
            if other_path == normalized and other_id != case_id:
                raise StateError(
                    f"path {normalized!r} is already mounted as case {other_id!r}"
                )
        cases[case_id] = normalized
        updated = ExtensionState(
            enabled_modules=state.enabled_modules,
            disabled_modules=state.disabled_modules,
            external_cases=MappingProxyType(cases),
        )
        if updated != state:
            self.save(updated)
        return updated

    def unmount_case(self, case_id: str) -> ExtensionState:
        validate_extension_id(case_id, "case id")
        state = self.load()
        if case_id not in state.external_cases:
            return state
        cases = dict(state.external_cases)
        del cases[case_id]
        updated = ExtensionState(
            enabled_modules=state.enabled_modules,
            disabled_modules=state.disabled_modules,
            external_cases=MappingProxyType(cases),
        )
        self.save(updated)
        return updated
