"""Checks for core/sync_io.py — the scripts the pages start must not freeze
the app while they run.

    hearth/.venv/bin/python tests/test_sync_io.py

The app runs one backend worker: a blocking subprocess.run inside an event
handler stalls every other page and websocket until the script ends.
"""
import asyncio
import pathlib
import sys
import time

import _db  # noqa: F401  (first: never the real hearth.db)

from hearth.core import sync_io  # noqa: E402

CWD = pathlib.Path(__file__).parent


async def main():
    start = time.monotonic()
    job = asyncio.create_task(
        sync_io.arun([sys.executable, "-c", "import time; time.sleep(1.5)"], CWD))
    await asyncio.sleep(0.1)
    # The loop stayed free while the script slept.
    assert time.monotonic() - start < 0.5, "event loop was blocked"
    assert not job.done()
    assert await job == (True, "")

    # A missing interpreter is a failed run, not an exception that would leave
    # a page stuck on busy=True.
    ok, out = await sync_io.arun(["/nonexistent/python"], CWD)
    assert ok is False and "nonexistent" in out, out


asyncio.run(main())
print("sync_io checks passed")
