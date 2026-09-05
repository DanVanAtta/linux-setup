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
  the primary home — enough to `cd` through it — recursive `rwX` on `~/work`,
  and recursive read-only `rX` on `~/Screenshots` (so it can read pasted or
  referenced screenshots but never write there). Default ACLs on each keep new
  files inheriting that access — editable both directions under `~/work`,
  bot-readable under `~/Screenshots` — without a shared group or setgid.
- **Home lockdown (the trap in traverse).** Traverse alone is *not* enough
  isolation: a `--x` grant lets the bot read any **world-readable** file in the
  home by exact path (the home's `0750` mode gates listing, not per-file read).
  So the role also strips all "other" access from every top-level entry in the
  primary home except `~/work`. Without this, dotfiles that export tokens
  (`~/.bashrc`), key/credential files, and dumps sitting in the home are
  readable by the bot even though it can't `ls` the directory. Subdirs like
  `~/.ssh`/`~/.aws`/`~/.gnupg` were already `700`, but many home files default
  to `644`/`664` — those are the exposure this closes.
- **Launch path.** A sudoers drop-in lets the primary user run the bot as
  `claude` with `NOPASSWD`. `sudo`'s `env_reset` drops the primary user's
  exported secrets (eg: PAT tokens); only `TERM`/`COLORTERM` are kept. The
  `claude`/`bot` aliases live in a sourced fragment
  (`~/.config/claude-bot.sh`), so the drifted hand-edited `.bashrc` need not be
  reconciled — sourced last, the fragment wins over any stale inline alias.
- **Where the bot's own env loads (headless).** The permitted sudo command is a
  wrapper (`~/.local/bin/claude-bot`), not the binary directly. This matters
  because the bot is headless: every command it runs is a non-interactive
  `bash -c`, which reads no startup file — not `.bashrc` (its interactive guard
  returns first) and not `.profile` (login shells only). `BASH_ENV` is the usual
  headless hook, but `sudo` strips it. So the wrapper is the load point: running
  as `claude`, it sources `~/.pat_tokens` and fixes `PATH`, then execs the real
  launcher; every child the bot spawns inherits that env. It is a separate path
  from `.local/bin/claude` (the auto-updated launcher symlink) so a bot
  self-update can't overwrite it.
- **Own config.** The bot keeps its own `/home/claude/.claude`, independent of
  the human's. A fresh provision starts it empty — the first `bot` run does
  onboarding and a Claude login of its own.
- **`~/work` symlink.** `/home/claude/work` links to the shared checkout so the
  bot's `$HOME/work` (used by hooks like worktree-create) resolves correctly.
- **Clipboard access (paste).** Paste into the bot's terminal reads the X
  clipboard via `xsel`; under the isolated user that read fails (no Xwayland
  cookie in the human's `0700` runtime dir), Claude Code sees an empty clipboard,
  and nothing pastes — text included. To restore paste, a login autostart hook
  (`claude-bot-xauth-export`) copies the session's Xwayland cookie to
  `~/.claude-bot-xauth` (`0600` + a `u:claude:r` ACL), and the launch wrapper
  points `XAUTHORITY` there. The cookie path rotates per login, so the copy runs
  each graphical login rather than once. **This is a deliberate widening of the
  isolation model** — see the tradeoff below.
- **Container builds (rootless Podman).** The bot builds and runs containers
  with Podman *rootless* — inside its own user namespace — so a container escape
  or a `-v /:/host` mount only ever yields the `claude` user's privileges, the
  same boundary already in force. The bot is **never** in the `docker` group: the
  docker socket is root-equivalent (`docker run -v /:/host` = root on the host),
  and that would dissolve every ACL protection above. The role installs Podman,
  reserves the bot a subordinate uid/gid range (container `root` → an unprivileged
  host uid), enables systemd linger for a persistent `XDG_RUNTIME_DIR`, and drops
  a `docker`→`podman` shim in the bot's `~/.local/bin` so scripts calling `docker`
  just work. Rootless adds no new authority — the bot could already run arbitrary
  code as `claude`; this only lets it do so in containers within that same box.
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
- **Clipboard paste hands the bot X-clipboard read.** Enabling paste means the
  bot holds the session's Xwayland cookie, so it can read the clipboard at will —
  not only when you paste. On Wayland this is scoped to the clipboard and any
  legacy X11 clients (native Wayland windows are shielded by the compositor from
  X screengrab/keylog), but a copied password or token is readable while the
  grant stands. Remove the autostart entry and `~/.claude-bot-xauth` to revoke;
  paste then falls back to the read-only `~/Screenshots` path.
- The initial recursive ACL pass over `~/work` is a one-time, somewhat slow
  walk; subsequent runs skip it (gated on the default ACL already being set).
- **Rootless Podman can't do `--privileged`, docker-in-docker, or raw device
  access** — those need real root, and giving them to an isolated user has no safe
  form; a build that genuinely requires them is where this boundary stops. Bind
  mounts also see container-`root`-written files as an unprivileged mapped uid, so
  a container writing into `~/work` leaves files owned by a subuid, not `claude`.

## Usage

`bot` (defined by the fragment) `cd`s to `~/work` and launches the bot as the
`claude` user. Run it once interactively to complete the Claude login.
