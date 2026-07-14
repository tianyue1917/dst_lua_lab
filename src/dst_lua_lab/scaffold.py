from __future__ import annotations

import os
import re
import shutil
import stat
from pathlib import Path
from typing import Literal

from .manifest import validate_extension_id


class ScaffoldError(ValueError):
    """A scaffold destination or identifier is unsafe to create."""


ScaffoldKind = Literal["module", "case"]

_LONG_NUMERIC_IDENTIFIER = re.compile(r"\d{7,}")
_KLEI_USER_IDENTIFIER = re.compile(r"(?:^|[._-])ku[._-][a-z0-9]+(?:$|[._-])", re.IGNORECASE)
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}


def _assert_public_safe_id(extension_id: str) -> None:
    """Keep target-specific account and Workshop identifiers out of templates."""

    if extension_id.isdigit() or _LONG_NUMERIC_IDENTIFIER.search(extension_id):
        raise ScaffoldError(
            "extension id looks like a Workshop or platform identifier; "
            "use a descriptive public-safe id"
        )
    if _KLEI_USER_IDENTIFIER.search(extension_id):
        raise ScaffoldError(
            "extension id looks like a Klei user identifier; "
            "use a descriptive public-safe id"
        )
    if extension_id.endswith(".") or extension_id.split(".", 1)[0] in _WINDOWS_RESERVED_NAMES:
        raise ScaffoldError(
            "extension id is not a portable directory name; "
            "use a descriptive public-safe id"
        )


def _test_filename(kind: ScaffoldKind, extension_id: str) -> str:
    """Return an injective, import-safe test name across all scaffolds."""

    encoded = (
        extension_id.replace("_", "_u")
        .replace("-", "_h")
        .replace(".", "_d")
    )
    return f"tests/test_{kind}_{encoded}.py"


def _is_reparse_point(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )


def _prepare_destination(
    lab_root: Path | str, kind: ScaffoldKind, extension_id: str
) -> tuple[Path, Path]:
    # This is the canonical manifest validator. Scaffold-specific privacy checks
    # are deliberately additional and do not duplicate the ID grammar.
    validate_extension_id(extension_id, f"{kind} id")
    _assert_public_safe_id(extension_id)

    raw_root = Path(lab_root).expanduser()
    if _is_reparse_point(raw_root):
        raise ScaffoldError(f"Lab root must not be a symlink or reparse point: {raw_root}")
    root = raw_root.resolve()
    if not root.is_dir():
        raise ScaffoldError(f"Lab root is missing or not a directory: {root}")

    collection_name = "modules" if kind == "module" else "casepacks"
    collection = root / collection_name
    if _is_reparse_point(collection):
        raise ScaffoldError(
            f"scaffold collection must not be a symlink or reparse point: {collection}"
        )
    if os.path.lexists(collection) and not collection.is_dir():
        raise ScaffoldError(f"scaffold collection is not a directory: {collection}")
    if not collection.exists():
        collection.mkdir()

    resolved_collection = collection.resolve()
    if resolved_collection.parent != root or not resolved_collection.is_relative_to(root):
        raise ScaffoldError(f"scaffold collection escapes Lab root: {collection}")

    destination = collection / extension_id
    if os.path.lexists(destination):
        raise ScaffoldError(f"scaffold destination already exists: {destination}")
    resolved_destination = destination.resolve(strict=False)
    if (
        resolved_destination.parent != resolved_collection
        or not resolved_destination.is_relative_to(resolved_collection)
    ):
        raise ScaffoldError(f"scaffold destination escapes its collection: {destination}")
    return root, destination


def _write_scaffold(
    lab_root: Path | str,
    kind: ScaffoldKind,
    extension_id: str,
    files: dict[str, str],
) -> list[str]:
    root, destination = _prepare_destination(lab_root, kind, extension_id)
    try:
        # mkdir(exist_ok=False) is the final no-overwrite gate after validation.
        destination.mkdir()
        for relative, content in files.items():
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8", newline="\n")
    except Exception:
        # A failed scaffold should never leave an apparently usable partial
        # extension behind. The destination was created by this call and was
        # proven not to exist above.
        if destination.is_dir() and not _is_reparse_point(destination):
            shutil.rmtree(destination, ignore_errors=True)
        raise

    return sorted(
        path.relative_to(root).as_posix()
        for path in destination.rglob("*")
        if path.is_file()
    )


def create_module(lab_root: Path | str, module_id: str) -> list[str]:
    """Create a public-safe Capability Module and return its relative file list."""

    validate_extension_id(module_id, "module id")
    manifest = f'''schema = 1
id = "{module_id}"
name = "Capability module: {module_id}"
version = "0.1.0"
api_version = "1"
priority = 100
dependencies = []
conflicts = []
profiles = ["algorithm", "modload", "frontend", "server-sim"]
entry = "plugin.py"
'''
    entry = f'''"""Entry point for the {module_id} Capability Module."""


def register(context):
    """Declare this module's trace interest through the public API."""
    context.subscribe_trace("{module_id}.ready")
'''
    readme = f'''# {module_id}

This is a public-safe DST Lua Lab Capability Module scaffold.

Implement reusable behavior in `plugin.py`. Keep target-specific patches,
account identifiers, Workshop identifiers, logs, and game assets out of this
directory. Run its template contract with:

```console
python -m pytest modules/{module_id}/tests
```
'''
    test = f'''from __future__ import annotations

import runpy
from pathlib import Path

from dst_lua_lab.manifest import load_module_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_contract() -> None:
    manifest = load_module_manifest(ROOT)
    assert manifest.id == "{module_id}"
    assert manifest.entry == "plugin.py"


def test_entry_contract() -> None:
    events: list[str] = []

    class Context:
        def subscribe_trace(self, event: str) -> None:
            events.append(event)

    namespace = runpy.run_path(str(ROOT / "plugin.py"))
    namespace["register"](Context())
    assert events == ["{module_id}.ready"]
'''
    return _write_scaffold(
        lab_root,
        "module",
        module_id,
        {
            "module.toml": manifest,
            "plugin.py": entry,
            "README.md": readme,
            _test_filename("module", module_id): test,
        },
    )


def create_case(lab_root: Path | str, case_id: str) -> list[str]:
    """Create a public-safe Case Pack and return its relative file list."""

    validate_extension_id(case_id, "case id")
    manifest = f'''schema = 1
id = "{case_id}"
name = "Case pack: {case_id}"
version = "0.1.0"
api_version = "1"
required_modules = []
optional_modules = []
profiles = ["modload"]
entry = "adapter.py"

[match]
required_files = ["modinfo.lua", "modmain.lua"]
'''
    entry = f'''"""Entry point for the {case_id} Case Pack."""


def register(context):
    """Declare a synthetic assertion through the public extension API."""
    context.add_assertion("case.{case_id}.loaded", expected=True)
'''
    readme = f'''# {case_id}

This is a public-safe DST Lua Lab Case Pack scaffold.

Keep this adapter narrow and target-specific, but never commit account data,
Workshop source, logs, save data, secrets, or proprietary game assets. Add
only synthetic fixtures to tests. Run its template contract with:

```console
python -m pytest casepacks/{case_id}/tests
```
'''
    test = f'''from __future__ import annotations

import runpy
from pathlib import Path

from dst_lua_lab.manifest import load_case_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_manifest_contract() -> None:
    manifest = load_case_manifest(ROOT)
    assert manifest.id == "{case_id}"
    assert manifest.entry == "adapter.py"
    assert manifest.workshop_id is None


def test_entry_contract() -> None:
    assertions: list[tuple[str, object]] = []

    class Context:
        def add_assertion(self, name: str, *, expected: object) -> None:
            assertions.append((name, expected))

    namespace = runpy.run_path(str(ROOT / "adapter.py"))
    namespace["register"](Context())
    assert assertions == [("case.{case_id}.loaded", True)]
'''
    return _write_scaffold(
        lab_root,
        "case",
        case_id,
        {
            "case.toml": manifest,
            "adapter.py": entry,
            "README.md": readme,
            _test_filename("case", case_id): test,
        },
    )


__all__ = ["ScaffoldError", "create_case", "create_module"]
