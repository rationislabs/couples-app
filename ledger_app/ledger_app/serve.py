"""Start the production backend with the frontend the image build compiled.

`reflex run --env prod` recompiles and rebuilds the frontend on every start
(reflex/reflex.py `_run_prod` calls `_compile_app()` then
`build.setup_frontend_prod()`), which needs Bun at runtime and takes minutes.
This starts only the backend and mounts the compiled frontend into it — the
mount `reflex run --env preview` uses (`exec.get_frontend_mount`).

    python -m ledger_app.serve        # from ledger_app/, where rxconfig.py is
"""
import os

os.environ.setdefault("REFLEX_ENV_MODE", "prod")

from reflex_base.environment import environment  # noqa: E402
from reflex.utils import exec as rx_exec  # noqa: E402

# Internal vars are stored as `__<NAME>`, so a plain os.environ["REFLEX_SKIP_COMPILE"]
# is ignored; set it through reflex so the workers (which inherit the env) skip the compile.
environment.REFLEX_SKIP_COMPILE.set(True)

if __name__ == "__main__":
    rx_exec.run_backend_prod(
        os.environ.get("LEDGER_BIND_HOST", "127.0.0.1"),
        int(os.environ.get("PORT", "3000")),
        mount_frontend_compiled_app=True,
    )
