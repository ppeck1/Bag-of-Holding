"""Non-destructive cleanup audit for Bag of Holding.

Lists cleanup candidates only. It does not delete files.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def size_bytes(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    total = 0
    for p in path.rglob("*"):
        try:
            if p.is_file():
                total += p.stat().st_size
        except OSError:
            pass
    return total


def rel(path: Path) -> str:
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return str(path)


def collect() -> dict[str, list[Path]]:
    patterns = {
        "__pycache__": [p for p in ROOT.rglob("__pycache__") if p.is_dir()],
        ".pytest_cache": [p for p in ROOT.rglob(".pytest_cache") if p.is_dir()],
        "*.pyc": [p for p in ROOT.rglob("*.pyc") if p.is_file()],
        "build_dist": [p for name in ("build", "dist") for p in ROOT.rglob(name) if p.is_dir()],
        "reports_logs": [p for pat in ("*.log", "*report*.json", "*report*.md") for p in ROOT.rglob(pat) if p.is_file()],
        "runtime_scratch": [p for name in ("scratch", "tmp", "temp") for p in ROOT.rglob(name) if p.is_dir()],
    }
    return patterns


def git_untracked() -> list[str]:
    try:
        proc = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            cwd=str(ROOT),
            text=True,
            capture_output=True,
            timeout=10,
            check=False,
        )
    except Exception:
        return []
    if proc.returncode != 0:
        return []
    return [line for line in proc.stdout.splitlines() if line.strip()]


def main() -> int:
    print("# BOH Cleanup Audit (non-destructive)")
    print(f"root={ROOT}")
    print()
    for group, paths in collect().items():
        print(f"## {group}: {len(paths)} candidate(s)")
        for p in paths[:80]:
            print(f"- {rel(p)} ({size_bytes(p)} bytes)")
        if len(paths) > 80:
            print(f"- ... {len(paths) - 80} more")
        print()

    library = Path(os.environ.get("BOH_LIBRARY", ROOT / "library")).resolve()
    quarantine = library / ".boh_quarantine"
    print("## library")
    print(f"- {rel(library)} exists={library.exists()} size={size_bytes(library) if library.exists() else 0} bytes")
    print(f"- {rel(quarantine)} exists={quarantine.exists()} size={size_bytes(quarantine) if quarantine.exists() else 0} bytes")
    print()

    untracked = git_untracked()
    print(f"## git untracked: {len(untracked)} candidate(s)")
    for item in untracked[:120]:
        print(f"- {item}")
    if len(untracked) > 120:
        print(f"- ... {len(untracked) - 120} more")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

