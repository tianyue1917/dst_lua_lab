from __future__ import annotations

import os
from pathlib import Path

import pytest

from dst_lua_lab.vfs import build_default_vfs


SCRIPTS_ZIP_VALUE = os.environ.get("DSTLAB_SCRIPTS_ZIP")
SCRIPTS_ZIP = Path(SCRIPTS_ZIP_VALUE).expanduser().resolve() if SCRIPTS_ZIP_VALUE else None


@pytest.mark.skipif(
    SCRIPTS_ZIP is None or not SCRIPTS_ZIP.is_file(),
    reason="set DSTLAB_SCRIPTS_ZIP to test a user-provided DST scripts archive",
)
def test_user_provided_scripts_zip_resolves_class() -> None:
    assert SCRIPTS_ZIP is not None
    result = build_default_vfs(SCRIPTS_ZIP, None, []).read_module("class", caller="integration-test")
    assert result.uri == "dst://scripts/class.lua"
    assert result.data
    assert result.caller == "integration-test"
