from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def test_wheel_installs_usable_builtin_extensions(tmp_path: Path) -> None:
    if importlib.util.find_spec("build") is None:
        pytest.skip("wheel smoke test requires the optional 'build' package")

    sdist_dir = tmp_path / "sdist"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--sdist",
            "--no-isolation",
            "--outdir",
            str(sdist_dir),
        ],
        cwd=PROJECT_ROOT,
        check=True,
    )
    sdists = list(sdist_dir.glob("dst_lua_lab-*.tar.gz"))
    assert len(sdists) == 1
    extracted = tmp_path / "source"
    shutil.unpack_archive(sdists[0], extracted)
    source_roots = [item for item in extracted.iterdir() if item.is_dir()]
    assert len(source_roots) == 1
    assert (source_roots[0] / "dstlab.py").is_file()

    wheelhouse = tmp_path / "wheelhouse"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "build",
            "--wheel",
            "--no-isolation",
            "--outdir",
            str(wheelhouse),
        ],
        cwd=source_roots[0],
        check=True,
    )
    wheels = list(wheelhouse.glob("dst_lua_lab-*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())
    assert "dst_lua_lab/_bundled/modules/rpc_capture/module.toml" in names
    assert "dst_lua_lab/_bundled/modules/rpc_capture/lua/bootstrap.lua" in names
    assert "dst_lua_lab/_bundled/casepacks/general_mod_debug/case.toml" in names
    assert not any("/_bundled/" in name and "/tests/" in name for name in names)

    target = tmp_path / "site"
    subprocess.run(
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-deps",
            "--target",
            str(target),
            str(wheel),
        ],
        cwd=tmp_path,
        check=True,
    )

    smoke = r'''
from pathlib import Path

import dst_lua_lab
from dst_lua_lab.extension_runtime import ExtensionSession
from dst_lua_lab.planner import ExtensionPlanner
from dst_lua_lab.registry import ExtensionRegistry
from dst_lua_lab.state import ExtensionState

site = Path(__import__("os").environ["DSTLAB_WHEEL_SITE"]).resolve()
package_file = Path(dst_lua_lab.__file__).resolve()
package_file.relative_to(site)
runtime_root = package_file.parents[2]

catalog = ExtensionRegistry(runtime_root, include_packaged=True).discover()
assert "rpc_capture" in catalog.modules
assert "general_mod_debug" in catalog.cases
assert catalog.modules["rpc_capture"].source == "packaged"

plan = ExtensionPlanner(catalog, ExtensionState()).resolve(
    requested_modules=["rpc_capture"]
)
session = ExtensionSession.from_plan(plan.to_dict(), profile="modload")
assert [item["id"] for item in session.loaded_extensions] == ["rpc_capture"]
assert session.bootstraps("pre_mod")[0].data
print("wheel extension smoke test passed")
'''
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(target)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    environment["DSTLAB_WHEEL_SITE"] = str(target)
    result = subprocess.run(
        [sys.executable, "-c", smoke],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert "wheel extension smoke test passed" in result.stdout

    cli_environment = dict(environment)
    # The wheel itself stays first on PYTHONPATH, while its declared Lupa
    # dependency may come from the test interpreter's normal site-packages.
    cli_environment.pop("PYTHONNOUSERSITE", None)
    cli_environment["PYTHONSAFEPATH"] = "1"
    cli_workspace = tmp_path / "cli-workspace"
    cli_workspace.mkdir()
    trusted_home = tmp_path / "trusted-home"
    cli_environment["DSTLAB_HOME"] = str(trusted_home)
    untrusted_module = cli_workspace / "modules" / "cwd_injected"
    untrusted_module.mkdir(parents=True)
    (untrusted_module / "module.toml").write_text(
        'schema=1\nid="cwd_injected"\nname="bad"\nversion="1"\napi_version="1"\n',
        "utf-8",
    )
    cli_result = subprocess.run(
        [sys.executable, "-m", "dst_lua_lab.cli", "module", "list"],
        cwd=cli_workspace,
        env=cli_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"rpc_capture"' in cli_result.stdout
    assert "cwd_injected" not in cli_result.stdout
    assert not (target / "work").exists()
    assert not (target / "reports").exists()

    reserved_module = subprocess.run(
        [
            sys.executable,
            "-m",
            "dst_lua_lab.cli",
            "module",
            "init",
            "rpc_capture",
        ],
        cwd=cli_workspace,
        env=cli_environment,
        capture_output=True,
        text=True,
    )
    assert reserved_module.returncode == 2
    assert not (trusted_home / "modules" / "rpc_capture").exists()

    reserved_case = subprocess.run(
        [
            sys.executable,
            "-m",
            "dst_lua_lab.cli",
            "case",
            "init",
            "general_mod_debug",
        ],
        cwd=cli_workspace,
        env=cli_environment,
        capture_output=True,
        text=True,
    )
    assert reserved_case.returncode == 2
    assert not (trusted_home / "casepacks" / "general_mod_debug").exists()

    run_result = subprocess.run(
        [
            sys.executable,
            "-m",
            "dst_lua_lab.cli",
            "run",
            "--profile",
            "algorithm",
            "--source",
            "return 42",
        ],
        cwd=cli_workspace,
        env=cli_environment,
        check=True,
        capture_output=True,
        text=True,
    )
    report_line = next(
        line for line in run_result.stdout.splitlines() if line.startswith("report=")
    )
    report = Path(report_line.removeprefix("report=")).resolve()
    report.relative_to(trusted_home / "reports")
    assert (report / "result.json").is_file()
    assert not (target / "work").exists()
    assert not (target / "reports").exists()
