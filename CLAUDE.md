# linux-setup

Ansible-based provisioning for a developer desktop. Recipes live in the
`justfile` (`just` alone lists them); see `README.md` for first-time setup.

## Validating a change — `just verify`

`just verify` is the canonical "this is good" check. It runs with **no sudo,
no vault, no network**:

1. `ansible-playbook --syntax-check` of `system-setup.yml`
2. `ansible-lint ansible/` — must be **fully green** (ansible-lint's
   `production` profile, 0 findings)

Run it before committing. It is enforced as a **git pre-commit hook**
(`.githooks/pre-commit`, activated via `core.hooksPath`): a commit only
succeeds when `verify` passes. Wire the hook with `just install-hooks` (also
run by `just setup`, so a fresh clone gets it). Bypass a single commit with
`git commit --no-verify`.

`verify` assumes the Galaxy collections are installed — run `just galaxy` once
(part of `just setup`); otherwise lint fails resolving modules like `snap`.

The check-mode dry run is **not** part of the gate — it needs sudo, the vault
password, and network. Run it separately when you want it: `just diff` (and
`just apply` to provision for real). Both need `sudo -v` first.

## Keeping lint green

Prefer a real fix over silencing. Use a targeted `# noqa: <rule>  # <why>`
only when a rule genuinely conflicts with intent, never a blanket profile
downgrade or global `skip_list`. Current, deliberate exceptions:

- `role-name[path]` — the `git/*` sub-roles are intentionally grouped under
  `roles/git/`; noqa'd at the play level in `system-setup.yml`.
- `latest[git]` — the `git-tools` and `scm_breeze` clones deliberately track
  their default branch (pinned after first clone by `update: false`).
- `command-instead-of-module` — the `git config` reads need the *merged*
  effective config (the `git_config` module reads a single scope); the
  legacy `systemctl --user` cleanup must tolerate an already-absent unit,
  which the `systemd` module does not.
