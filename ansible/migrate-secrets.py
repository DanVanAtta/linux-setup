#!/usr/bin/env python3
"""Move hardcoded secrets in ~/.pat_tokens into the GNOME keyring.

~/.pat_tokens is sourced by ~/.bashrc and, in steady state, holds only load
lines — 'export VAR=$(secret-tool lookup service pat_tokens key VAR ...)' — so
it carries no secret at rest. To add or rotate a secret, drop its value in
hardcoded ('export VAR=thevalue') and run 'just migrate-secrets': the value is
cleared from and re-stored in the keyring, and the line is rewritten to its
load form only once the store is proven durable. Add and rotate are the same
gesture, and the file returns to secret-free.

Durability is not assumed from a read-back: gnome-keyring will happily accept a
store into the in-memory 'session' collection (eg: when no default/login
collection is unlocked), where a same-session look-up still succeeds but the
secret evaporates at logout. So a store counts as durable only if it also wrote
an on-disk '*.keyring' collection. A secret that cannot be proven durable is
left hardcoded in the file and its manual 'secret-tool store' command printed,
so a plaintext copy is never destroyed on the strength of a phantom store.

Ansible does not manage this file's contents — only that ~/.bashrc sources it.
This script is the sole populate path; keep it standalone (stdlib + secret-tool).
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

TOKENS_FILE = Path.home() / ".pat_tokens"
KEYRING_SERVICE = "pat_tokens"
MAX_LEN = 4096
# Persistent gnome-keyring collections live here as '*.keyring' files; the
# transient 'session' collection does not, which is how a durable store is told
# apart from one that will not survive logout.
KEYRINGS_DIR = Path.home() / ".local" / "share" / "keyrings"

EXPORT_RE = re.compile(r"^export\s+(\w+)=(.*)$")
# Only names that read as a credential are eligible, so a bare-literal config
# export (eg: a username) is never mistaken for a secret to be swallowed.
SECRET_NAME_RE = re.compile(r"TOKEN|KEY|SECRET|PASSWORD|VAULT|LICENSE", re.IGNORECASE)


def strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
        return value[1:-1]
    return value


def is_hardcoded_secret(var: str, rhs: str) -> bool:
    """A line worth migrating: a credential-named var whose value is a literal.

    A '$' in the RHS means the value is loaded ('$(secret-tool ...)') or derived
    from another var ('"$LINODE_TOKEN"'), so it is already keyring-backed and
    left untouched.
    """
    return SECRET_NAME_RE.search(var) is not None and "$" not in rhs


def validate(value: str) -> str | None:
    """Return a redacted reason the value is unusable, or None if it passes."""
    if not value:
        return "empty value"
    if any(c.isspace() for c in value):
        return "contains whitespace — likely a truncated multi-line paste"
    if len(value) > MAX_LEN:
        return f"length {len(value)} exceeds {MAX_LEN} — likely a run-on paste"
    return None


def keyring_fingerprint() -> dict[str, int]:
    """Modification times of every on-disk collection, keyed by filename."""
    prints: dict[str, int] = {}
    if KEYRINGS_DIR.is_dir():
        for path in KEYRINGS_DIR.glob("*.keyring"):
            try:
                prints[path.name] = path.stat().st_mtime_ns
            except OSError:
                pass
    return prints


def wrote_to_disk(before: dict[str, int], after: dict[str, int]) -> bool:
    """True if any on-disk collection was created or rewritten between snapshots."""
    return any(name not in before or mtime > before[name]
               for name, mtime in after.items())


def store_and_prove(var: str, value: str) -> str | None:
    """Store the value and prove it landed durably; redacted error or None.

    A read-back alone is not proof — it passes even for a store into the
    in-memory 'session' collection. Durability is confirmed only by an on-disk
    collection write, snapshotted around the store.
    """
    before = keyring_fingerprint()
    subprocess.run(["secret-tool", "clear", "service", KEYRING_SERVICE, "key", var],
                   capture_output=True)
    store = subprocess.run(
        ["secret-tool", "store", f"--label={var}", "service", KEYRING_SERVICE, "key", var],
        input=value.encode(), capture_output=True)
    if store.returncode != 0:
        return f"secret-tool store failed: {store.stderr.decode().strip()}"
    readback = subprocess.run(
        ["secret-tool", "lookup", "service", KEYRING_SERVICE, "key", var],
        capture_output=True)
    if readback.returncode != 0 or readback.stdout.decode() != value:
        return "read-back did not match what was stored"
    if not wrote_to_disk(before, keyring_fingerprint()):
        return ("stored only in the in-memory 'session' keyring — no on-disk "
                "collection was written, so it would not survive logout")
    return None


def manual_store_cmd(var: str, value: str) -> str:
    """The 'secret-tool store' a human can paste into an unlocked desktop session."""
    return (f"printf %s {shlex.quote(value)} | "
            f"secret-tool store --label={var} service {KEYRING_SERVICE} key {var}")


def load_line(var: str) -> str:
    return f"export {var}=$(secret-tool lookup service {KEYRING_SERVICE} key {var} 2>/dev/null)"


def rewrite(path: Path, replacements: dict[int, str]) -> None:
    """Rewrite the file atomically, swapping migrated lines for their load form,
    preserving 0600 and every other line verbatim."""
    lines = path.read_text().splitlines()
    for idx, new in replacements.items():
        lines[idx] = new
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(lines) + "\n")
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main() -> int:
    if subprocess.run(["which", "secret-tool"], capture_output=True).returncode != 0:
        print("secret-tool not found — install libsecret-tools first.", file=sys.stderr)
        return 1
    if not TOKENS_FILE.exists():
        print(f"No {TOKENS_FILE}.", file=sys.stderr)
        return 1
    mode = TOKENS_FILE.stat().st_mode & 0o777
    if mode != 0o600:
        print(f"{TOKENS_FILE} is mode {oct(mode)}; run 'chmod 600 {TOKENS_FILE}' and re-run.", file=sys.stderr)
        return 1

    replacements: dict[int, str] = {}
    failures = 0
    for idx, raw in enumerate(TOKENS_FILE.read_text().splitlines()):
        m = EXPORT_RE.match(raw.strip())
        if not m:
            continue
        var, rhs = m.group(1), m.group(2).strip()
        if not is_hardcoded_secret(var, rhs):
            continue
        value = strip_quotes(rhs)
        reason = validate(value) or store_and_prove(var, value)
        if reason:
            # Left hardcoded on purpose: never drop the only plaintext copy for a
            # store we could not prove. Re-run after fixing the keyring, or paste:
            print(f"  {var}: {reason} — left in place; run in your desktop session:")
            print(f"      {manual_store_cmd(var, value)}")
            failures += 1
            continue
        replacements[idx] = load_line(var)
        print(f"  {var}: stored len={len(value)} …{value[-4:]} → rewrote to load line")

    if replacements:
        rewrite(TOKENS_FILE, replacements)
        print(f"Migrated {len(replacements)} secret(s) into the keyring.")
    else:
        print("Nothing to migrate.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
