# claude_user

Runs the Claude Code bot as a dedicated, low-privilege Unix user (`claude`)
instead of as the primary human user, so a bot launched with
`--dangerously-skip-permissions` (YOLO mode) is contained by the kernel rather
than by an in-process sandbox it can disable itself.

## Model

- **Separate user, own home.** The bot runs as `claude` with its own
  `/home/claude` and its own `~/.claude` config. Nothing of the bot's is in the
  primary user's home.
- **Opt-in access via POSIX ACLs.** The bot gets a traverse-only (`--x`) ACL on
  the primary home — enough to `cd` through it — and recursive `rwX` on
  `~/work` only. Everything else (`~/.ssh`, `~/.aws`, `~/.gnupg`, the GNOME
  keyring, ...) is unreachable by default. Default ACLs on `~/work` keep new
  files editable in both directions without a shared group or setgid.
- **Launch path.** A sudoers drop-in lets the primary user run the bot binary
  as `claude` with `NOPASSWD`. `sudo`'s `env_reset` drops the primary user's
  exported secrets (eg: PAT tokens); only `TERM`/`COLORTERM` are kept. The
  `claude`/`bot` aliases live in a sourced fragment
  (`~/.config/claude-bot.sh`), so the drifted hand-edited `.bashrc` need not be
  reconciled — sourced last, the fragment wins over any stale inline alias.
- **Config migration (one-time).** On first provision the durable subset of the
  primary user's `~/.claude` (`settings.json`, `skills/`, `hooks/`, `plugins/`,
  `statusline-command.sh`, `claude-skills.txt`, `projects/` — which carries the
  bot's memory) is copied into `/home/claude/.claude`; machine/session state and
  credentials are left behind. Config paths in `settings.json` are repointed
  from the old home, preserving `~/work` references. Re-running the role does
  **not** re-seed, so the bot's config evolves independently.
- **`~/work` symlink.** `/home/claude/work` links to the shared checkout so the
  bot's `$HOME/work` (used by hooks like worktree-create) resolves correctly.
- **GitHub identity of its own.** The bot has a separate GitHub account
  (`DanVanAtta[Bot]`), never the human's. Its API token is stored
  ansible-vault-encrypted in `vars/main.yml` and deployed to the bot's home two
  ways: `~/.pat_tokens` exports `GH_TOKEN`/`GITHUB_TOKEN` for `gh`, and
  `~/.git-credentials` (with `credential.helper=store`) backs https `git`. Both
  files are `0600` and owned by the bot. Rotate the token by re-encrypting it —
  see the header of `vars/main.yml`.

## Deliberate tradeoffs

- **First `bot` run prompts a fresh Claude login** — credentials are not copied,
  which is the point of a separate identity.
- **GitHub actions run as the bot, not the human** — its token is a different
  account. The human's keyring and PATs stay unreachable.
- **Any tool that reads `~/.ssh` breaks under the bot** — including a sanctioned
  read-only SSH log-fetch wrapper. Run those as the primary user, or grant the
  bot its own dedicated key outside `~/.ssh`.
- The initial recursive ACL pass over `~/work` is a one-time, somewhat slow
  walk; subsequent runs skip it (gated on the default ACL already being set).

## Usage

`bot` (defined by the fragment) `cd`s to `~/work` and launches the bot as the
`claude` user. Run it once interactively to complete the Claude login.
