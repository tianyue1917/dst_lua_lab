from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Generic, Mapping, TypeVar

from .manifest import (
    CaseManifest,
    ManifestError,
    ModuleManifest,
    load_case_manifest,
    load_module_manifest,
    validate_extension_id,
)
from .state import ExtensionState, StateError, StateStore


_PACKAGE_DIR = Path(__file__).resolve().parent
_BUNDLED_EXTENSIONS_ROOT = _PACKAGE_DIR / "_bundled"


class RegistryError(ValueError):
    """Extension discovery or a registry lifecycle operation failed."""


ManifestT = TypeVar("ManifestT", ModuleManifest, CaseManifest)


@dataclass(frozen=True, slots=True)
class DiscoveredExtension(Generic[ManifestT]):
    manifest: ManifestT
    root: Path
    source: str
    manifest_path: Path
    manifest_sha256: str


DiscoveredModule = DiscoveredExtension[ModuleManifest]
DiscoveredCase = DiscoveredExtension[CaseManifest]


@dataclass(frozen=True, slots=True)
class ExtensionCatalog:
    modules: Mapping[str, DiscoveredModule] = field(
        default_factory=lambda: MappingProxyType({})
    )
    cases: Mapping[str, DiscoveredCase] = field(
        default_factory=lambda: MappingProxyType({})
    )


@dataclass(frozen=True, slots=True)
class CaseValidation:
    case_id: str
    manifest_valid: bool
    target_checked: bool
    target_matched: bool | None
    errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "manifest_valid": self.manifest_valid,
            "target_checked": self.target_checked,
            "target_matched": self.target_matched,
            "errors": list(self.errors),
        }


class ExtensionRegistry:
    def __init__(
        self,
        lab_root: Path | str,
        state_store: StateStore | None = None,
        *,
        include_packaged: bool = False,
    ) -> None:
        self.lab_root = Path(lab_root).resolve()
        self.state_store = state_store or StateStore(self.lab_root)
        self.include_packaged = include_packaged

    def discover(self) -> ExtensionCatalog:
        state = self.state_store.load()
        modules = self._discover_builtin_modules()
        cases = self._discover_builtin_cases()
        for expected_id, root_text in sorted(state.external_cases.items()):
            root = Path(root_text)
            if not root.is_dir():
                raise RegistryError(
                    f"mounted case {expected_id!r} path is missing or not a directory: {root}"
                )
            record = self._case_record(root, "external")
            if record.manifest.id != expected_id:
                raise RegistryError(
                    f"mounted case key {expected_id!r} does not match manifest id "
                    f"{record.manifest.id!r} at {root}"
                )
            if expected_id in cases:
                previous = cases[expected_id]
                raise RegistryError(
                    f"duplicate case id {expected_id!r}: {previous.root} and {root}"
                )
            cases[expected_id] = record
        return ExtensionCatalog(
            MappingProxyType(dict(sorted(modules.items()))),
            MappingProxyType(dict(sorted(cases.items()))),
        )

    def list_modules(self) -> tuple[DiscoveredModule, ...]:
        return tuple(self.discover().modules.values())

    def list_cases(self) -> tuple[DiscoveredCase, ...]:
        return tuple(self.discover().cases.values())

    def enable_module(self, module_id: str) -> ExtensionState:
        validate_extension_id(module_id, "module id")
        if module_id not in self.discover().modules:
            raise RegistryError(f"unknown module: {module_id}")
        return self.state_store.enable_module(module_id)

    def disable_module(self, module_id: str) -> ExtensionState:
        validate_extension_id(module_id, "module id")
        if module_id not in self.discover().modules:
            raise RegistryError(f"unknown module: {module_id}")
        return self.state_store.disable_module(module_id)

    def mount_case(self, root: Path | str) -> ExtensionState:
        root = Path(root).resolve()
        if not root.is_dir():
            raise RegistryError(f"case path is missing or not a directory: {root}")
        try:
            record = self._case_record(root, "external")
        except ManifestError as exc:
            raise RegistryError(str(exc)) from exc

        builtins = self._discover_builtin_cases()
        if record.manifest.id in builtins:
            raise RegistryError(f"cannot mount over built-in case: {record.manifest.id}")

        state = self.state_store.load()
        current = state.external_cases.get(record.manifest.id)
        if current is not None and current != str(root):
            raise RegistryError(
                f"case {record.manifest.id!r} is already mounted from {current}"
            )
        for other_id, other_root in state.external_cases.items():
            if other_root == str(root) and other_id != record.manifest.id:
                raise RegistryError(f"case path is already mounted as {other_id!r}: {root}")
        try:
            return self.state_store.mount_case(record.manifest.id, root)
        except StateError as exc:
            raise RegistryError(str(exc)) from exc

    def unmount_case(self, case_id: str) -> ExtensionState:
        validate_extension_id(case_id, "case id")
        if case_id in self._discover_builtin_cases():
            raise RegistryError(f"cannot unmount built-in case: {case_id}")
        return self.state_store.unmount_case(case_id)

    def validate_case(
        self, case_id: str, mod_root: Path | str | None = None
    ) -> CaseValidation:
        validate_extension_id(case_id, "case id")
        catalog = self.discover()
        if case_id not in catalog.cases:
            raise RegistryError(f"unknown case: {case_id}")
        if mod_root is None:
            return CaseValidation(case_id, True, False, None)

        root = Path(mod_root).resolve()
        errors: list[str] = []
        if not root.is_dir():
            errors.append(f"target mod path is missing or not a directory: {root}")
        else:
            match = catalog.cases[case_id].manifest.match
            for relative in match.required_files:
                target = root / Path(relative)
                if not self._is_confined(target, root) or not target.is_file():
                    errors.append(f"missing required target file: {relative}")
            for relative, accepted_hashes in match.file_hashes.items():
                target = root / Path(relative)
                if not self._is_confined(target, root) or not target.is_file():
                    errors.append(f"missing hashed target file: {relative}")
                    continue
                actual = hashlib.sha256(target.read_bytes()).hexdigest().upper()
                expected = {value.upper() for value in accepted_hashes}
                if actual not in expected:
                    errors.append(
                        f"target hash mismatch for {relative}: {actual} not in accepted hashes"
                    )
        return CaseValidation(case_id, True, True, not errors, tuple(errors))

    def _discover_builtin_modules(self) -> dict[str, DiscoveredModule]:
        records: dict[str, DiscoveredModule] = {}
        for base, source in self._builtin_search_roots("modules"):
            for root in self._builtin_roots(base, "module.toml"):
                record = self._module_record(root, source)
                if record.manifest.id in records:
                    previous = records[record.manifest.id]
                    raise RegistryError(
                        f"duplicate module id {record.manifest.id!r}: "
                        f"{previous.root} and {record.root}"
                    )
                records[record.manifest.id] = record
        return records

    def _discover_builtin_cases(self) -> dict[str, DiscoveredCase]:
        records: dict[str, DiscoveredCase] = {}
        for base, source in self._builtin_search_roots("casepacks"):
            for root in self._builtin_roots(base, "case.toml"):
                record = self._case_record(root, source)
                if record.manifest.id in records:
                    previous = records[record.manifest.id]
                    raise RegistryError(
                        f"duplicate case id {record.manifest.id!r}: "
                        f"{previous.root} and {record.root}"
                    )
                records[record.manifest.id] = record
        return records

    def _builtin_search_roots(self, collection: str) -> tuple[tuple[Path, str], ...]:
        """Return checkout extensions and, for wheel CLI use, packaged ones.

        Temporary/custom ``ExtensionRegistry`` roots intentionally do not see
        global packaged extensions.  This preserves isolation for embedders and
        tests while making the installed ``dstlab`` command behave like a
        source checkout.
        """

        primary = self.lab_root / collection
        roots: list[tuple[Path, str]] = [(primary, "builtin")]
        if self.include_packaged:
            bundled = _BUNDLED_EXTENSIONS_ROOT / collection
            if bundled.resolve() != primary.resolve():
                roots.append((bundled, "packaged"))
        return tuple(roots)

    @staticmethod
    def _builtin_roots(base: Path, manifest_name: str) -> tuple[Path, ...]:
        if not base.exists():
            return ()
        if not base.is_dir():
            raise RegistryError(f"extension root is not a directory: {base}")
        base = base.resolve()
        roots: list[Path] = []
        for child in sorted(base.iterdir(), key=lambda item: item.name):
            if not child.is_dir() or not (child / manifest_name).is_file():
                continue
            root = child.resolve()
            if not ExtensionRegistry._is_confined(root, base):
                raise RegistryError(f"built-in extension escapes its root: {child}")
            roots.append(root)
        return tuple(roots)

    @staticmethod
    def _is_confined(path: Path, root: Path) -> bool:
        try:
            path.resolve().relative_to(root.resolve())
        except (OSError, ValueError):
            return False
        return True

    def _module_record(self, root: Path, source: str) -> DiscoveredModule:
        try:
            manifest = load_module_manifest(root)
        except ManifestError as exc:
            raise RegistryError(f"invalid module at {root}: {exc}") from exc
        return self._record(manifest, root, source, "module.toml")

    def _case_record(self, root: Path, source: str) -> DiscoveredCase:
        try:
            manifest = load_case_manifest(root)
        except ManifestError as exc:
            raise RegistryError(f"invalid case at {root}: {exc}") from exc
        return self._record(manifest, root, source, "case.toml")

    @staticmethod
    def _record(
        manifest: ManifestT, root: Path, source: str, manifest_name: str
    ) -> DiscoveredExtension[ManifestT]:
        root = root.resolve()
        manifest_path = root / manifest_name
        if manifest.entry is not None:
            entry = root / Path(manifest.entry)
            if not ExtensionRegistry._is_confined(entry, root):
                raise RegistryError(f"extension entry escapes root: {entry}")
            if not entry.is_file():
                raise RegistryError(f"extension entry does not exist: {entry}")
        digest = hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper()
        return DiscoveredExtension(manifest, root, source, manifest_path, digest)
