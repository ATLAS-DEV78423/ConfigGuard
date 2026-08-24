# Changelog

All notable changes to rice are documented here. Format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versioning is SemVer.

## [1.0.0] - 2026-08-24

First stable release. V1 scope per `RICE_BUILD_SPEC.md`: snapshot -> APT
upgrade -> reconcile -> validate, with journal-based recovery.

### Fixed
- **Restore over broken symlinks** crashed with `FileExistsError`
  mid-restore; the existence gate now uses lstat semantics and removes any
  conflicting entry before writing.
- **Type-flip hazards at restore**: a live directory where a tracked entry
  belongs is refused with an explicit error for BOTH file and symlink
  entries — never rmtree'd, never copied into.
- **Restore through a live symlink** no longer writes to the link's target;
  the link is replaced by the tracked file.
- **Log redaction was wired to the wrong object**: the filter lived on the
  logger, so records propagated from child loggers (`rice.snapshot`,
  `rice.update`, ...) bypassed it. Filters now sit on every output handler;
  covered by a child-logger regression test.
- **Waybar validation false failures**: strict-JSON parse errors from the
  deliberately-partial JSONC stripper degraded to hard failures and spurious
  rollback offers; they now report ok=None ("manual check needed").
- **Config storage format** now matches spec §12: paths under home are stored
  as `~/...`; init honors an injected home instead of the real `$HOME`.

### Removed
- Dead APIs: `PackageManager.changed_packages()` (+ `_last` state),
  `Reconciler.resolve(on_decision=)`, per-snapshot `metadata.json`, custom
  `rice completion` command (Typer's built-in `--install-completion` /
  `--show-completion` cover FR-034), `CommandRunner.capture()` alias,
  duplicated integrator detect/config_dirs bodies.

### Changed
- Shell completion documented via Typer built-ins (REQUIREMENTS FR-034).
- Version reporting via `rice --version` (flag, not subcommand).

### Verification
- Three independent review rounds (18 findings closed), static sweeps
  (no shell=True, subprocess only in runner, raw open only in fs),
  CI green on Ubuntu 24.04/latest + Debian 13 (trixie):
  lint/format/mypy, unit+cli+security, integration+recovery.

## [0.1.0] - 2026-08-21

Initial development release: core state machine, snapshot store with
SHA-256 verification, APT adapter (non-interactive, lock-respecting),
reconciler with keep-mine default, transaction journal + recovery,
Typer CLI with JSON output.
