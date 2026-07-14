from __future__ import annotations

import copy
import hashlib
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType, ModuleType
from typing import Any, Callable, Mapping


EXTENSION_API_VERSION = "1"
BOOTSTRAP_PHASES = ("pre_runtime", "pre_mod", "post_mod")
_EXTENSION_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_GLOBAL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_NATIVE_API_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")


class ExtensionRuntimeError(ValueError):
    """An extension plan or entry point is invalid."""


@dataclass(frozen=True, slots=True)
class NativeCallContext:
    """The only host object passed to a registered native handler."""

    api: str
    profile: str
    args: tuple[Any, ...]
    _emit: Callable[..., None] = field(repr=False)

    def emit(self, event_type: str, source: str, effect: str, **data: Any) -> None:
        self._emit(event_type, source, effect, **data)


def _json_value(value: Any, *, label: str) -> Any:
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False)
        return json.loads(encoded)
    except (TypeError, ValueError) as exc:
        raise ExtensionRuntimeError(f"{label} must be JSON-safe: {exc}") from exc


def _scoped_path(root: Path, relative_path: str, *, must_exist: bool = True) -> Path:
    candidate = Path(relative_path)
    if candidate.is_absolute():
        raise ExtensionRuntimeError(f"extension path must be relative: {relative_path!r}")
    root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ExtensionRuntimeError(f"extension path escapes its root: {relative_path!r}") from exc
    if must_exist and not resolved.is_file():
        raise ExtensionRuntimeError(f"extension file does not exist: {resolved}")
    return resolved


@dataclass(frozen=True, slots=True)
class LuaBootstrap:
    extension_id: str
    phase: str
    path: Path
    data: bytes


@dataclass(slots=True)
class ExtensionContext:
    """Versioned declaration API passed only to Worker-loaded local extensions."""

    extension_id: str
    kind: str
    root: Path
    api_version: str
    profile: str
    _session: "ExtensionSession" = field(repr=False)

    @property
    def config(self) -> Mapping[str, Any]:
        return MappingProxyType(copy.deepcopy(self._session.public_config))

    def read_bytes(self, relative_path: str) -> bytes:
        return _scoped_path(self.root, relative_path).read_bytes()

    def register_lua_bootstrap(self, phase: str, relative_path: str) -> None:
        if phase not in BOOTSTRAP_PHASES:
            raise ExtensionRuntimeError(
                f"invalid bootstrap phase {phase!r}; expected one of {', '.join(BOOTSTRAP_PHASES)}"
            )
        path = _scoped_path(self.root, relative_path)
        self._session.lua_bootstraps.append(
            LuaBootstrap(self.extension_id, phase, path, path.read_bytes())
        )
        self._session._contribute(self, "lua_bootstrap", phase=phase, path=str(path))

    def register_global(self, name: str, value: Any) -> None:
        if not _GLOBAL_IDENTIFIER.fullmatch(name):
            raise ExtensionRuntimeError(f"invalid Lua global name: {name!r}")
        if name in self._session.globals:
            owner = self._session.global_owners[name]
            raise ExtensionRuntimeError(f"Lua global {name!r} already registered by {owner}")
        clean = _json_value(value, label=f"global {name!r}")
        self._session.globals[name] = clean
        self._session.global_owners[name] = self.extension_id
        self._session._contribute(self, "global", name=name, value=clean)

    def deny_mod_global(self, name: str) -> None:
        if not _GLOBAL_IDENTIFIER.fullmatch(name):
            raise ExtensionRuntimeError(f"invalid Lua global name: {name!r}")
        self._session.denied_mod_globals.add(name)
        self._session._contribute(self, "deny_mod_global", name=name)

    def register_native(self, api: str, handler: Callable[[NativeCallContext], Any]) -> None:
        if not _NATIVE_API_IDENTIFIER.fullmatch(api):
            raise ExtensionRuntimeError(f"invalid native API name: {api!r}")
        if not callable(handler):
            raise ExtensionRuntimeError(f"native handler for {api!r} is not callable")
        if api in self._session.native_handlers:
            owner = self._session.native_owners[api]
            raise ExtensionRuntimeError(f"native API {api!r} already registered by {owner}")
        self._session.native_handlers[api] = handler
        self._session.native_owners[api] = self.extension_id
        self._session._contribute(self, "native", api=api)

    def register_rpc_observer(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        if not callable(handler):
            raise ExtensionRuntimeError("RPC observer is not callable")
        self._session.rpc_observers.append((self.extension_id, handler))
        self._session._contribute(self, "rpc_observer")

    def register_after_run(self, handler: Callable[[dict[str, Any]], Any]) -> None:
        if not callable(handler):
            raise ExtensionRuntimeError("after-run handler is not callable")
        self._session.after_run_handlers.append((self.extension_id, handler))
        self._session._contribute(self, "after_run")

    # Compatibility with the phase-one synthetic examples. These remain
    # declarations; they do not grant an extension direct access to TraceRecorder.
    def subscribe_trace(self, event: str) -> None:
        self._session._contribute(self, "trace_subscription", event=str(event))

    def add_assertion(self, name: str, *, expected: Any) -> None:
        self._session._contribute(
            self, "assertion", name=str(name), expected=_json_value(expected, label="assertion expected")
        )


class ExtensionSession:
    """Worker-owned extension lifetime and collected declarations."""

    def __init__(self, *, profile: str, config: Mapping[str, Any] | None = None) -> None:
        self.profile = profile
        self.public_config = copy.deepcopy(dict(config or {}))
        self.loaded_extensions: list[dict[str, Any]] = []
        self.contributions: list[dict[str, Any]] = []
        self.lua_bootstraps: list[LuaBootstrap] = []
        self.globals: dict[str, Any] = {}
        self.global_owners: dict[str, str] = {}
        self.denied_mod_globals: set[str] = set()
        self.native_handlers: dict[str, Callable[[NativeCallContext], Any]] = {}
        self.native_owners: dict[str, str] = {}
        self.rpc_observers: list[tuple[str, Callable[[dict[str, Any]], Any]]] = []
        self.after_run_handlers: list[tuple[str, Callable[[dict[str, Any]], Any]]] = []
        self.after_run_outputs: list[dict[str, Any]] = []
        self.skipped_management_entries: list[dict[str, str]] = []

    def _contribute(self, context: ExtensionContext, contribution_type: str, **details: Any) -> None:
        self.contributions.append(
            {
                "extension_id": context.extension_id,
                "extension_kind": context.kind,
                "type": contribution_type,
                **details,
            }
        )

    @classmethod
    def from_plan(
        cls, plan: Mapping[str, Any] | None, *, profile: str, config: Mapping[str, Any] | None = None
    ) -> "ExtensionSession":
        session = cls(profile=profile, config=config)
        session.load_plan(plan or {})
        return session

    def load_plan(self, plan: Mapping[str, Any]) -> None:
        if not isinstance(plan, Mapping):
            raise ExtensionRuntimeError("extension_plan must be an object")
        modules = plan.get("modules", [])
        if not isinstance(modules, list):
            raise ExtensionRuntimeError("extension_plan.modules must be a list")
        seen: set[str] = set()
        for item in modules:
            if self._skip_legacy_management_item(plan, item, "module"):
                continue
            self._load_item(item, kind="module", seen=seen)
            seen.add(str(item.get("id")))
        case = plan.get("case")
        if case is not None:
            if self._skip_legacy_management_item(plan, case, "case"):
                return
            self._load_item(case, kind="case", seen=seen)

    def _skip_legacy_management_item(self, plan: Mapping[str, Any], item: Any, kind: str) -> bool:
        """Accept phase-one evidence-only records without mistaking them for executable entries."""
        required = (
            "api_version",
            "root",
            "manifest_path",
            "manifest_sha256",
            "entry_path",
            "entry_sha256",
            "profiles",
        )
        if bool(plan.get("management_only")) and isinstance(item, Mapping) and any(
            field not in item for field in required
        ):
            self.skipped_management_entries.append(
                {"id": str(item.get("id", "")), "kind": kind, "reason": "management_only_record"}
            )
            return True
        return False

    def _load_item(self, item: Any, *, kind: str, seen: set[str]) -> None:
        if not isinstance(item, Mapping):
            raise ExtensionRuntimeError(f"planned {kind} must be an object")
        extension_id = str(item.get("id", ""))
        if not _EXTENSION_ID.fullmatch(extension_id):
            raise ExtensionRuntimeError(f"invalid planned {kind} id: {extension_id!r}")
        if extension_id in seen or any(x["id"] == extension_id for x in self.loaded_extensions):
            raise ExtensionRuntimeError(f"duplicate extension in plan: {extension_id}")
        api_version = str(item.get("api_version", ""))
        if api_version != EXTENSION_API_VERSION:
            raise ExtensionRuntimeError(
                f"unsupported extension API {api_version!r} for {extension_id}; Worker supports {EXTENSION_API_VERSION!r}"
            )
        profiles = item.get("profiles")
        if not isinstance(profiles, list) or any(
            not isinstance(profile, str) for profile in profiles
        ):
            raise ExtensionRuntimeError(
                f"planned {kind} {extension_id} profiles must be a list of strings"
            )
        if profiles and self.profile not in profiles:
            raise ExtensionRuntimeError(
                f"planned {kind} {extension_id} does not support profile {self.profile!r}"
            )
        if kind == "module":
            dependencies = item.get("dependencies", [])
            if not isinstance(dependencies, list) or any(str(dep) not in seen for dep in dependencies):
                missing = [str(dep) for dep in dependencies if str(dep) not in seen] if isinstance(dependencies, list) else []
                raise ExtensionRuntimeError(f"module {extension_id} loaded before dependencies: {missing}")
        root_raw = item.get("root")
        if not isinstance(root_raw, str) or not Path(root_raw).is_absolute():
            raise ExtensionRuntimeError(f"planned {kind} {extension_id} root must be absolute")
        root = Path(root_raw).resolve()
        if not root.is_dir():
            raise ExtensionRuntimeError(f"planned {kind} root does not exist: {root}")
        manifest_raw = item.get("manifest_path")
        expected_manifest_sha = item.get("manifest_sha256")
        if not isinstance(manifest_raw, str) or not Path(manifest_raw).is_absolute():
            raise ExtensionRuntimeError(f"planned {kind} {extension_id} manifest_path must be absolute")
        manifest_path = Path(manifest_raw).resolve()
        try:
            manifest_path.relative_to(root)
        except ValueError as exc:
            raise ExtensionRuntimeError(f"manifest escapes extension root: {manifest_path}") from exc
        if not manifest_path.is_file():
            raise ExtensionRuntimeError(f"planned manifest does not exist: {manifest_path}")
        actual_manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest().upper()
        if not isinstance(expected_manifest_sha, str) or actual_manifest_sha != expected_manifest_sha.upper():
            raise ExtensionRuntimeError(
                f"manifest changed after planning for {extension_id}: "
                f"expected {expected_manifest_sha!r}, actual {actual_manifest_sha}"
            )
        entry_raw = item.get("entry_path")
        expected_entry_sha = item.get("entry_sha256")
        loaded = {
            "id": extension_id,
            "kind": kind,
            "api_version": api_version,
            "root": str(root),
            "manifest_path": str(manifest_path),
            "manifest_sha256": actual_manifest_sha,
            "entry_path": None,
            "entry_sha256": None,
            "status": "loaded",
        }
        if entry_raw is not None:
            if not isinstance(entry_raw, str) or not Path(entry_raw).is_absolute():
                raise ExtensionRuntimeError(f"planned {kind} {extension_id} entry_path must be absolute")
            entry = Path(entry_raw).resolve()
            try:
                entry.relative_to(root)
            except ValueError as exc:
                raise ExtensionRuntimeError(f"entry point escapes extension root: {entry}") from exc
            if not entry.is_file():
                raise ExtensionRuntimeError(f"entry point does not exist: {entry}")
            entry_data = entry.read_bytes()
            actual_entry_sha = hashlib.sha256(entry_data).hexdigest().upper()
            if (
                not isinstance(expected_entry_sha, str)
                or actual_entry_sha != expected_entry_sha.upper()
            ):
                raise ExtensionRuntimeError(
                    f"entry changed after planning for {extension_id}: "
                    f"expected {expected_entry_sha!r}, actual {actual_entry_sha}"
                )
            loaded["entry_path"] = str(entry)
            loaded["entry_sha256"] = actual_entry_sha
            self._execute_entry(
                extension_id, kind, root, api_version, entry, entry_data
            )
        else:
            if expected_entry_sha is not None:
                raise ExtensionRuntimeError(
                    f"planned {kind} {extension_id} has entry_sha256 without entry_path"
                )
            loaded["status"] = "loaded_no_entry"
        self.loaded_extensions.append(loaded)

    def _execute_entry(
        self,
        extension_id: str,
        kind: str,
        root: Path,
        api_version: str,
        entry: Path,
        entry_data: bytes,
    ) -> None:
        module_name = f"_dstlab_extension_{kind}_{extension_id}_{id(self):x}"
        module = ModuleType(module_name)
        module.__file__ = str(entry)
        module.__package__ = ""
        before_path = list(sys.path)
        try:
            code = compile(entry_data, str(entry), "exec")
            exec(code, module.__dict__)
            register = getattr(module, "register", None)
            if not callable(register):
                raise ExtensionRuntimeError(f"extension {extension_id} entry must define register(context)")
            context = ExtensionContext(extension_id, kind, root, api_version, self.profile, self)
            register(context)
        except ExtensionRuntimeError:
            raise
        except Exception as exc:
            raise ExtensionRuntimeError(
                f"extension {extension_id} register(context) failed: {type(exc).__name__}: {exc}"
            ) from exc
        finally:
            sys.path[:] = before_path
            sys.modules.pop(module_name, None)

    def bootstraps(self, phase: str) -> tuple[LuaBootstrap, ...]:
        return tuple(item for item in self.lua_bootstraps if item.phase == phase)

    def notify_rpc(self, event: dict[str, Any]) -> None:
        clean = _json_value(event, label="RPC event")
        for extension_id, handler in self.rpc_observers:
            try:
                handler(dict(clean))
            except Exception as exc:
                raise ExtensionRuntimeError(
                    f"RPC observer from {extension_id} failed: {type(exc).__name__}: {exc}"
                ) from exc

    def run_after(self, result: dict[str, Any]) -> None:
        for extension_id, handler in self.after_run_handlers:
            try:
                output = handler(dict(result))
            except Exception as exc:
                raise ExtensionRuntimeError(
                    f"after-run handler from {extension_id} failed: {type(exc).__name__}: {exc}"
                ) from exc
            if output is not None:
                self.after_run_outputs.append(
                    {
                        "extension_id": extension_id,
                        "value": _json_value(output, label=f"after-run output from {extension_id}"),
                    }
                )

    def report(self) -> dict[str, Any]:
        return {
            "api_version": EXTENSION_API_VERSION,
            "management_only": False,
            "extensions_loaded": bool(self.loaded_extensions),
            "loaded_extensions": self.loaded_extensions,
            "contributions": self.contributions,
            "after_run_outputs": self.after_run_outputs,
            "skipped_management_entries": self.skipped_management_entries,
        }
