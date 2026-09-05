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

## Deliberate tradeoffs

- **First `bot` run prompts a fresh Claude login** — credentials are not copied,
  which is the point of a separate identity.
- **`gh` / token-authenticated `git` stop working under the bot** by design: it
  has no access to the primary user's keyring or PATs. Give the bot its own
  GitHub account/token separately if it needs one.
- **Any tool that reads `~/.ssh` breaks under the bot** — including a sanctioned
  read-only SSH log-fetch wrapper. Run those as the primary user, or grant the
  bot its own dedicated key outside `~/.ssh`.
- The initial recursive ACL pass over `~/work` is a one-time, somewhat slow
  walk; subsequent runs skip it (gated on the default ACL already being set).

## Usage

`bot` (defined by the fragment) `cd`s to `~/work` and launches the bot as the
`claude` user. Run it once interactively to complete the Claude login.
