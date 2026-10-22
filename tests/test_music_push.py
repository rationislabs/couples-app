"""Checks for pages/music.py preview/apply: Apply appends exactly what the
preview showed.

    ledger_app/.venv/bin/python tests/test_music_push.py

Apply read the count field again, so changing it after the preview appended a
number of tracks nobody had looked at.
"""
import asyncio

import _db  # noqa: F401  (first: never the real ledger.db)

from ledger_app.core import sync_io  # noqa: E402
from ledger_app.pages import music as M  # noqa: E402

calls = []


async def fake_arun(cmd, cwd, timeout=900):
    calls.append(cmd)
    return True, "ok"


def test_apply_uses_the_previewed_count():
    sync_io.arun = fake_arun
    st = M.MusicState(_reflex_internal_init=True)
    st.push_count = "10"
    asyncio.run(M.MusicState.preview_push.fn(st, "Mix"))
    st.push_count = "200"  # the field edited after the preview
    asyncio.run(M.MusicState.apply_push.fn(st))
    applied = calls[-1]
    assert "--apply" in applied
    assert applied[applied.index("--count") + 1] == "10", applied


if __name__ == "__main__":
    for fn in (test_apply_uses_the_previewed_count,):
        fn()
        print(f"  ok  {fn.__name__}")
    print("music push checks passed")
