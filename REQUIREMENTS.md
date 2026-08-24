# REQUIREMENTS.md

Formal requirements for Rice CLI. Each requirement has a unique ID and is
classified as functional (FR), non-functional (NFR), security (SR), performance
(PR), compatibility (CR), or UX (UR).

---

## Functional Requirements

**FR-001**  
Rice MUST create a verified snapshot before modifying any protected file during
an update.

**FR-002**  
Rice MUST NOT modify protected files if snapshot verification fails.

**FR-003**  
Rice MUST persist transaction state (ID, state, timestamp, snapshot reference)
after every state transition.

**FR-004**  
Rice MUST recover from an interrupted transaction on restart by detecting the
last persisted state and offering appropriate recovery actions.

**FR-005**  
Rice MUST operate without a GUI or TUI (CLI-only).

**FR-006**  
Rice MUST support `rice init` to discover candidate configs and persist the
user's selection to `~/.config/rice/config.toml`.

**FR-007**  
Rice MUST support `rice status` showing detected OS, package manager, desktop,
protected configs, last snapshot, last update status.

**FR-008**  
Rice MUST support `rice snapshot [--pin]` to manually create a snapshot of
all protected configs.

**FR-009**  
Rice MUST support `rice update` performing the full PREPARE→...→COMMITTED flow.

**FR-010**  
Rice MUST support `rice diff [SNAPSHOT]` showing unified diffs between snapshot
and current configs for all tracked files.

**FR-011**  
Rice MUST support `rice restore [SNAPSHOT]` restoring all tracked files with
full metadata (perms, owner, group, mtime, symlink state).

**FR-012**  
Rice MUST support `rice doctor [--fix]` validating all protected configs and
optionally attempting auto-fix (restore from last good snapshot).

**FR-013**  
Rice MUST support `rice snapshots list` listing all snapshots with timestamps,
file counts, and pin status.

**FR-014**  
Rice MUST support `rice snapshots show SNAPSHOT` displaying the manifest for
one snapshot.

**FR-015**  
Rice MUST support `rice snapshots delete SNAPSHOT` removing a snapshot after
confirmation (or `--force`).

**FR-016**  
Rice MUST support `rice snapshots prune` enforcing the retention policy
(last 10, last 30 days, pinned).

**FR-017**  
Rice MUST support `rice version` printing semantic version and exiting.

**FR-018**  
Rice MUST abort the update transaction if the APT command returns non-zero
and leave the system in a known state without attempting reconciliation.

**FR-019**  
Rice MUST detect unchanged files (sha256 match) and skip them during
reconciliation.

**FR-020**  
Rice MUST detect files changed by the package update and preserve the user's
snapshot version by default (restore user config).

**FR-021**  
Rice MUST detect conflict (update changed a file AND automatic resolution is
unsafe) and present an interactive prompt (keep/use/diff/abort).

**FR-022**  
Rice MUST NOT automatically resolve semantic configuration conflicts in V1.

**FR-023**  
Rice MUST validate configs after reapplying: Hyprland (`hyprctl reload`),
Waybar (JSONC parse), Kitty (dry-run if available), Wofi (dry check).

**FR-024**  
Rice MUST offer rollback to the pre-update snapshot on validation failure.

**FR-025**  
Rice MUST implement atomic filesystem writes (temp + fsync + rename).

**FR-026**  
Rice MUST preserve file permissions, owner, group, mtime, and symlink state
on restore.

**FR-027**  
Rice MUST canonicalize all paths and validate they are within protected scope
before any filesystem operation.

**FR-028**  
Rice MUST refuse to follow symlinks whose targets escape the protected scope.

**FR-029**  
Rice MUST check available disk space before snapshot; abort with clear message
if insufficient (required vs available).

**FR-030**  
Rice MUST implement a global lock (`~/.local/share/rice/transaction.lock`)
preventing concurrent `rice update` or `rice restore` transactions.

**FR-031**  
Rice MUST handle SIGINT/SIGTERM/SIGHUP gracefully: persist state, leave no
half-modified user configs.

**FR-032**  
Rice MUST detect APT/dpkg locks and report "another package manager is running"
without attempting to bypass.

**FR-033**  
Rice MUST provide machine-readable `--json` output for `status`, `diff`,
`snapshots list`, `snapshots show`, `doctor`.

**FR-034**  
Rice MUST provide shell completion scripts for bash, zsh, fish via the CLI
framework's built-in mechanism (`rice --install-completion` /
`rice --show-completion <shell>`).

---

## Non-Functional Requirements

**NFR-001**  
Rice MUST be written in Python 3.11+ with type annotations (mypy strict).

**NFR-002**  
Rice MUST use Typer for the CLI framework.

**NFR-003**  
Rice MUST have zero direct `open()`/`subprocess.run()` calls in core modules;
all via `Filesystem` and `CommandRunner` abstractions.

**NFR-004**  
Rice MUST NOT use `shell=True` anywhere.

**NFR-005**  
Rice MUST NOT construct shell commands via string interpolation.

**NFR-006**  
Rice MUST NOT run `sudo` during unit tests (use `FakeCommandRunner`).

**NFR-007**  
All package-manager operations MUST go through the `PackageManager` interface.

**NFR-008**  
All filesystem mutations MUST go through the `Filesystem` abstraction.

**NFR-009**  
Rice MUST be distributable via `pip install rice-cli` and optionally as `.deb`.

---

## Security Requirements

**SR-001**  
Rice MUST never execute configuration file contents as code.

**SR-002**  
Rice MUST never log full configuration file contents (hashes/metadata only).

**SR-003**  
Rice MUST never write to paths outside `~/.config/rice/`,
`~/.local/share/rice/`, and user-selected protected paths.

**SR-004**  
Rice MUST validate all symlink targets; refuse to follow targets outside
protected scope.

**SR-005**  
Rice MUST verify snapshot integrity via SHA-256 before any restore operation.

**SR-006**  
Rice MUST delegate all package-manager security (signatures, repo trust) to
the underlying package manager; never bypass.

**SR-007**  
Rice MUST not store, log, or transmit sudo passwords or credentials.

---

## Performance Requirements

**PR-001**  
`rice status` MUST complete in < 500ms typical on SSD.

**PR-002**  
`rice snapshot` MUST scale approximately linearly with protected data size.

**PR-003**  
`rice diff` MUST handle thousands of files without excessive memory usage
(streaming diff, not loading all into RAM).

**PR-004**  
Snapshot creation for typical rice configs (~50MB) MUST complete in < 10s.

---

## Compatibility Requirements

**CR-001**  
Rice MUST run on Ubuntu 24.04 LTS and Ubuntu 26.04 LTS.

**CR-002**  
Rice MUST run on Debian 13 (trixie)+.

**CR-003**  
Rice MUST detect and protect Hyprland configs.

**CR-004**  
Rice MUST detect and protect Waybar configs.

**CR-005**  
Rice MUST detect and protect Kitty configs.

**CR-006**  
Rice MUST detect and protect Wofi/Rofi configs.

**CR-007**  
Rice MUST allow user-selected additional paths beyond detected apps.

---

## UX Requirements

**UR-001**  
Rice MUST work in plain terminals (no color requirement).

**UR-002**  
Rice MUST support `--no-color` to disable colored output.

**UR-003**  
Rice MUST support `--quiet` (warnings/errors only).

**UR-004**  
Rice MUST support `--verbose` (debug output).

**UR-005**  
Rice MUST support `--non-interactive` (no prompts; default safe actions).

**UR-006**  
Rice MUST support `--dry-run` (simulate without mutating).

**UR-007**  
Rice MUST provide meaningful exit codes per section 6 of BUILD_SPEC.

**UR-008**  
Rice MUST produce clear, actionable error messages (what failed, why, how to
recover).

**UR-009**  
Rice MUST NOT prompt when `--non-interactive` is set.

---

## Traceability

| Requirement | Build Spec Section | Test Location |
|-------------|-------------------|---------------|
| FR-001..004 | 17, 21 | tests/recovery/ |
| FR-006..017 | 5 | tests/cli/ |
| FR-018 | 16, 17 | tests/integration/ |
| FR-019..022 | 18, 19 | tests/unit/ |
| FR-023..024 | 20 | tests/unit/, tests/integration/ |
| FR-025..028 | 22 | tests/unit/, tests/security/ |
| FR-029 | 12 | tests/unit/ |
| FR-030 | 13 | tests/unit/ |
| FR-031 | 14 | tests/recovery/ |
| FR-032 | 15 | tests/integration/ |
| FR-033 | 5 | tests/cli/ |
| FR-034 | 22 | tests/cli/ |
| NFR-001..009 | 7, 9, 32 | tests/unit/ |
| SR-001..007 | 24 | tests/security/ |
| PR-001..004 | 20 | tests/integration/ |
| CR-001..007 | 4, 13 | tests/integration/ |
| UR-001..009 | 5, 21, 31 | tests/cli/ |