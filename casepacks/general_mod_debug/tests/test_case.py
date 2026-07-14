from __future__ import annotations

from pathlib import Path

from dst_lua_lab.manifest import load_case_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_general_case_is_target_neutral_and_enables_the_four_basics():
    manifest = load_case_manifest(ROOT)
    assert manifest.workshop_id is None
    assert manifest.match.required_files == ()
    assert manifest.required_modules == (
        "dst_runtime_baseline",
        "strict_env",
        "rpc_capture",
        "persistence_trace",
        "scheduler_trace",
    )
