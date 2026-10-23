"""Who may talk to the backend. The app has no login, so this is the lock.

Reflex's default lets the websocket accept any Origin: any web page a tailnet
device opens could drive the app. The tailnet name comes from
LEDGER_ALLOWED_HOST (setup.sh --host writes it); each household sets its own.
"""
import os

from starlette.middleware.trustedhost import TrustedHostMiddleware

LOCAL_HOSTS = ("localhost", "127.0.0.1")
LOCAL_PORTS = ("3000", "3100")  # the container's and ledger.sh's port


def _tailnet_host() -> str:
    """The host name alone: a pasted https://name/ or name:443 means the same host."""
    host = os.environ.get("LEDGER_ALLOWED_HOST", "").strip()
    host = host.split("://", 1)[-1].split("/", 1)[0]
    return host.rsplit(":", 1)[0] if ":" in host else host


def allowed_hosts() -> list[str]:
    return [h for h in (_tailnet_host(), *LOCAL_HOSTS) if h]


def allowed_origins() -> list[str]:
    ports = dict.fromkeys((*LOCAL_PORTS, os.environ.get("PORT", "3000")))
    local = [f"http://{h}:{p}" for p in ports for h in LOCAL_HOSTS]
    host = _tailnet_host()
    return ([f"https://{host}"] if host else []) + local


def trusted_hosts(app):
    """Answer only our own Host names: a DNS-rebinding page sends its own."""
    return TrustedHostMiddleware(app, allowed_hosts=allowed_hosts())
