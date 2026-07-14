from pathlib import Path


def test_frontend_case_manifest_exists() -> None:
    assert (Path(__file__).resolve().parents[1] / "case.toml").is_file()
