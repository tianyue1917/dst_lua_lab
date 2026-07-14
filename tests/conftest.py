from __future__ import annotations

import shutil
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


PROJECT_ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = PROJECT_ROOT / ".pytest-generated"
SYNTHETIC_SCRIPTS_ZIP = GENERATED_ROOT / "scripts.zip"


CLASS_LUA = r'''
function Class(base, constructor)
    if constructor == nil then
        constructor = base
        base = nil
    end

    local class = {}
    class.__index = class
    class._ctor = constructor
    setmetatable(class, {
        __index = base,
        __call = function(type_, ...)
            local instance = setmetatable({}, type_)
            if base ~= nil and base._ctor ~= nil then
                base._ctor(instance, ...)
            end
            if constructor ~= nil then
                constructor(instance, ...)
            end
            return instance
        end,
    })
    return class
end
'''.lstrip()


def pytest_sessionstart(session) -> None:  # type: ignore[no-untyped-def]
    GENERATED_ROOT.mkdir(parents=True, exist_ok=True)
    with ZipFile(SYNTHETIC_SCRIPTS_ZIP, "w", ZIP_DEFLATED) as archive:
        archive.writestr("scripts/class.lua", CLASS_LUA)
        archive.writestr("scripts/constants.lua", "return nil\n")
        archive.writestr("scripts/tuning.lua", "return nil\n")
        archive.writestr("scripts/strings.lua", "return nil\n")


def pytest_sessionfinish(session, exitstatus) -> None:  # type: ignore[no-untyped-def]
    shutil.rmtree(GENERATED_ROOT, ignore_errors=True)
