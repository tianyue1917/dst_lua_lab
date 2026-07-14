from __future__ import annotations

import heapq
from dataclasses import dataclass
from pathlib import Path

from .manifest import ManifestError, validate_extension_id
from .registry import DiscoveredCase, DiscoveredModule, ExtensionCatalog
from .state import ExtensionState


class PlannerError(ValueError):
    """An extension plan cannot be resolved safely."""


@dataclass(frozen=True, slots=True)
class PlannedModule:
    id: str
    name: str
    version: str
    api_version: str
    priority: int
    dependencies: tuple[str, ...]
    reasons: tuple[str, ...]
    root: Path
    source: str
    manifest_path: Path
    manifest_sha256: str
    entry_path: Path | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "priority": self.priority,
            "dependencies": list(self.dependencies),
            "reasons": list(self.reasons),
            "root": str(self.root),
            "source": self.source,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "entry_path": None if self.entry_path is None else str(self.entry_path),
        }


@dataclass(frozen=True, slots=True)
class PlannedCase:
    id: str
    name: str
    version: str
    api_version: str
    root: Path
    source: str
    manifest_path: Path
    manifest_sha256: str
    entry_path: Path | None

    def to_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "version": self.version,
            "api_version": self.api_version,
            "root": str(self.root),
            "source": self.source,
            "manifest_path": str(self.manifest_path),
            "manifest_sha256": self.manifest_sha256,
            "entry_path": None if self.entry_path is None else str(self.entry_path),
        }


@dataclass(frozen=True, slots=True)
class ExtensionPlan:
    modules: tuple[PlannedModule, ...]
    case: PlannedCase | None = None
    disabled_optional_modules: tuple[str, ...] = ()
    unavailable_optional_modules: tuple[str, ...] = ()
    management_only: bool = True

    @property
    def dependency_order(self) -> tuple[str, ...]:
        return tuple(item.id for item in self.modules)

    def to_dict(self) -> dict[str, object]:
        return {
            "management_only": self.management_only,
            "case": None if self.case is None else self.case.to_dict(),
            "modules": [item.to_dict() for item in self.modules],
            "dependency_order": list(self.dependency_order),
            "disabled_optional_modules": list(self.disabled_optional_modules),
            "unavailable_optional_modules": list(self.unavailable_optional_modules),
        }

    # Config and report code historically calls its JSON-safe methods ``to_json``.
    def to_json(self) -> dict[str, object]:
        return self.to_dict()


class ExtensionPlanner:
    def __init__(self, catalog: ExtensionCatalog, state: ExtensionState) -> None:
        self.catalog = catalog
        self.state = state

    def resolve(
        self,
        case_id: str | None = None,
        requested_modules: tuple[str, ...] | list[str] = (),
        disabled_modules: tuple[str, ...] | list[str] = (),
    ) -> ExtensionPlan:
        requested = self._ids(requested_modules, "requested module")
        run_disabled = self._ids(disabled_modules, "disabled module")
        disabled = set(self.state.disabled_modules) | set(run_disabled)
        reasons: dict[str, set[str]] = {}

        for module_id in self.state.enabled_modules:
            self._select(module_id, "user", reasons, disabled)
        for module_id in requested:
            self._select(module_id, "requested", reasons, disabled)

        case_record: DiscoveredCase | None = None
        disabled_optional: list[str] = []
        unavailable_optional: list[str] = []
        if case_id is not None:
            try:
                validate_extension_id(case_id, "case id")
            except ManifestError as exc:
                raise PlannerError(str(exc)) from exc
            case_record = self.catalog.cases.get(case_id)
            if case_record is None:
                raise PlannerError(f"unknown case: {case_id}")
            for module_id in case_record.manifest.required_modules:
                if module_id in disabled:
                    raise PlannerError(
                        f"case {case_id!r} requires explicitly disabled module {module_id!r}"
                    )
                self._select(module_id, "case_required", reasons, disabled)
            for module_id in case_record.manifest.optional_modules:
                if module_id in disabled:
                    disabled_optional.append(module_id)
                elif module_id not in self.catalog.modules:
                    unavailable_optional.append(module_id)
                else:
                    self._select(module_id, "case_optional", reasons, disabled)

        self._add_dependencies(reasons, disabled)
        selected = {module_id: self.catalog.modules[module_id] for module_id in reasons}
        self._check_conflicts(selected)
        order = self._topological_order(selected)
        modules = tuple(
            self._planned_module(selected[module_id], reasons[module_id])
            for module_id in order
        )
        return ExtensionPlan(
            modules=modules,
            case=None if case_record is None else self._planned_case(case_record),
            disabled_optional_modules=tuple(sorted(disabled_optional)),
            unavailable_optional_modules=tuple(sorted(unavailable_optional)),
            management_only=True,
        )

    @staticmethod
    def _ids(values: tuple[str, ...] | list[str], label: str) -> tuple[str, ...]:
        result: list[str] = []
        for value in values:
            try:
                validate_extension_id(value, label)
            except ManifestError as exc:
                raise PlannerError(str(exc)) from exc
            if value in result:
                raise PlannerError(f"duplicate {label}: {value}")
            result.append(value)
        return tuple(result)

    def _select(
        self,
        module_id: str,
        reason: str,
        reasons: dict[str, set[str]],
        disabled: set[str],
    ) -> None:
        if module_id in disabled:
            raise PlannerError(f"module {module_id!r} is explicitly disabled")
        if module_id not in self.catalog.modules:
            raise PlannerError(f"missing module: {module_id}")
        reasons.setdefault(module_id, set()).add(reason)

    def _add_dependencies(
        self, reasons: dict[str, set[str]], disabled: set[str]
    ) -> None:
        pending = list(reasons)
        while pending:
            module_id = pending.pop()
            record = self.catalog.modules[module_id]
            for dependency in record.manifest.dependencies:
                if dependency in disabled:
                    raise PlannerError(
                        f"module {module_id!r} depends on explicitly disabled module "
                        f"{dependency!r}"
                    )
                if dependency not in self.catalog.modules:
                    raise PlannerError(
                        f"missing module dependency: {module_id} -> {dependency}"
                    )
                reason = f"dependency:{module_id}"
                if dependency not in reasons:
                    reasons[dependency] = {reason}
                    pending.append(dependency)
                else:
                    reasons[dependency].add(reason)

    @staticmethod
    def _check_conflicts(selected: dict[str, DiscoveredModule]) -> None:
        for module_id, record in selected.items():
            for conflict in record.manifest.conflicts:
                if conflict in selected:
                    raise PlannerError(
                        f"module conflict: {module_id} conflicts with {conflict}"
                    )

    @staticmethod
    def _topological_order(selected: dict[str, DiscoveredModule]) -> tuple[str, ...]:
        indegree = {module_id: 0 for module_id in selected}
        dependents: dict[str, list[str]] = {module_id: [] for module_id in selected}
        for module_id, record in selected.items():
            for dependency in record.manifest.dependencies:
                if dependency in selected:
                    indegree[module_id] += 1
                    dependents[dependency].append(module_id)
        ready: list[tuple[int, str]] = [
            (selected[module_id].manifest.priority, module_id)
            for module_id, count in indegree.items()
            if count == 0
        ]
        heapq.heapify(ready)
        output: list[str] = []
        while ready:
            _, module_id = heapq.heappop(ready)
            output.append(module_id)
            for dependent in dependents[module_id]:
                indegree[dependent] -= 1
                if indegree[dependent] == 0:
                    heapq.heappush(
                        ready,
                        (selected[dependent].manifest.priority, dependent),
                    )
        if len(output) != len(selected):
            cycle = sorted(module_id for module_id, count in indegree.items() if count)
            raise PlannerError(f"module dependency cycle: {', '.join(cycle)}")
        return tuple(output)

    @staticmethod
    def _planned_module(
        record: DiscoveredModule, reasons: set[str]
    ) -> PlannedModule:
        manifest = record.manifest
        return PlannedModule(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            api_version=manifest.api_version,
            priority=manifest.priority,
            dependencies=manifest.dependencies,
            reasons=tuple(sorted(reasons)),
            root=record.root,
            source=record.source,
            manifest_path=record.manifest_path,
            manifest_sha256=record.manifest_sha256,
            entry_path=(
                None if manifest.entry is None else record.root / Path(manifest.entry)
            ),
        )

    @staticmethod
    def _planned_case(record: DiscoveredCase) -> PlannedCase:
        manifest = record.manifest
        return PlannedCase(
            id=manifest.id,
            name=manifest.name,
            version=manifest.version,
            api_version=manifest.api_version,
            root=record.root,
            source=record.source,
            manifest_path=record.manifest_path,
            manifest_sha256=record.manifest_sha256,
            entry_path=(
                None if manifest.entry is None else record.root / Path(manifest.entry)
            ),
        )
