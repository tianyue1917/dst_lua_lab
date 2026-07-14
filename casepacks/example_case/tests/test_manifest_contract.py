from pathlib import Path


def test_case_pack_is_synthetic_and_self_contained() -> None:
    root = Path(__file__).resolve().parents[1]
    manifest = (root / "case.toml").read_text("utf-8")
    assert 'id = "example_case"' in manifest
    assert 'required_modules = ["example_trace"]' in manifest
    assert "workshop_id" not in manifest
