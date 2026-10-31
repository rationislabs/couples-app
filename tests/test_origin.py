"""Checks for core/origin.py — which origins may open the websocket, which
Host headers the backend answers.

    hearth/.venv/bin/python tests/test_origin.py

The app has no login, so these two lists are what keeps a web page on another
site (or a DNS-rebinding page) from driving it.
"""
import os
import pathlib
import sys

import warnings

import _db  # noqa: F401  (first: never the real hearth.db)

warnings.filterwarnings("ignore", message="Using `httpx` with `starlette.testclient`")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "hearth"))

from starlette.applications import Starlette  # noqa: E402
from starlette.responses import PlainTextResponse  # noqa: E402
from starlette.routing import Route  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402

from hearth.core import origin  # noqa: E402

LOCAL = ["http://localhost:3000", "http://127.0.0.1:3000",
         "http://localhost:3100", "http://127.0.0.1:3100"]


def with_env(host, port=None):
    for k, v in (("HEARTH_ALLOWED_HOST", host), ("PORT", port)):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


with_env(None)
assert origin.allowed_origins() == LOCAL, origin.allowed_origins()
assert origin.allowed_hosts() == ["localhost", "127.0.0.1"]

with_env("hearth.example.ts.net")
assert origin.allowed_origins() == ["https://hearth.example.ts.net", *LOCAL]
assert origin.allowed_hosts() == ["hearth.example.ts.net", "localhost", "127.0.0.1"]

# A pasted URL or a trailing slash is still the same host name.
for pasted in ("https://hearth.example.ts.net/", "hearth.example.ts.net:443", " hearth.example.ts.net "):
    with_env(pasted)
    assert origin.allowed_hosts()[0] == "hearth.example.ts.net", origin.allowed_hosts()

with_env(None, port="3300")
assert "http://127.0.0.1:3300" in origin.allowed_origins()
assert "*" not in origin.allowed_origins()

# rxconfig hands the list to Reflex, never the "*" default.
with_env("hearth.example.ts.net")
import rxconfig  # noqa: E402
assert list(rxconfig.config.cors_allowed_origins) == origin.allowed_origins()

# The Host check wraps the backend.
ok = Starlette(routes=[Route("/ping", lambda r: PlainTextResponse("pong"))])
client = TestClient(origin.trusted_hosts(ok))
assert client.get("/ping", headers={"host": "evil.example"}).status_code == 400
assert client.get("/ping", headers={"host": "hearth.example.ts.net"}).status_code == 200
assert client.get("/ping", headers={"host": "127.0.0.1:3300"}).status_code == 200
print("origin checks passed")
