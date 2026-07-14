from __future__ import annotations

import json

from dst_lua_lab.cli import launch_worker
from dst_lua_lab.config import EXIT_LUA_ERROR, EXIT_OK, EXIT_TIMEOUT, RunConfig


def read_result(report):
    return json.loads((report / "result.json").read_text("utf-8"))


def test_worker_success() -> None:
    code, report = launch_worker(RunConfig(source="return 21 * 2"), 5)
    assert code == EXIT_OK
    assert read_result(report)["result"] == 42


def test_worker_syntax_error() -> None:
    code, report = launch_worker(RunConfig(source="this is not lua !!!"), 5)
    assert code == EXIT_LUA_ERROR
    assert read_result(report)["status"] == "error"


def test_worker_runtime_error() -> None:
    code, report = launch_worker(RunConfig(source="error('boom')"), 5)
    assert code == EXIT_LUA_ERROR
    assert "boom" in read_result(report)["message"]


def test_worker_infinite_loop_timeout() -> None:
    code, report = launch_worker(RunConfig(source="while true do end"), 0.4)
    assert code == EXIT_TIMEOUT
    assert read_result(report)["status"] == "timeout"


def test_dynamic_chunk_is_captured() -> None:
    code, report = launch_worker(RunConfig(source="return loadstring('return 9')()"), 5)
    assert code == EXIT_OK
    result = read_result(report)
    assert result["result"] == 9
    assert result["dynamic_chunks"] == 1
    assert len(list((report / "chunks").glob("*.bin"))) == 1
