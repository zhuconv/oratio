"""`oratio doctor` — diagnose the host environment before a run.

Checks every non-Python dependency Oratio needs and prints an actionable report
plus install hints when something is missing. Useful for uvx / pip installs
where the user didn't clone the repo and doesn't have the README at hand.

Exits 0 when all checks pass, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    hint: str | None = None


def _bin(name: str) -> str | None:
    return shutil.which(name)


def _version(cmd: list[str]) -> str | None:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
    except (OSError, subprocess.TimeoutExpired):
        return None
    out = (r.stdout or r.stderr or "").strip().splitlines()
    return out[0] if out else None


def check_claude() -> Check:
    path = _bin("claude")
    if not path:
        return Check(
            "claude CLI",
            False,
            "not found on PATH",
            hint="npm install -g @anthropic-ai/claude-code && claude  # one-time login",
        )
    v = _version(["claude", "--version"])
    return Check("claude CLI", True, f"{path} ({v or 'unknown version'})")


def check_ffmpeg() -> Check:
    if not _bin("ffmpeg"):
        return Check(
            "ffmpeg",
            False,
            "not found on PATH",
            hint="brew install ffmpeg   # or: apt install ffmpeg",
        )
    v = _version(["ffmpeg", "-version"])
    return Check("ffmpeg", True, v or "installed")


def check_espeak() -> Check:
    path = _bin("espeak-ng") or _bin("espeak")
    if not path:
        return Check(
            "espeak-ng",
            False,
            "not found on PATH (Kokoro phonemizer dep)",
            hint="brew install espeak-ng   # or: apt install espeak-ng",
        )
    return Check("espeak-ng", True, path)


def check_yt_dlp() -> Check:
    try:
        import yt_dlp  # noqa: F401
        import yt_dlp.version as ver
        return Check("yt-dlp (python)", True, f"version {ver.__version__}")
    except Exception as e:
        return Check(
            "yt-dlp (python)",
            False,
            f"import failed: {e}",
            hint="uv sync   # reinstall python deps",
        )


def check_claude_sdk() -> Check:
    try:
        import claude_agent_sdk  # noqa: F401
        return Check("claude-agent-sdk", True, "importable")
    except Exception as e:
        return Check(
            "claude-agent-sdk",
            False,
            f"import failed: {e}",
            hint="uv sync",
        )


def check_kokoro() -> Check:
    try:
        import kokoro  # noqa: F401
        return Check("kokoro TTS", True, "importable (first run downloads ~330 MB)")
    except Exception as e:
        return Check(
            "kokoro TTS",
            False,
            f"import failed: {e}",
            hint="uv sync",
        )


def check_api_key() -> Check:
    """Informational only — having the key set is not an error; Oratio clobbers it."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return Check(
            "ANTHROPIC_API_KEY",
            True,
            "set — Oratio will clobber this at runtime so billing goes through your Pro/Max subscription",
        )
    return Check("ANTHROPIC_API_KEY", True, "unset (fine — subscription auth is used)")


ALL_CHECKS = (
    check_claude,
    check_ffmpeg,
    check_espeak,
    check_yt_dlp,
    check_claude_sdk,
    check_kokoro,
    check_api_key,
)


def _emit_text(checks: list[Check]) -> int:
    ok_icon = "OK  "
    bad_icon = "MISS"
    failed = 0
    print(f"oratio doctor  —  {platform.platform()}")
    print("=" * 60)
    for c in checks:
        prefix = ok_icon if c.ok else bad_icon
        print(f"  [{prefix}] {c.name:<22} {c.detail}")
        if not c.ok:
            failed += 1
            if c.hint:
                print(f"         hint: {c.hint}")
    print("=" * 60)
    if failed:
        print(f"{failed} issue(s). Fix the hints above and rerun `oratio doctor`.")
        return 1
    print("All dependencies present. You're ready to run `oratio <url-or-name>`.")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Check Oratio's host dependencies (claude CLI, ffmpeg, espeak-ng, python deps).",
    )
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON.")
    args = ap.parse_args()

    checks = [fn() for fn in ALL_CHECKS]
    if args.json:
        print(json.dumps(
            [{"name": c.name, "ok": c.ok, "detail": c.detail, "hint": c.hint} for c in checks],
            indent=2,
        ))
        sys.exit(0 if all(c.ok for c in checks) else 1)
    sys.exit(_emit_text(checks))


if __name__ == "__main__":
    main()
