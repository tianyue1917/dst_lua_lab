"""Fail when repository content looks like local input or a committed secret."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MAX_TEXT_BYTES = 2 * 1024 * 1024


def _pattern(*parts: str) -> re.Pattern[str]:
    # Split sensitive literals so this scanner does not flag its own source.
    return re.compile("".join(parts), re.IGNORECASE)


TEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("absolute Windows user path", _pattern(r"\b[A-Z]:", r"[\\/]", "Users", r"[\\/]")),
    ("absolute Unix home path", _pattern(r"/(?:home|Users)/", r"[^/\s]+/")),
    (
        "Klei user id",
        _pattern(
            r"\bK",
            r"U_(?!(?:OFFLINE|SYNTHETIC|TEST|EXAMPLE)\b)[A-Za-z0-9_-]{6,}\b",
        ),
    ),
    (
        "credential-like encoded assignment",
        _pattern(
            r"\b(?:redeem[_-]?code|cdk|credential|access[_-]?token)\s*[:=]\s*",
            r"['\"][A-Za-z0-9+/=_-]{16,}['\"]",
        ),
    ),
    ("PEM private key", _pattern("-----BEGIN ", r"(?:RSA |EC |OPENSSH )?", "PRIVATE KEY-----")),
    ("GitHub token", _pattern(r"\b(?:ghp|gho|ghu|ghs|ghr)_", r"[A-Za-z0-9]{20,}\b")),
    ("GitHub fine-grained token", _pattern(r"\bgithub_pat_", r"[A-Za-z0-9_]{20,}\b")),
    ("AWS access key", _pattern(r"\bAKIA", r"[A-Z0-9]{16}\b")),
    ("OpenAI-style secret key", _pattern(r"\bsk-", r"[A-Za-z0-9_-]{20,}\b")),
    (
        "literal credential assignment",
        _pattern(
            r"\b(?:passw(?:or)?d|api[_-]?key|client[_-]?secret|access[_-]?token)\s*[:=]\s*",
            r"['\"][^'\"\r\n]{8,}['\"]",
        ),
    ),
    ("credential in URL", _pattern(r"https?://[^/\s:@]+:", r"[^/\s@]+@")),
)


def _repository_files() -> list[Path]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    return [ROOT / Path(value.decode("utf-8")) for value in result.stdout.split(b"\0") if value]


def _path_problem(relative: Path) -> str | None:
    portable = relative.as_posix().lower()
    name = relative.name.lower()
    if portable.startswith("analysis/") or portable.startswith("mods/"):
        return "private input tree"
    if portable.startswith("workshop-") or "/workshop-" in portable:
        return "Workshop source tree"
    if name == "scripts.zip" or name == "cluster" + "_token.txt":
        return "local game or cluster input"
    if name == ".env" or name.startswith(".env."):
        return "environment file"
    if name.endswith((".pem", ".key", ".pfx", ".log", ".pyc", ".pyo")):
        return "credential, log, or generated file"
    if "__pycache__" in relative.parts or ".dstlab" in relative.parts:
        return "generated runtime state"
    return None


def main() -> int:
    findings: list[str] = []
    for path in _repository_files():
        relative = path.relative_to(ROOT)
        path_problem = _path_problem(relative)
        if path_problem:
            findings.append(f"{relative.as_posix()}: forbidden path ({path_problem})")
            continue
        if path.is_symlink():
            findings.append(f"{relative.as_posix()}: symbolic links are not allowed")
            continue
        data = path.read_bytes()
        if len(data) > MAX_TEXT_BYTES:
            findings.append(f"{relative.as_posix()}: file exceeds {MAX_TEXT_BYTES} bytes")
            continue
        if b"\0" in data:
            findings.append(f"{relative.as_posix()}: binary or UTF-16 content is not allowed")
            continue
        text = data.decode("utf-8", errors="replace")
        for label, pattern in TEXT_PATTERNS:
            match = pattern.search(text)
            if match:
                line = text.count("\n", 0, match.start()) + 1
                findings.append(f"{relative.as_posix()}:{line}: {label}")

    if findings:
        print("Sensitive-content scan failed:", file=sys.stderr)
        for finding in findings:
            print(f"  - {finding}", file=sys.stderr)
        return 1
    print("Sensitive-content scan passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
