from __future__ import annotations

from dst_lua_lab.runtime import RuntimeAdapter
from dst_lua_lab.trace import safe_value


def test_all_required_runtimes_start() -> None:
    for runtime_id in ("lua51", "luajit20", "luajit21"):
        lua = RuntimeAdapter(runtime_id).create()
        assert lua.execute(b"return 6 * 7") == 42


def test_vm_state_is_isolated() -> None:
    first = RuntimeAdapter("luajit20").create()
    first.execute(b"DSTLAB_LEAK = 123")
    second = RuntimeAdapter("luajit20").create()
    assert second.globals()[b"DSTLAB_LEAK"] is None


def test_bytes_are_serialized_without_nul_loss() -> None:
    value = safe_value(b"A\x00\xffB")
    assert value["length"] == 4
    assert value["hex"] == "4100ff42"
