#!/usr/bin/env python3
"""Secret storage for the media ledger.

    ./ledger_app/.venv/bin/python security.py --check      # posture report
    ./ledger_app/.venv/bin/python security.py --encrypt    # .env -> secrets.enc
    ./ledger_app/.venv/bin/python security.py --shred-env  # remove plaintext .env
    ./ledger_app/.venv/bin/python security.py --rekey      # new passphrase

What this protects against, and what it does not
------------------------------------------------
Encrypting secrets at rest only helps when the key is not stored beside the
ciphertext. If the key sat in a file next to `secrets.enc`, anyone who could
read one could read the other and nothing would be gained. So the key is never
written to disk: it is derived from a passphrase with scrypt, and the passphrase
is held only in the OS keyring (unlocked by your login session) or supplied
through the environment by a service manager.

That defends against a copied file: an old backup, a synced folder, a disk sold
without wiping, a `tar` of the project sent somewhere. It does **not** defend
against someone who already has your logged-in user account, because the app has
to decrypt to run and so does anything running as you.

The larger exposure is usually not these tokens — it is an unencrypted disk,
where `ledger.db` (every saved place, the date log and the private pages) is
readable by anyone who takes the machine. Full-disk encryption fixes that;
this file cannot.

Resolution order used by the app
--------------------------------
1. a real environment variable, so a deployment can inject secrets and never
   place them on disk (systemd `LoadCredential`, a container secret);
2. `secrets.enc`, decrypted with the passphrase from the keyring;
3. plaintext `.env`, which still works but reports itself as unprotected.
"""
from __future__ import annotations

import base64
import getpass
import json
import os
import pathlib
import secrets as _secrets
import stat
import sys

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

ROOT = pathlib.Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
ENC_FILE = ROOT / "secrets.enc"

KEYRING_SERVICE = "media-ledger"
KEYRING_USER = "secrets-passphrase"
PASSPHRASE_ENV = "LEDGER_PASSPHRASE"

# scrypt parameters. n=2**15 costs ~100 ms per derivation here, which is
# irrelevant once per process start and expensive in bulk for anyone guessing.
_SCRYPT_N = 2 ** 15
_SCRYPT_R = 8
_SCRYPT_P = 1

# Values shorter than this are identifiers rather than secrets, so they stay
# readable; SPOTIFY_REDIRECT_URI is a localhost callback and not sensitive.
_MIN_SECRET_LEN = 20
_NEVER_SECRET = {"SPOTIFY_REDIRECT_URI"}


# ---------------------------------------------------------------------------
# key handling
# ---------------------------------------------------------------------------
def _derive(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=32, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return base64.urlsafe_b64encode(kdf.derive(passphrase.encode()))


def _keyring():
    try:
        import keyring
        return keyring
    except Exception:                                        # noqa: BLE001
        return None


def _passphrase(*, prompt_ok: bool = True, confirm: bool = False) -> str:
    """From the environment, then the keyring, then a prompt.

    The environment comes first so a service manager can supply it without a
    keyring or a terminal, which is how this will run on a always-on box.
    """
    if (value := os.environ.get(PASSPHRASE_ENV)):
        return value

    kr = _keyring()
    if kr is not None:
        try:
            if (value := kr.get_password(KEYRING_SERVICE, KEYRING_USER)):
                return value
        except Exception:                                    # noqa: BLE001
            pass                                             # locked or absent

    if not prompt_ok or not sys.stdin.isatty():
        raise SystemExit(
            f"no passphrase available: set {PASSPHRASE_ENV}, or store one in the "
            f"keyring by running `security.py --encrypt` from a terminal"
        )

    value = getpass.getpass("Passphrase for the ledger secrets: ")
    if confirm and value != getpass.getpass("Again: "):
        raise SystemExit("passphrases did not match")
    if not value:
        raise SystemExit("empty passphrase")
    return value


def _remember(passphrase: str) -> bool:
    kr = _keyring()
    if kr is None:
        return False
    try:
        kr.set_password(KEYRING_SERVICE, KEYRING_USER, passphrase)
        return True
    except Exception:                                        # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# store
# ---------------------------------------------------------------------------
def _parse_env(path: pathlib.Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


def _write_private(path: pathlib.Path, data: str) -> None:
    """Create with 0600 from the start, rather than writing then chmod-ing,
    which would leave a readable window."""
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        fh.write(data)


def encrypt_store(values: dict[str, str], passphrase: str) -> None:
    salt = _secrets.token_bytes(16)
    token = Fernet(_derive(passphrase, salt)).encrypt(
        json.dumps(values).encode())
    envelope = {
        "version": 1,
        "kdf": {"name": "scrypt", "n": _SCRYPT_N, "r": _SCRYPT_R,
                "p": _SCRYPT_P, "salt": base64.b64encode(salt).decode()},
        "ciphertext": token.decode(),
    }
    _write_private(ENC_FILE, json.dumps(envelope, indent=2) + "\n")


def decrypt_store(passphrase: str | None = None) -> dict[str, str]:
    if not ENC_FILE.exists():
        return {}
    envelope = json.loads(ENC_FILE.read_text())
    kdf = envelope["kdf"]
    salt = base64.b64decode(kdf["salt"])
    phrase = passphrase if passphrase is not None else _passphrase()
    key = base64.urlsafe_b64encode(
        Scrypt(salt=salt, length=32, n=kdf["n"], r=kdf["r"],
               p=kdf["p"]).derive(phrase.encode()))
    try:
        plain = Fernet(key).decrypt(envelope["ciphertext"].encode())
    except InvalidToken:
        raise SystemExit("wrong passphrase, or secrets.enc has been altered")
    return json.loads(plain)


# ---------------------------------------------------------------------------
# the accessor the rest of the app uses
# ---------------------------------------------------------------------------
_cache: dict[str, str] | None = None


def load(*, quiet: bool = False) -> dict[str, str]:
    """Every secret, from the first source that has it. Cached per process so a
    passphrase prompt or a scrypt derivation happens at most once."""
    global _cache
    if _cache is not None:
        return _cache

    values: dict[str, str] = {}
    source = "none"

    if ENC_FILE.exists():
        values = decrypt_store()
        source = "secrets.enc"
    elif ENV_FILE.exists():
        values = _parse_env(ENV_FILE)
        source = ".env (plaintext)"
        if not quiet:
            print("security: reading plaintext .env; run "
                  "`python security.py --encrypt` to protect it", file=sys.stderr)

    # A real environment variable always wins, so a deployment can override
    # without touching either file.
    for key in list(values) + [k for k in os.environ if k.startswith(
            ("TMDB_", "SPOTIFY_", "LASTFM_"))]:
        if (found := os.environ.get(key)):
            values[key] = found

    _cache = values
    if not quiet:
        print(f"security: {len(values)} secrets loaded from {source}",
              file=sys.stderr)
    return values


def get(name: str, default: str = "") -> str:
    return load(quiet=True).get(name, default)


def export_to_environ() -> int:
    """Put the secrets into os.environ for code that reads them directly.

    Scripts here already use os.environ, so this keeps `security.py` a drop-in
    rather than a rewrite of every caller.
    """
    count = 0
    for key, value in load(quiet=True).items():
        if value and key not in os.environ:
            os.environ[key] = value
            count += 1
    return count


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _is_secret(key: str, value: str) -> bool:
    return len(value) >= _MIN_SECRET_LEN and key not in _NEVER_SECRET


def cmd_encrypt() -> int:
    plain = _parse_env(ENV_FILE)
    if not plain:
        print(f"nothing to encrypt: no readable {ENV_FILE.name}")
        return 1
    if ENC_FILE.exists():
        print(f"{ENC_FILE.name} already exists — use --rekey to change the "
              f"passphrase, or delete it first")
        return 1

    secret_keys = [k for k, v in plain.items() if _is_secret(k, v)]
    print(f"encrypting {len(plain)} values ({len(secret_keys)} of them secret): "
          + ", ".join(plain))
    passphrase = _passphrase(confirm=True)
    encrypt_store(plain, passphrase)

    # Prove it round-trips before anything suggests deleting the plaintext.
    if decrypt_store(passphrase) != plain:
        ENC_FILE.unlink(missing_ok=True)
        print("round-trip check failed; wrote nothing")
        return 1

    stored = _remember(passphrase)
    print(f"wrote {ENC_FILE.name} (0600), verified it decrypts")
    print("passphrase saved to the OS keyring" if stored else
          "could not reach the OS keyring — set LEDGER_PASSPHRASE to run headless")
    print(f"\n{ENV_FILE.name} is still there and still plaintext. "
          f"Remove it with:\n  python security.py --shred-env")
    return 0


def cmd_shred_env() -> int:
    if not ENC_FILE.exists():
        print("refusing: no secrets.enc, so .env is the only copy")
        return 1
    plain = _parse_env(ENV_FILE)
    if not plain:
        print(f"{ENV_FILE.name} is already gone")
        return 0
    if decrypt_store() != plain:
        print("refusing: secrets.enc does not match .env exactly. "
              "Run --rekey after reconciling them.")
        return 1
    # Overwrite before unlinking. On a copy-on-write or flash filesystem this is
    # not a guarantee, which is another argument for encrypting the disk.
    size = ENV_FILE.stat().st_size
    with open(ENV_FILE, "r+b") as fh:
        fh.write(_secrets.token_bytes(size))
        fh.flush()
        os.fsync(fh.fileno())
    ENV_FILE.unlink()
    print(f"overwrote and removed {ENV_FILE.name}; secrets.enc is now the only copy")
    print("keep a backup of the passphrase somewhere offline — losing it means "
          "re-issuing every token")
    return 0


def cmd_rekey() -> int:
    if not ENC_FILE.exists():
        print("no secrets.enc to rekey")
        return 1
    print("current passphrase:")
    values = decrypt_store(_passphrase())
    print("new passphrase:")
    fresh = _passphrase(confirm=True)
    encrypt_store(values, fresh)
    if decrypt_store(fresh) != values:
        print("round-trip check failed after rekey")
        return 1
    _remember(fresh)
    print(f"rekeyed {ENC_FILE.name} and updated the keyring")
    return 0


def cmd_check() -> int:
    problems = 0

    def line(status: str, msg: str) -> None:
        print(f"  {status:5} {msg}")

    print("secret storage")
    if ENC_FILE.exists():
        mode = stat.S_IMODE(ENC_FILE.stat().st_mode)
        line("ok" if not mode & 0o077 else "FAIL",
             f"{ENC_FILE.name} present, mode {oct(mode)}")
        problems += bool(mode & 0o077)
        try:
            values = decrypt_store()
            line("ok", f"decrypts, {len(values)} values")
        except SystemExit as exc:
            line("FAIL", f"cannot decrypt: {exc}")
            problems += 1
    else:
        line("warn", "no secrets.enc — secrets are plaintext")

    if ENV_FILE.exists():
        mode = stat.S_IMODE(ENV_FILE.stat().st_mode)
        readable = bool(mode & 0o077)
        line("FAIL" if readable else "warn",
             f"{ENV_FILE.name} still exists, mode {oct(mode)}"
             + (" — other accounts can read it" if readable else
                " — owner-only, but plaintext"))
        problems += readable

    kr = _keyring()
    print("passphrase")
    if os.environ.get(PASSPHRASE_ENV):
        line("ok", f"{PASSPHRASE_ENV} set in the environment")
    elif kr is not None:
        try:
            line("ok" if kr.get_password(KEYRING_SERVICE, KEYRING_USER)
                 else "warn",
                 "keyring reachable" if kr.get_password(
                     KEYRING_SERVICE, KEYRING_USER)
                 else "keyring reachable but holds no passphrase")
        except Exception as exc:                             # noqa: BLE001
            line("warn", f"keyring unreachable: {type(exc).__name__}")
    else:
        line("warn", "no keyring module and no LEDGER_PASSPHRASE")

    print("disk")
    import subprocess
    blk = subprocess.run(["lsblk", "-o", "FSTYPE"], capture_output=True,
                         text=True).stdout.lower()
    if "crypto_luks" in blk:
        line("ok", "an encrypted volume exists")
    else:
        line("FAIL", "no encrypted volume: ledger.db and every backup are "
                     "readable by anyone who takes this machine")
        problems += 1

    print()
    print(f"{problems} problem(s)" if problems else "no problems")
    return 1 if problems else 0


def main(argv: list[str]) -> int:
    commands = {"--encrypt": cmd_encrypt, "--shred-env": cmd_shred_env,
                "--rekey": cmd_rekey, "--check": cmd_check}
    if len(argv) != 1 or argv[0] not in commands:
        print(__doc__)
        return 2
    return commands[argv[0]]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
