#!/usr/bin/env python3
"""Move hardcoded secrets in ~/.pat_tokens into the GNOME keyring.

~/.pat_tokens is sourced by ~/.bashrc and, in steady state, holds only load
lines — 'export VAR=$(secret-tool lookup service pat_tokens key VAR ...)' — so
it carries no secret at rest. To add or rotate a secret, drop its value in
hardcoded ('export VAR=thevalue') and run 'just migrate-secrets': the value is
cleared from and re-stored in the keyring, then the line is rewritten back to
its load form. Add and rotate are the same gesture, and the file returns to
secret-free.

Ansible does not manage this file's contents — only that ~/.bashrc sources it.
This script is the sole populate path; keep it standalone (stdlib + secret-tool).
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

TOKENS_FILE = Path.home() / ".pat_tokens"
KEYRING_SERVICE = "pat_tokens"
MAX_LEN = 4096

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


def store_and_verify(var: str, value: str) -> str | None:
    """Clear any prior value, store the new one, read it back; redacted error or None."""
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
    return None


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
        reason = validate(value) or store_and_verify(var, value)
        if reason:
            print(f"  {var}: {reason} — nothing stored")
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
