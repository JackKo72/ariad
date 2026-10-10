"""Shared env-var file check for the annotation/eval scripts (tasks/08,
tasks/09). A bare "Usage:" line on a typo'd or not-yet-copied path made
the real problem invisible; this says which variable, which path, and
what IS in that folder."""

from __future__ import annotations

import os
from pathlib import Path


def require_files(names: list[str], usage: str) -> list[Path] | None:
    """Paths for env vars `names`, or None after printing what is wrong."""
    missing_vars = [n for n in names if not os.environ.get(n)]
    if missing_vars:
        print(f"{', '.join(missing_vars)} not set.\nUsage: {usage}")
        return None
    paths = [Path(os.environ[n]) for n in names]
    ok = True
    for name, path in zip(names, paths):
        if path.is_file():
            continue
        ok = False
        print(f"{name}={path}: file not found (cwd {Path.cwd()})")
        folder = path.parent if path.parent.is_dir() else None
        if folder is not None:
            present = sorted(p.name for p in folder.iterdir() if p.is_file())
            print(f"  {folder}/ contains: {', '.join(present) if present else '(empty)'}")
        else:
            print(f"  folder {path.parent} does not exist")
    return paths if ok else None
