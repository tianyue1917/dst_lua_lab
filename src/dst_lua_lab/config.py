from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class RunConfig:
    command: str = "run"
    profile: str = "algorithm"
    runtime: str = "luajit20"
    entry: str | None = None
    source: str | None = None
    scripts_zip: str | None = None
    mod: str | None = None
    dependencies: list[str] = field(default_factory=list)
    userid: str = "KU_OFFLINE"
    fixed_time: str = "2099-01-01T00:00:00Z"
    seed: int = 12345
    run_id: str = ""
    report_dir: str = ""
    work_dir: str = ""
    max_trace_events: int = 10000
    case_id: str | None = None
    requested_modules: list[str] = field(default_factory=list)
    replay_plan: list[dict[str, Any]] = field(default_factory=list)
    extension_plan: dict[str, Any] = field(default_factory=dict)
    management_only: bool = True

    def to_json(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_json(cls, value: dict[str, Any]) -> "RunConfig":
        return cls(**value)

    def absolute_inputs(self) -> None:
        for name in ("entry", "scripts_zip", "mod"):
            value = getattr(self, name)
            if value:
                setattr(self, name, str(Path(value).resolve()))
        self.dependencies = [str(Path(p).resolve()) for p in self.dependencies]


EXIT_OK = 0
EXIT_LUA_ERROR = 1
EXIT_CONFIG_ERROR = 2
EXIT_MISSING_NATIVE = 3
EXIT_TIMEOUT = 4
EXIT_ASSERTION = 5
EXIT_INTERNAL = 6
