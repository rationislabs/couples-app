import os as _os

import reflex as rx

from ledger_app.core.paths import db_path as _db_path, gallery_dir as _gallery_dir

# Uploads land in gallery/ (under LEDGER_DATA_DIR when set). Set here rather than in
# ledger.sh so `reflex run` started any other way agrees about where photos live.
# setdefault, so an explicit REFLEX_UPLOADED_FILES_DIR still wins. Reflex reads
# this at call time and mounts it at /_upload when the app is built, which is
# after this file is imported. gallery/ is gitignored and backed up nightly.
_os.environ.setdefault("REFLEX_UPLOADED_FILES_DIR", str(_gallery_dir()))

# Loopback binding.
#
# `reflex run` (dev) starts Vite through the "dev" script in .web/package.json,
# which Reflex generates as "react-router dev --host". The bare --host makes
# Vite listen on 0.0.0.0, exposing an app that has no login to the whole
# network. rx.Config has no frontend host option, and editing package.json does
# not survive, because the generator rewrites that key every time.
#
# An earlier version of this file monkey-patched
# reflex_base.constants.installer.PackageJson.Commands.DEV to drop the flag.
# That is removed: the patch only applies where rxconfig is imported, so any
# code path that regenerates package.json without it writes the flag back, and
# Reflex re-reads that file on every line of frontend output. A file that keeps
# changing under that reader is how `reflex run` died with
# JSONDecodeError: Expecting value: line 1 column 1 (char 0).
#
# Use prod mode instead for anything you actually browse:
#   ./ledger.sh start      # --env prod --single-port --backend-host 127.0.0.1
# One port, no Vite dev server, no package.json watcher, and the websocket is
# same-origin, which is also what makes it work through `tailscale serve`.
# Dev mode stays for editing, on loopback via --backend-host.

config = rx.Config(
    app_name="ledger_app",
    db_url=f"sqlite:///{_db_path()}",
    # the API half of the same problem; the default is 0.0.0.0
    backend_host="127.0.0.1",
    # Pin both ports. Unpinned, Reflex probes for a free port at startup while
    # .web/env.json was baked with whatever it chose last time, so the frontend
    # can end up dialling a port the backend is not on — which surfaces as
    # "Cannot connect to server: websocket error" with nothing listening there.
    # 8000 is often held by something else, which is what pushes the probe
    # into guessing, so the backend is moved clear of it.
    frontend_port=3000,
    # backend_port is deliberately NOT pinned here. Prod runs with
    # --single-port, and reflex.py rejects the run outright when prod has both
    # ports set to different values ("frontend and backend must run on the same
    # port"). Left unset, prod puts the backend on the frontend port, and dev
    # gets its backend port from ledger.sh instead.
    # Vite answers 403 to any request whose Host header it does not recognise,
    # which is what `tailscale serve` gets when it proxies the tailnet hostname
    # to 127.0.0.1:3000. Named explicitly rather than True: True accepts any
    # Host, which re-opens DNS rebinding against an app that has no login.
    # The tailnet name comes only from LEDGER_ALLOWED_HOST, and only matters in
    # dev mode (prod serves no Vite).
    vite_allowed_hosts=[
        h for h in (_os.environ.get("LEDGER_ALLOWED_HOST", ""), "localhost", "127.0.0.1") if h
    ],
    show_built_with_reflex=False,
    plugins=[
        rx.plugins.SitemapPlugin(),
        rx.plugins.TailwindV4Plugin(),
        rx.plugins.RadixThemesPlugin(
            theme=rx.theme(appearance="dark", accent_color="orange",
                           # BUBBLY SPIKE.
                           # Revert to "small" to undo; see the block at the
                           # foot of assets/ledger.css for the rest.
                           radius="large")
        ),
    ]
)