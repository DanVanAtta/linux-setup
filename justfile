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

# Install required Ansible collections.
galaxy: setup
    ansible-galaxy collection install -r ansible/requirements.yml

# Lint all roles + playbook (no sudo; still red from pre-existing legacy debt).
verify:
    ansible-lint ansible/

# No-sudo work check: syntax-check the playbook, then lint the claude_user role.
check:
    ansible-playbook --inventory "localhost," --connection local \
      --syntax-check ansible/system-setup.yml
    ansible-lint ansible/roles/claude_user

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
