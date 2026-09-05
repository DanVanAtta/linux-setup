# Linux Setup

This is my personal crib-sheet for setting up a new system.

Contained is a mostly-automated full setup for a developer desktop
running Ubuntu.  Provided is an idempotent 'run-setup' script that
will do the  majority of the setup.  Also in this  README are a few
additional notes for things to install and/or configure.


## Run setup:

Prerequisite: install the [`just`](https://github.com/casey/just) command
runner — it's the project's task interface (recipes live in the `justfile`).

```
ssh-keygen -t ed25519
 # Add SSH key to github.com
sudo apt install -y git
mkdir ~/work/
cd ~/work/
git clone git@github.com:DanVanAtta/linux_setup.git
cd linux_setup/
just setup     # install ansible tooling (uv/pipx, ansible-core, ansible-lint)
sudo -v        # pre-cache sudo; recipes avoid ansible's --ask-become-pass
just apply     # provision this machine
```

`just apply` (and the `just diff` check-mode dry run) provision the machine and
need root: run `sudo -v` first so `become` needs no prompt — the recipes
deliberately avoid ansible's `--ask-become-pass`, which hangs on this
ansible-core version. Both also read the ansible-vault password from the
`MY_ANSIBLE_VAULT` environment variable (exported via `~/.bashrc`) so vaulted
vars decrypt.

To check the config without touching the system (no sudo, no vault):
`just verify` runs ansible-lint, and `just check` is a full no-sudo dry run
(syntax-check + lint).


## Install List

The following are installed/configured:
 
- Grub boot menu will always be displayed on boot (5s timeout)
- Security hardening configs
- Git: 
  - sets up git username & email
  - add git config file with defaults & settings
  - [SCM Breeze](https://github.com/scmbreeze/scm_breeze)
- Docker: install sudo-less docker (requires machine reboot)
- DNS: adds [DNS blacklist](https://raw.githubusercontent.com/StevenBlack/hosts/master/hosts) 
  which maps advertising and tracking hosts to '0.0.0.0'
- Apt: installs a lot of packages, eg: clamav, zip, shellcheck
- VIM: deploys vimrc file
- Apps:
   - Brave
   - Intellij (ultimate)
   - Steam


## Manual Install

- set up keyboard shortcuts
- [yed](https://www.yworks.com/products/yed/download)

### Git Tools

```
git clone git@github.com:DanVanAtta/git_tools.git ~/.git_tools

## add to path
grep -q 'git_tools' ~/.bashrc \
    || (TOOL_HOME=~/.git_tools \
          && echo -n 'PATH=$PATH:' >> ~/.bashrc \
          && echo "$TOOL_HOME" >> ~/.bashrc)
```

