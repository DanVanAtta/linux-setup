#!/usr/bin/env python3
"""Migrate hardcoded secrets out of a plaintext staging file into the GNOME keyring.

This is the sole populate path for the PATs that 'system-setup.yml' consumes; the
playbook only ever reads the keyring. The workflow: drop 'KEY=value' lines into
'~/.secret-tokens.env', run 'just migrate-secrets', and each value that validates and
stores cleanly has its line removed from the file — so a live secret sits in plaintext
only for the seconds between paste and run, and the file drains to empty.

Every token is bounded (min/max length + no internal whitespace) before it is stored:
an Ubuntu/Wayland clipboard truncates or picks up the wrong buffer silently, and a
mangled value in the keyring surfaces only as a confusing auth failure days later. The
bounds and key list live in 'pat_tokens.json', shared with the playbook so the set of
secrets is defined in one place.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

# The staging file is plaintext on disk by design; keep it out of any repo and locked to
# the owner. Path is fixed rather than configurable so there is exactly one place a live
# secret can transit.
STAGING_FILE = Path.home() / ".secret-tokens.env"
KEYRING_SERVICE = "pat_tokens"
META_FILE = Path(__file__).parent / "pat_tokens.json"


class TokenSpec:
    """One expected secret: its keyring key, human label, and accepted length bounds."""

    def __init__(self, entry: dict) -> None:
        self.key = entry["key"]
        self.label = entry["label"]
        self.min_len = entry["min_len"]
        self.max_len = entry["max_len"]


def load_specs() -> dict[str, TokenSpec]:
    specs = [TokenSpec(e) for e in json.loads(META_FILE.read_text())]
    return {s.key: s for s in specs}


def parse_staging(path: Path) -> list[tuple[int, str, str]]:
    """Return (line_index, key, value) for each 'KEY=value' assignment.

    Surrounding whitespace on the value is stripped so a stray trailing space from an
    editor is forgiven; internal whitespace is left intact for validation to reject,
    since that is the fingerprint of a truncated multi-line paste. Blank lines, comments,
    and empty assignments ('KEY=') are skipped, not migrated.
    """
    assignments = []
    for idx, raw in enumerate(path.read_text().splitlines()):
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip()
        if key and value:
            assignments.append((idx, key, value))
    return assignments


def has_internal_whitespace(value: str) -> bool:
    return any(c.isspace() for c in value)


def validate(value: str, spec: TokenSpec) -> str | None:
    """Return a redacted reason the value is unacceptable, or None if it passes.

    The reason names length only, never the value, so it is safe to print.
    """
    if not (spec.min_len <= len(value) <= spec.max_len):
        return f"length {len(value)} not in [{spec.min_len}, {spec.max_len}] — likely a truncated or run-on paste"
    if has_internal_whitespace(value):
        return "contains whitespace — likely a truncated multi-line paste"
    return None


def store_and_verify(key: str, value: str, spec: TokenSpec) -> str | None:
    """Store the value in the keyring and read it back; return a redacted error or None.

    The read-back guards against a store that reported success but round-tripped a
    different value; only on an exact match is the caller safe to drop the line.
    """
    store = subprocess.run(
        ["secret-tool", "store", f"--label={spec.label}",
         "service", KEYRING_SERVICE, "key", key],
        input=value.encode(),
        capture_output=True,
    )
    if store.returncode != 0:
        return f"secret-tool store failed: {store.stderr.decode().strip()}"

    readback = subprocess.run(
        ["secret-tool", "lookup", "service", KEYRING_SERVICE, "key", key],
        capture_output=True,
    )
    if readback.returncode != 0 or readback.stdout.decode() != value:
        return "read-back did not match what was stored"
    return None


def rewrite_without(path: Path, drop_indices: set[int]) -> None:
    """Rewrite the staging file minus the migrated lines, atomically, preserving 0600.

    Comments and un-migrated (skipped or failed) lines are kept verbatim so the file
    stays a faithful to-do list of what still needs migrating.
    """
    kept = [line for idx, line in enumerate(path.read_text().splitlines())
            if idx not in drop_indices]
    fd, tmp = tempfile.mkstemp(dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write("\n".join(kept) + ("\n" if kept else ""))
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def main() -> int:
    if subprocess.run(["which", "secret-tool"], capture_output=True).returncode != 0:
        print("secret-tool not found — run 'just apply' (installs libsecret-tools) first.", file=sys.stderr)
        return 1
    if not STAGING_FILE.exists():
        print(f"No staging file at {STAGING_FILE}.\n"
              f"Create it with 0600 perms and one 'KEY=value' line per secret, then re-run.", file=sys.stderr)
        return 1

    # A world/group-readable staging file defeats the point; refuse rather than migrate
    # from a file other users can read.
    mode = STAGING_FILE.stat().st_mode & 0o777
    if mode != 0o600:
        print(f"{STAGING_FILE} is mode {oct(mode)}; run 'chmod 600 {STAGING_FILE}' and re-run.", file=sys.stderr)
        return 1

    specs = load_specs()
    migrated: set[int] = set()
    failures = 0

    for idx, key, value in parse_staging(STAGING_FILE):
        spec = specs.get(key)
        if spec is None:
            print(f"  {key}: unknown key (not in pat_tokens.json) — skipped")
            failures += 1
            continue
        reason = validate(value, spec) or store_and_verify(key, value, spec)
        if reason:
            print(f"  {key}: {reason} — nothing stored")
            failures += 1
            continue
        migrated.add(idx)
        print(f"  {key}: stored len={len(value)} …{value[-4:]}")

    if migrated:
        rewrite_without(STAGING_FILE, migrated)
        print(f"Migrated {len(migrated)} secret(s); their lines were removed from {STAGING_FILE.name}.")
    else:
        print("Nothing migrated.")

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
