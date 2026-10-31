"""Checks for scripts/ops/security.py — it must never leave the app without
its keys.

    hearth/.venv/bin/python tests/test_security.py

Nothing in the app or the scripts reads secrets.enc: they all read .env. A
command that deletes .env after encrypting it strands every API key.
"""
import importlib.util
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("security", ROOT / "scripts/ops/security.py")
security = importlib.util.module_from_spec(spec)
spec.loader.exec_module(security)


def test_no_command_removes_env():
    assert not hasattr(security, "cmd_shred_env")
    assert "--shred-env" not in (security.__doc__ or "")
    assert security.main(["--shred-env"]) == 2  # unknown command: usage, nothing done


def test_secrets_enc_never_committed_or_baked_in():
    for ignore in (".gitignore", ".dockerignore"):
        lines = (ROOT / ignore).read_text().splitlines()
        assert "secrets.enc" in lines, f"secrets.enc missing from {ignore}"
    r = subprocess.run(["git", "check-ignore", "-q", "secrets.enc"], cwd=ROOT)
    assert r.returncode == 0


if __name__ == "__main__":
    for fn in (test_no_command_removes_env, test_secrets_enc_never_committed_or_baked_in):
        fn()
        print(f"  ok  {fn.__name__}")
    print("security checks passed")
