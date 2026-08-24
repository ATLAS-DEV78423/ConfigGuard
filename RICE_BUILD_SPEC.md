# RICE_BUILD_SPEC.md

**The single authoritative build specification for the Rice CLI.**

Rice is a safety-critical configuration-management CLI for Linux desktop
"ricers" (Hyprland/Wayland users). It protects the user's customized desktop
environment from becoming broken or inconsistent as a consequence of system
package updates. It does NOT stop package managers from overwriting dotfiles
(package managers primarily manage system/package-owned files); it protects the
user's *entire* customized environment from the consequences of updates.

This document is the source of truth. All other docs (ARCHITECTURE.md,
REQUIREMENTS.md, SECURITY.md, TESTING.md, CLAUDE.md, CONTRIBUTING.md) expand
on sections here. When they conflict, this document wins.

---

## 1. Product Definition

`rice` is a CLI that wraps a system package update, snapshots the user's desktop
configuration before the update, runs the update, then reconciles any config
changes so the user's customizations survive. It operates entirely in the
terminal (CLI-only, no GUI/TUI).

The product protects *configuration integrity, preservation, and recovery*. It
is explicitly NOT a full-OS rollback tool (not Timeshift).

## 2. Goals / Non-Goals

**Goals**
- Snapshot user desktop config before any update.
- Run the system update through a clean package-manager abstraction.
- Detect and reconcile config changes caused by the update.
- Recover automatically if the process is interrupted.
- Be scriptable (machine-readable output, deterministic exit codes).

**Non-Goals (V1 explicit exclusions)** — see section 34.

## 3. V1 Scope

| Dimension | V1 Value |
|-----------|----------|
| OS | Ubuntu 24.04+, Debian 13+ |
| Package manager | APT/dpkg |
| Desktop | Hyprland |
| Config targets | Hyprland, Waybar, Kitty, Wofi/Rofi, + user-selected additional paths |
| CLI | `rice init`, `status`, `snapshot`, `update`, `diff`, `restore`, `doctor`, `snapshots list/show/delete/prune`, `--version` |
| Languages | Python 3.11+ |
| Distribution | `pip install rice-cli`, `.deb` via setuptools |

Everything else is explicitly out of scope.

## 4. Supported Platforms

- Ubuntu 24.04 LTS, Ubuntu 26.04 LTS
- Debian 13 (trixie)+
- Arch, Fedora, Sway, i3: future (V2/V3)

## 5. CLI Specification

```
rice init                Discover candidate configs, ask which to protect, persist decision
rice status              Show detected system, protected configs, last snapshot/update
rice snapshot [--pin]    Manually snapshot protected configs
rice update              Full protected update (PREPARE→...→COMMITTED)
rice diff [SNAPSHOT]     Show diffs between a snapshot and current configs
rice restore [SNAPSHOT]  Restore configs from a snapshot
rice doctor [--fix]      Check health; optionally attempt auto-fix
rice snapshots list      List all snapshots
rice snapshots show S    Show one snapshot's manifest
rice snapshots delete S  Delete a snapshot
rice snapshots prune     Prune per retention policy
```

Global flags: `--version` (print version and exit), `-v/--verbose`,
`--no-color`, `--quiet`, `--json`, `--non-interactive`, `--dry-run`.

`restore`/`diff`/`snapshots show/delete` default to the most recent snapshot
when `SNAPSHOT` is omitted (except `delete`/`restore` require explicit id in
non-interactive mode).

## 6. Exit Codes

| Code | Meaning |
|------|---------|
| 0 | success |
| 1 | general error |
| 2 | invalid CLI usage |
| 3 | configuration error |
| 4 | snapshot failure |
| 5 | update failure |
| 6 | reconciliation conflict |
| 7 | validation failure |
| 8 | recovery failure |
| 9 | permission/sudo failure |

## 7. Architecture

Layered, with two testable abstractions (Filesystem, CommandRunner) so no module
performs raw `open()`/`subprocess.run()` directly.

```
cli.py                 # Typer-based entrypoint, maps to exit codes
core/
  state.py             # transaction state machine + journal persistence
  detector.py          # OS/desktop/config discovery
  snapshot.py          # snapshot creation/verification/restore
  updater.py           # PackageManager interface + APT impl
  reconciler.py        # diff + conflict handling
  validator.py         # per-app config validation
  config.py            # rice config.toml load/save (protected scope)
  fs.py                # Filesystem abstraction (atomic writes, hashing, metadata)
  runner.py            # CommandRunner abstraction (run/capture/privileged)
  loggingx.py          # safe logging (no secrets/config dumping)
pkgmanagers/
  base.py              # PackageManager ABC
  apt.py               # APT implementation
integrators/
  common.py            # DesktopIntegrator ABC
  hyprland.py          # Hyprland config handling
  waybar.py
  kitty.py
  wofi.py
```

## 8. Repository Tree

```
ConfigGuard/
├── RICE_BUILD_SPEC.md
├── ARCHITECTURE.md
├── REQUIREMENTS.md
├── SECURITY.md
├── TESTING.md
├── CONTRIBUTING.md
├── CLAUDE.md
├── README.md
├── pyproject.toml
├── rice/
│   ├── __init__.py
│   ├── cli.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── state.py
│   │   ├── detector.py
│   │   ├── snapshot.py
│   │   ├── updater.py
│   │   ├── reconciler.py
│   │   ├── validator.py
│   │   ├── config.py
│   │   ├── fs.py
│   │   ├── runner.py
│   │   └── loggingx.py
│   ├── pkgmanagers/
│   │   ├── __init__.py
│   │   ├── base.py
│   │   └── apt.py
│   └── integrators/
│       ├── __init__.py
│       ├── common.py
│       ├── hyprland.py
│       ├── waybar.py
│       ├── kitty.py
│       └── wofi.py
└── tests/
    ├── fixtures/
    │   ├── hyprland/{original,updated,conflicting}/
    │   ├── waybar/{...}
    │   └── kitty/{...}
    ├── unit/
    ├── integration/
    ├── recovery/
    ├── security/
    └── cli/
```

## 9. Module Interfaces

```python
# core/fs.py
class Filesystem:
    def read(self, path: Path) -> bytes
    def write_atomically(self, path: Path, data: bytes) -> None
    def copy(self, src: Path, dst: Path) -> None
    def move(self, src: Path, dst: Path) -> None
    def remove(self, path: Path) -> None
    def exists(self, path: Path) -> bool
    def metadata(self, path: Path) -> FileMeta   # perms, owner, group, size, mtime, type, symlink target
    def sha256(self, path: Path) -> str
    def ensure_dir(self, path: Path) -> None
    def free_space(self, path: Path) -> int        # bytes available

# core/runner.py
class CommandRunner:
    def run(self, args: list[str], *, check=False) -> RunResult
    def capture(self, args: list[str]) -> RunResult
    def privileged(self, args: list[str]) -> RunResult   # wraps sudo

# core/state.py
class TransactionState(Enum):
    IDLE, PREPARING, SNAPSHOTTED, UPDATING, UPDATED,
    RECONCILING, CONFLICT, VALIDATING, COMMITTED,
    UPDATE_FAILED, RECOVERY, KNOWN_STATE
class TransactionJournal:
    def begin(self, txn_id) -> None
    def set_state(self, state) -> None
    def record(self, key, value) -> None
    def load(self) -> dict | None          # None if no in-flight txn
    def clear(self) -> None

# pkgmanagers/base.py
class PackageManager(ABC):
    def detect() -> bool
    def update(self, runner) -> UpdateResult   # runs sudo apt update && upgrade

# integrators/common.py
class DesktopIntegrator(ABC):
    name: str
    def detect(self) -> bool
    def config_dirs(self) -> list[Path]
    def validate(self, fs) -> ValidationResult
```

## 10. Data Models

- `FileMeta`: path, type (file/symlink/dir), mode, uid, gid, size, mtime,
  sha256, symlink_target (optional).
- `ManifestEntry`: relative_path, FileMeta, backup_rel_path.
- `SnapshotManifest`: timestamp, host, desktop, packages_upgraded, files[].
- `UpdateResult`: success, exit_code, upgraded[], stdout_tail, stderr_tail.
- `ValidationResult`: app, ok, message.
- `TransactionRecord`: txn_id, state, started_at, snapshot_id, packages, steps[].

## 11. Snapshot Format

```
~/.local/share/rice/
├── config.toml
├── snapshots/
│   └── 2026-08-21T12-04-33Z/
│       ├── manifest.json
│       └── files/
│           ├── .config/hypr/hyprland.conf
│           ├── .config/waybar/config
│           └── ...
├── transactions/
│   └── <txn_id>.json            # journal, deleted on COMMITTED
├── logs/
│   └── rice-YYYYMMDD.log
└── current -> snapshots/<latest>
```

`manifest.json` records for each file: relative path, type, permissions, owner,
group, size, mtime, SHA-256, and backup location. Symlinks record their target
and whether the target is within protected scope.

## 12. Configuration Format

`~/.config/rice/config.toml`:

```toml
[rice]
data_dir = "~/.local/share/rice"
version = "0.1.0"

[protected]
# Each entry maps an integrator/app to its discovered paths.
hyprland = ["~/.config/hypr"]
waybar   = ["~/.config/waybar"]
kitty    = ["~/.config/kitty"]
wofi     = ["~/.config/wofi"]
extra    = ["~/.config/user-paths"]
```

`rice init` discovers candidates and persists this file. `rice` reads it to know
what to protect. Missing config → exit code 3 (configuration error) with a
prompt to run `rice init`.

## 13. Discovery System

`rice init` / `rice status` run `Detector`:
1. Read `/etc/os-release` → distro ID (ubuntu/debian) and version.
2. Check `$XDG_SESSION_DESKTOP` / `$WAYLAND_DISPLAY`.
3. For each known integrator, call `detect()` which checks for config dirs in
   `$HOME/.config/`.
4. Present discovered candidates; user selects which to protect (default: all).
5. Persist decision to `config.toml`.

## 14. Ownership Model

Rice protects only files it was *told* to protect (from `config.toml`). It never
snapshots `~/.config` wholesale. Each protected path is recorded with full
metadata so restore preserves permissions, owner, group, symlink state, and file
type. A path outside `config.toml`'s scope is never touched by restore.

## 15. Package-Manager Interface

`PackageManager` ABC exposes `update()`. All
package-manager operations go through `CommandRunner.privileged()`. Rice
orchestrates APT; it does NOT try to outsmart it.

## 16. APT Implementation

- `apt update` then `apt upgrade -y` (never `apt-get` for the user command; the
  implementation uses the `apt` binary).
- `DEBIAN_FRONTEND=noninteractive` set; **no** `--force-conf*` policy flags are
  passed in V1 (Rice handles preservation itself via snapshots, not dpkg policy).
- Run via `sudo` through `CommandRunner.privileged`.
- If `sudo` fails → exit 9 (permission/sudo failure).
- If update returns non-zero → transaction state UPDATE_FAILED; do NOT reconcile;
  leave system in known state; offer recovery.
- V1 does not support `dist-upgrade`/`full-upgrade`.

## 17. Update Transaction State Machine

```
IDLE
 │
 ▼
PREPARING
 │
 ▼
SNAPSHOTTED
 │
 ▼
UPDATING ──failure──► UPDATE_FAILED
 │
 ▼
UPDATED
 │
 ▼
RECONCILING ──conflict──► CONFLICT
 │
 ▼
VALIDATING ──failure──► RECOVERY ──► KNOWN_STATE
 │
 ▼
COMMITTED
```

Every state transition is persisted to the journal (`transactions/<id>.json`).
On restart, `rice status`/`rice doctor` detect an in-flight transaction and
report its last state + available recovery.

Invariant: PREPARE → SNAPSHOT → VERIFY SNAPSHOT → UPDATE → ANALYZE → RECONCILE →
VALIDATE → COMMIT. Any failure → RECOVERY → KNOWN STATE.

## 18. Reconciliation Algorithm (V1)

For each tracked file, compare snapshot (base) vs current (post-update):

- **UNCHANGED**: current sha == snapshot sha → do nothing.
- **USER CONFIG CHANGED** (current != snapshot, and the change is consistent with
  a user edit — i.e. we re-snapshotted before update so "current after update"
  should equal snapshot; if it differs, the update touched it): preserve the
  user's snapshot version by restoring it over the current file.
- **CONFLICT**: update changed the file AND we cannot safely auto-decide → show
  diff, user decides (keep mine / use new / diff / abort).

V1 deliberately omits intelligent 3-way merging (that is V2/V3). The default
safe action is to preserve the user's version.

## 19. Conflict Handling

When a conflict is detected and `--non-interactive` is NOT set, present:

```
[!] Conflict in ~/.config/hypr/hyprland.conf
Your line:  monitor=DP-1,1920x1080@144
New line:   monitor=DP-1,1920x1080@165
[1] keep my version  [2] use new  [3] diff  [4] abort
```

Options: keep mine (restore snapshot), use new (leave current), diff (show
unified diff), abort (roll back to pre-update snapshot, exit 6). In
`--non-interactive` mode, default to "keep mine" and record the decision in logs.

Rice MUST NOT automatically resolve a semantic configuration conflict.

## 20. Validation System

After reapplying, per-app validation:
- **Hyprland**: run `hyprctl reload` (if compositor reachable) or report "manual
  check needed".
- **Waybar**: parse config (jsonc) for syntax; attempt `--help` exit 0.
- **Kitty**: `kitty --config <path> --dry-run-config` if supported, else syntax
  check.
- **Wofi**: attempt `--show dmenu --config <path>` dry check.

Validation failure → warn user, offer rollback to snapshot (exit 7 if unresolvable
and user declines). Validation must never itself mutate configs.

## 21. Recovery System

If anything fails after SNAPSHOT:
- UPDATE_FAILED: leave system as-is (APT already ran; we do not downgrade).
  Configs untouched by update remain; offer `rice restore`.
- Validation failure: offer restore from the pre-update snapshot.
- RECOVERY state: restore all tracked files from snapshot using recorded
  metadata. Idempotent. On success → KNOWN_STATE.

`rice restore [SNAPSHOT]` is the manual recovery path: restores all recorded
files with metadata, never deletes originals first (copy-over only after
verified snapshot).

## 22. Filesystem Safety Rules

- All mutations go through `Filesystem`.
- Writes are atomic: temp file → fsync → rename.
- `remove()` only on paths within approved scope (snapshots dir, transaction
  journal). Never delete user configs.
- All paths are canonicalized and validated against protected scope before any
  operation.
- Symlinks: record target; refuse to follow symlinks that escape protected scope.
- No `shell=True`, no shell-string command construction anywhere.

## 23. Permission / Sudo Model

- Everything runs as the regular user except the APT invocation.
- `sudo` is invoked once via `CommandRunner.privileged` for the update only.
- No sudo during unit tests.
- Never store or log sudo passwords.

## 24. Security Threat Model

See SECURITY.md. Summary threats: malicious config file (never execute config
contents), path traversal (canonicalize+validate), symlink attack (validate
targets), privilege escalation (minimize privileged ops), corrupted snapshot
(hash+verify), interrupted transaction (journal), malicious package (delegate to
package manager), compromised update (don't bypass pm security).

## 25. Logging

- Logs under `~/.local/share/rice/logs/`.
- `loggingx` redacts secrets; never dumps full config file contents by default.
- Snapshot contents ≠ logs.
- Levels: default INFO, `--verbose` DEBUG, `--quiet` WARNING only.

## 26. Testing Architecture

See TESTING.md. Structure: `tests/{fixtures,unit,integration,recovery,security,cli}`.
Every module requires tests; failures and crash-recovery scenarios are mandatory.

## 27. Test Fixtures

`tests/fixtures/<app>/{original,updated,conflicting}/` provide deterministic
config samples for Hyprland, Waybar, Kitty, Wofi.

## 28. CI

GitHub Actions: lint (ruff), format check, type check (mypy), unit, integration,
security, build. Run on Ubuntu 24.04, Ubuntu 26.04, Debian 13.

## 29. Packaging

- `pyproject.toml` (setuptools/PEP 621), entry point `rice = rice.cli:app`.
- `pip install rice-cli`.
- Optional `.deb` build for Debian/Ubuntu.

## 30. Versioning

SemVer. 0.x = experimental. 1.0 = stable Ubuntu/Debian + Hyprland. 1.x = more
apps. 2.x = Arch. 3.x = advanced reconciliation.

## 31. Documentation

README.md + docs/ (installation, getting-started, concepts, configuration,
snapshots, recovery, troubleshooting, security, architecture, development).
Every CLI command documented.

## 32. Claude Code Rules

See CLAUDE.md. Hard rules: no destructive FS ops without verified snapshot +
tests; no `shell=True`; no shell-string commands; no writes outside approved
paths; no sudo in unit tests; all pm ops via PackageManager; all FS mutations via
Filesystem; every feature requires tests; no unapproved scope expansion.

## 33. Claude Code Task Workflow

Build milestone-by-milestone, not one giant prompt. Each milestone = small set
of modules + tests, verified before next.

## 34. Milestone 0 (foundation)

Repository skeleton, `fs.py`, `runner.py`, `loggingx.py`, `config.py`,
`state.py`, `CLAUDE.md`, spec docs, CI stub. Verified by unit tests of the two
abstractions + state machine.

## 35. Milestone 1 (detection + snapshot + restore)

`detector.py`, `snapshot.py`, integrators (hyprland/waybar/kitty/wofi), `init`,
`status`, `snapshot`, `restore`, `snapshots list/show/delete/prune`. Verified by
snapshot/restore round-trip tests + discovery tests.

## 36. Milestone 2 (update + reconcile + validate)

`updater.py` + `apt.py`, `reconciler.py`, `validator.py`, `update`, `diff`,
`doctor`. Verified by mocked-APT update tests + conflict-resolution tests +
crash-recovery tests.

## 37. Milestone 3 (polish)

Shell completion, `--json` across commands, retention pruning, full docs,
security test suite, CI green.

## 38. Definition of Done

A feature is done only when: implementation complete; unit tests pass;
integration tests pass; failure tests pass; crash-recovery tests pass; security
tests pass; CLI docs updated; architecture docs updated; no unsafe FS ops; no
unapproved scope expansion; formatting passes; lint passes; type-check passes; CI
passes.

## 39. Future Roadmap

V2: conflict handling UX polish, validation depth, telemetry opt-in (out of V1).
V3: Arch (pacman + `.pacnew`), Fedora (dnf + `.rpmnew`), Sway/i3.
V4: intelligent 3-way merge, richer TUI-free reporting, system packaging
(homebrew/AUR/snapcraft).

**Explicitly NOT in V1**: GUI, TUI, telemetry, AI config merging, cloud sync,
Git integration, Timeshift integration, auto dotfile install, package
installation beyond requested update, system rollback, editing `/etc`, Arch,
Fedora, Sway, i3.
