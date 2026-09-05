export PATH := $(HOME)/.local/bin:$(PATH)

install-ansible:
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


galaxy: install-ansible
	ansible-galaxy collection install -r ansible/requirements.yml

diff: galaxy
	ANSIBLE_CONFIG=./ansible/ansible.cfg ansible-playbook \
	  --inventory "localhost," \
	  --connection local \
	  --ask-become-pass \
	  --vault-password-file ansible/vault-pass.sh \
	  --check \
	  --diff \
	  ansible/system-setup.yml

apply: galaxy
	ANSIBLE_CONFIG=./ansible/ansible.cfg ansible-playbook \
	  --inventory "localhost," \
	  --connection local \
	  --ask-become-pass \
	  --vault-password-file ansible/vault-pass.sh \
	  --diff \
	  ansible/system-setup.yml

