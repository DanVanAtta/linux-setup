# linux-setup — provision this machine with Ansible.
# Run recipes with `just <name>`; `just` alone lists them. See README.md.

export ANSIBLE_CONFIG := "./ansible/ansible.cfg"
export PATH := env_var('HOME') + "/.local/bin:" + env_var('PATH')

# List available recipes.
default:
    @just --list

# Install the Ansible toolchain (pipx, uv, ansible-core + libs, lint, navigator).
setup:
    command -v pipx &>/dev/null || sudo apt-get install -y pipx
    pipx ensurepath
    command -v uv &>/dev/null || pipx install uv
    uv tool install --upgrade ansible-core \
      --with ansible \
      --with linode_api4 \
      --with passlib \
      --with netaddr \
      --with jmespath
    uv tool install --upgrade ansible-lint
    uv tool install --upgrade ansible-navigator
    just install-hooks

# Install required Ansible collections.
galaxy: setup
    ansible-galaxy collection install -r ansible/requirements.yml

# The gate — "this is good": no-sudo validation of the whole config. A
# pre-commit hook (see `install-hooks`) runs this, so a commit only lands when
# it passes. Syntax-checks the playbook, then lints every role + playbook
# (green under ansible-lint's `production` profile). Needs collections present;
# run `just galaxy` once. The check-mode dry run is separate (`just diff`).
verify:
    ansible-playbook --inventory "localhost," --connection local \
      --syntax-check ansible/system-setup.yml
    ansible-lint ansible/

# Point git at the tracked hooks dir so the pre-commit gate is active. Idempotent;
# also run by `setup`, so a fresh clone gets it after `just setup`.
install-hooks:
    git config core.hooksPath .githooks

# Check-mode dry run against this machine (needs sudo; run `sudo -v` first).
diff: galaxy
    sudo -v
    ansible-playbook --inventory "localhost," --connection local \
      --vault-password-file ansible/vault-pass.sh \
      --check --diff \
      ansible/system-setup.yml

# Provision this machine for real (needs sudo; run `sudo -v` first).
apply: galaxy
    sudo -v
    ansible-playbook --inventory "localhost," --connection local \
      --vault-password-file ansible/vault-pass.sh \
      --diff \
      ansible/system-setup.yml

# Move hardcoded secrets in ~/.pat_tokens into the GNOME keyring, rewriting each back to
# its `$(secret-tool lookup ...)` load line. Handles both adding and rotating a secret.
migrate-secrets:
    python3 ansible/migrate-secrets.py
