#!/usr/bin/env python3
"""Print the commands to move hardcoded ~/.pat_tokens secrets into the keyring.

~/.pat_tokens is sourced by ~/.bashrc and, in steady state, holds only load
lines — 'export VAR=$(secret-tool lookup service pat_tokens key VAR ...)' — so
it carries no secret at rest. To add or rotate a secret, drop its value in
hardcoded ('export VAR=thevalue').

This script does NOT store anything itself. A 'secret-tool store' issued from
here (run under 'just', a subshell, or any non-login context) lands in the
wrong or transient keyring — it reports success and even reads back, yet the
secret never reaches the login collection and is gone at the next terminal.
The store must run in the user's own unlocked login session, so the script's
job is to print the exact commands for the human to paste there:

  1. 'just migrate-secrets'            → prints the 'secret-tool store' commands
                                          (and verify look-ups). Changes nothing.
  2. paste + run those in your terminal, confirm each look-up echoes its value.
  3. 'just migrate-secrets --rewrite'  → backs up ~/.pat_tokens, then swaps the
                                          now-stored lines to their load form.

Splitting store (step 2, human, keyring) from rewrite (step 3, file only) keeps
the two failure domains apart: the plaintext is never dropped on the strength of
a store this script cannot vouch for. Ansible does not manage this file's
contents — only that ~/.bashrc sources it. Keep this standalone (stdlib only).
"""

from __future__ import annotations

import os
import re
import shlex
import shutil
import sys
import tempfile
from pathlib import Path

TOKENS_FILE = Path.home() / ".pat_tokens"
BACKUP_FILE = TOKENS_FILE.parent / (TOKENS_FILE.name + ".bak")
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
    """Return a reason the value is unusable, or None if it passes."""
    if not value:
        return "empty value"
    if any(c.isspace() for c in value):
        return "contains whitespace — likely a truncated multi-line paste"
    if len(value) > MAX_LEN:
        return f"length {len(value)} exceeds {MAX_LEN} — likely a run-on paste"
    return None


def store_cmd(var: str, value: str) -> str:
    """The 'secret-tool store' to paste into an unlocked login session."""
    return (f"printf %s {shlex.quote(value)} | "
            f"secret-tool store --label={var} service {KEYRING_SERVICE} key {var}")


def lookup_cmd(var: str) -> str:
    return f"secret-tool lookup service {KEYRING_SERVICE} key {var}"


def load_line(var: str) -> str:
    return f"export {var}=$(secret-tool lookup service {KEYRING_SERVICE} key {var} 2>/dev/null)"


def hardcoded_secrets() -> list[tuple[int, str, str]]:
    """Every (line index, var, value) whose line is a hardcoded credential."""
    found = []
    for idx, raw in enumerate(TOKENS_FILE.read_text().splitlines()):
        m = EXPORT_RE.match(raw.strip())
        if not m:
            continue
        var, rhs = m.group(1), m.group(2).strip()
        if is_hardcoded_secret(var, rhs):
            found.append((idx, var, strip_quotes(rhs)))
    return found


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


def check_file() -> str | None:
    """Guard the shared preconditions; a message to print on failure, or None."""
    if not TOKENS_FILE.exists():
        return f"No {TOKENS_FILE}."
    mode = TOKENS_FILE.stat().st_mode & 0o777
    if mode != 0o600:
        return f"{TOKENS_FILE} is mode {oct(mode)}; run 'chmod 600 {TOKENS_FILE}' and re-run."
    return None


def print_commands() -> int:
    secrets = hardcoded_secrets()
    if not secrets:
        print("No hardcoded secrets in ~/.pat_tokens — nothing to migrate.")
        return 0

    usable, rejected = [], []
    for idx, var, value in secrets:
        (rejected if validate(value) else usable).append((idx, var, value))

    for idx, var, value in rejected:
        print(f"  SKIP {var}: {validate(value)}", file=sys.stderr)

    if not usable:
        return 1

    print("Run these in your own terminal (an unlocked login session — NOT via")
    print("'just', ssh, or a subshell), then re-run with --rewrite:\n")
    for _, var, value in usable:
        print(f"  {store_cmd(var, value)}")
    print("\nVerify each echoes its value:\n")
    for _, var, _ in usable:
        print(f"  {lookup_cmd(var)}")
    print("\nThen convert ~/.pat_tokens to keyring-load lines:\n")
    print("  just migrate-secrets --rewrite")
    return 1 if rejected else 0


def rewrite_file() -> int:
    secrets = [(idx, var, value) for idx, var, value in hardcoded_secrets()
               if not validate(value)]
    if not secrets:
        print("No hardcoded secrets to convert — ~/.pat_tokens is already load-only.")
        return 0

    # Back up before overwriting: the store step happens by hand in another
    # session, so this cannot confirm the secrets actually landed — the .bak is
    # the only recovery path if a value was never stored.
    shutil.copy2(TOKENS_FILE, BACKUP_FILE)
    os.chmod(BACKUP_FILE, 0o600)
    rewrite(TOKENS_FILE, {idx: load_line(var) for idx, var, _ in secrets})

    print(f"Converted {len(secrets)} line(s) to keyring-load form.")
    print(f"Plaintext backed up to {BACKUP_FILE} — delete it once a new terminal")
    print("confirms the values load (it holds the secrets at rest until you do).")
    return 0


def main(argv: list[str]) -> int:
    if argv and argv[0] not in ("--rewrite",):
        print(f"usage: {Path(sys.argv[0]).name} [--rewrite]", file=sys.stderr)
        return 2
    reason = check_file()
    if reason:
        print(reason, file=sys.stderr)
        return 1
    return rewrite_file() if argv == ["--rewrite"] else print_commands()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
