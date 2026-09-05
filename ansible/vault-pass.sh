#!/usr/bin/env bash
# Ansible vault password client: emits the vault password from the
# MY_ANSIBLE_VAULT environment variable. ansible-playbook runs this (rather than
# reading it as a plain file) because it is executable. Referenced by the
# justfile's --vault-password-file so `just diff`/`apply` decrypt vaulted vars
# without a password file on disk.
set -euo pipefail

if [ -z "${MY_ANSIBLE_VAULT:-}" ]; then
  echo "vault-pass.sh: MY_ANSIBLE_VAULT is not set in the environment" >&2
  exit 1
fi

printf '%s' "$MY_ANSIBLE_VAULT"
