"""Every test that imports the app sets up a throwaway database first.

    hearth/.venv/bin/python tests/test_isolation.py

state.py builds ENGINE from HEARTH_DATA_DIR at import. tests/run.sh sets it,
but a file run on its own (as each docstring says) without `import _db`
first opens the real hearth/hearth.db, and some tests delete rows.
"""
import pathlib
import re

HERE = pathlib.Path(__file__).parent

bad = []
for f in sorted(HERE.glob("test_*.py")):
    lines = f.read_text().splitlines()
    app = next((i for i, line in enumerate(lines)
                if re.match(r"\s*(from hearth|import hearth|import spotify_sync)", line)), None)
    if app is None:
        continue
    db = next((i for i, line in enumerate(lines) if re.match(r"import _db\b", line)), None)
    if db is None or db > app:
        bad.append(f.name)

assert not bad, f"import _db before the app in: {', '.join(bad)}"
print("isolation checks passed")
