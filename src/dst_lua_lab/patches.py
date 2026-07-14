from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class PatchManifest:
    schema: int
    id: str
    version: str
    api_version: str = "1"
    priority: int = 100
    dependencies: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    match: dict[str, Any] = field(default_factory=dict)
    root: Path | None = None

    @classmethod
    def load(cls, path: Path) -> "PatchManifest":
        data = json.loads(path.read_text("utf-8"))
        manifest = cls(**{key: data[key] for key in cls.__dataclass_fields__ if key in data and key != "root"})
        if manifest.schema != 1 or manifest.api_version != "1":
            raise ValueError(f"unsupported patch schema/api: {manifest.schema}/{manifest.api_version}")
        manifest.root = path.parent
        return manifest


def sort_patches(manifests: list[PatchManifest]) -> list[PatchManifest]:
    by_id = {item.id: item for item in manifests}
    for item in manifests:
        for conflict in item.conflicts:
            if conflict in by_id:
                raise ValueError(f"patch conflict: {item.id} conflicts with {conflict}")
    output: list[PatchManifest] = []
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(item: PatchManifest) -> None:
        if item.id in visited:
            return
        if item.id in visiting:
            raise ValueError(f"patch dependency cycle at {item.id}")
        visiting.add(item.id)
        for dependency in item.dependencies:
            if dependency not in by_id:
                raise ValueError(f"missing patch dependency: {item.id} -> {dependency}")
            visit(by_id[dependency])
        visiting.remove(item.id)
        visited.add(item.id)
        output.append(item)

    for manifest in sorted(manifests, key=lambda item: (item.priority, item.id)):
        visit(manifest)
    return output
