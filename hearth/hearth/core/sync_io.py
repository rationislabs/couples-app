"""Paths and a subprocess runner for the scripts the app starts.

The pages run the importers and sync scripts under scripts/ as subprocesses,
so they all need the same paths and the same capped output.
"""
from __future__ import annotations

import asyncio
import pathlib
import subprocess

# core/ sits one level deeper than the package root, so this is
# hearth/ (where hearth.db lives), not the package directory.
from .paths import APP, ROOT, json_dir

DATA = json_dir()                 # API caches, nothing executable
DATA.mkdir(parents=True, exist_ok=True)   # gitignored, so absent on a fresh clone
SCRIPTS = ROOT / "scripts"        # import/ seed/ data/ ops/


def run(cmd: list[str], cwd: pathlib.Path, timeout: int = 900) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    except OSError as e:  # missing interpreter or script: a failed run, never a stuck busy flag
        return False, str(e)
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out.strip()[-600:]


async def arun(cmd: list[str], cwd: pathlib.Path, timeout: int = 900) -> tuple[bool, str]:
    """`run` in a worker thread, for event handlers: the app has one backend
    worker, so a blocking subprocess.run there freezes every page until the
    script ends (a Spotify sync can take 30 minutes)."""
    return await asyncio.to_thread(run, cmd, cwd, timeout)
