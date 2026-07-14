from __future__ import annotations

import json
import os
import stat
import tempfile
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SETTINGS_SCHEMA = 1


class SettingsError(ValueError):
    """A local Lab settings file is malformed or cannot be updated safely."""


@dataclass(frozen=True, slots=True)
class LabSettings:
    scripts_zip: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"schema": SETTINGS_SCHEMA, "scripts_zip": self.scripts_zip}


class SettingsStore:
    def __init__(self, lab_root: Path | str) -> None:
        raw_root = Path(lab_root).expanduser().absolute()
        if _is_reparse_point(raw_root):
            raise SettingsError(
                f"Lab root cannot be a symlink or reparse point: {raw_root}"
            )
        self.lab_root = raw_root.resolve()
        self.directory = self.lab_root / ".dstlab"
        self.path = self.directory / "config.toml"

    def load(self) -> LabSettings:
        if _is_reparse_point(self.directory) or _is_reparse_point(self.path):
            raise SettingsError("settings paths cannot be symlinks or reparse points")
        if not self.path.exists():
            return LabSettings()
        if not self.path.is_file():
            raise SettingsError(f"settings path is not a file: {self.path}")
        try:
            with self.path.open("rb") as stream:
                value = tomllib.load(stream)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise SettingsError(f"cannot read settings {self.path}: {exc}") from exc
        if type(value) is not dict:
            raise SettingsError("settings root must be a TOML table")
        unknown = sorted(set(value) - {"schema", "scripts_zip"})
        if unknown:
            raise SettingsError(f"unknown settings fields: {', '.join(unknown)}")
        if value.get("schema") != SETTINGS_SCHEMA:
            raise SettingsError(f"unsupported settings schema: {value.get('schema')!r}")
        scripts_zip = value.get("scripts_zip")
        if scripts_zip is not None and (type(scripts_zip) is not str or not scripts_zip.strip()):
            raise SettingsError("scripts_zip must be a non-empty string")
        return LabSettings(scripts_zip=scripts_zip)

    def set_scripts_zip(self, path: Path | str) -> LabSettings:
        resolved = Path(path).expanduser().resolve()
        if not resolved.is_file():
            raise SettingsError(f"scripts.zip path is missing or not a file: {resolved}")
        settings = LabSettings(scripts_zip=str(resolved))
        self._write(settings)
        return settings

    def clear_scripts_zip(self) -> LabSettings:
        settings = LabSettings()
        if self.path.exists():
            self._write(settings)
        return settings

    def _write(self, settings: LabSettings) -> None:
        self.directory.mkdir(parents=True, exist_ok=True)
        if _is_reparse_point(self.directory) or (
            self.path.exists() and _is_reparse_point(self.path)
        ):
            raise SettingsError("settings paths cannot be symlinks or reparse points")
        payload = [f"schema = {SETTINGS_SCHEMA}"]
        if settings.scripts_zip is not None:
            payload.append(f"scripts_zip = {json.dumps(settings.scripts_zip, ensure_ascii=False)}")
        data = "\n".join(payload) + "\n"
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                newline="\n",
                dir=self.directory,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except OSError as exc:
            raise SettingsError(f"cannot write settings {self.path}: {exc}") from exc
        finally:
            if temporary is not None:
                try:
                    Path(temporary).unlink()
                except OSError:
                    pass


def configured_scripts_zip(lab_root: Path | str) -> Path | None:
    value = SettingsStore(lab_root).load().scripts_zip
    return None if value is None else Path(value).expanduser().resolve()


def _is_reparse_point(path: Path) -> bool:
    if not os.path.lexists(path):
        return False
    info = path.lstat()
    attributes = getattr(info, "st_file_attributes", 0)
    return path.is_symlink() or bool(
        attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    )
