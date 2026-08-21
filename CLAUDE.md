# Rice Development Rules

Rice is a safety-critical configuration-management CLI for Linux desktops.
These rules are hard constraints, not suggestions.

## Never

- Perform destructive filesystem operations without: explicit code-path
  authorization, a verified snapshot, and tests covering the operation.
- Use `shell=True` or construct shell commands via string interpolation.
  All commands are argv lists through `core.runner.CommandRunner`.
- Modify files outside approved paths (`~/.config/rice/`,
  `~/.local/share/rice/`, protected paths from `config.toml`).
- Run sudo during unit tests; use `FakeCommandRunner`.
- Execute configuration file contents as code.
- Log configuration file contents or secrets (hashes/metadata only).
- Store, log, or transmit sudo passwords.
- Automatically resolve semantic configuration conflicts.
- Change public CLI behavior without updating CLI contract docs.
- Expand V1 scope without explicit approval.

## Always

- All package-manager operations go through the `PackageManager` interface.
- All filesystem mutations go through the `Filesystem` abstraction
  (`core/fs.py`) with atomic writes (temp -> fsync -> rename).
- Every new feature requires tests.
- Every state transition persists to the transaction journal before acting.
- Verify snapshot integrity (SHA-256) before any restore.
- Canonicalize and scope-validate every path before touching it.
- Prefer boring, deterministic implementations over clever automation.

## Verification environment

Rice targets Linux only. Do not execute rice code on other platforms;
verification happens via CI (Ubuntu/Debian) and manual testing on Linux.
