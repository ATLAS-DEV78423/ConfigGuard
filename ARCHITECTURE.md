# ARCHITECTURE.md

Layered design; the authoritative details live in `RICE_BUILD_SPEC.md`
(§7–§23). This file maps them to code.

## Layers

```
cli.py                 Typer entrypoint; maps RiceError -> exit codes (spec §6)
core/
  errors.py            RiceError hierarchy, one class per exit code
  fs.py                Filesystem abstraction: atomic writes, hashing,
                       metadata, scope checks. ONLY place raw fs ops happen.
  runner.py            CommandRunner abstraction. ONLY place subprocess happens.
  loggingx.py          Safe logging (redaction, no config contents).
  config.py            ~/.config/rice/config.toml load/save.
  state.py             Transaction state machine + persisted journal.
  detector.py          OS/desktop/config discovery.
  snapshot.py          Snapshot create/verify/restore/list/delete/prune.
  reconciler.py        Post-update diff classification + resolution.
  validator.py         Per-app config validation (never mutates).
  updater.py           run_protected_update(): orchestration, locking, signals.
pkgmanagers/
  base.py              PackageManager ABC + UpdateResult.
  apt.py               APT impl (apt update / apt upgrade -y via sudo).
integrators/
  common.py            DesktopIntegrator ABC + ValidationResult.
  hyprland/waybar/kitty/wofi
```

## Invariants

- **Two seams:** every external effect flows through `Filesystem` or
  `CommandRunner`; tests substitute fakes at exactly those points.
- **State machine** (spec §17): PREPARING -> SNAPSHOTTED -> UPDATING ->
  UPDATED -> RECONCILING -> VALIDATING -> COMMITTED; failures route to
  UPDATE_FAILED / CONFLICT / RECOVERY -> KNOWN_STATE. Every transition is
  persisted to `transactions/<txn>.json` before acting on it.
- **Update invariant:** PREPARE -> SNAPSHOT -> VERIFY SNAPSHOT -> UPDATE ->
  ANALYZE -> RECONCILE -> VALIDATE -> COMMIT. Nothing mutates user configs
  before a verified snapshot exists.
- **Ownership:** rice touches only paths listed in `config.toml` (canonicalized,
  scope-checked). Symlinks escaping scope are refused.
- **Reconciliation V1:** UNCHANGED skip · CHANGED keep-mine (prompt when
  interactive) · TYPE_CHANGED conflict prompt · abort rolls back to snapshot.
  No automatic semantic merges.

## Storage layout

See spec §11 (`~/.local/share/rice/{snapshots,transactions,logs,current}`).

## Testing strategy

Fake `CommandRunner` + tmp `$HOME` make every scenario deterministic:
success, APT failure, conflicts, validation failure, crash-at-any-state
(`tests/recovery/`). See TESTING.md.
