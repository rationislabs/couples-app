"""Paths and a subprocess runner for the scripts the app starts.

The pages run the importers and sync scripts under scripts/ as subprocesses,
so they all need the same paths and the same capped output.
"""
from __future__ import annotations

import pathlib
import subprocess

from sqlmodel import create_engine

# core/ sits one level deeper than the package root, so this is
# ledger_app/ (where ledger.db lives), not the package directory.
from .paths import APP, ROOT, db_path, json_dir

DATA = json_dir()                 # API caches, nothing executable
DATA.mkdir(parents=True, exist_ok=True)   # gitignored, so absent on a fresh clone
SCRIPTS = ROOT / "scripts"        # import/ seed/ data/ ops/
ENGINE = create_engine(f"sqlite:///{db_path()}")


def run(cmd: list[str], cwd: pathlib.Path, timeout: int = 900) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return False, f"timed out after {timeout}s"
    out = (r.stdout or "") + (r.stderr or "")
    return r.returncode == 0, out.strip()[-600:]
