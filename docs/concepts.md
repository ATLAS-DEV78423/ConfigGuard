# Concepts

## What rice protects

Only the paths listed in `~/.config/rice/config.toml` — nothing else, never
`~/.config` wholesale (the ownership model, spec §14). V1 detects Hyprland,
Waybar, Kitty, and Wofi/Rofi; you can add extra paths at `rice init`.

## The update transaction

Every `rice update` runs the same invariant:

```
PREPARE -> SNAPSHOT -> VERIFY SNAPSHOT -> UPDATE -> ANALYZE ->
RECONCILE -> VALIDATE -> COMMIT
```

Any failure routes to RECOVERY and ends in a KNOWN STATE. Every state
transition is persisted to a journal (`~/.local/share/rice/transactions/`)
*before* acting on it, so a power loss mid-update leaves a readable record
that `rice status` / `rice doctor --fix` use to recover.

## Snapshots

A snapshot is a directory under `~/.local/share/rice/snapshots/<id>/`
containing copied config files plus a `manifest.json` recording each file's
path, type, permissions, owner, group, size, mtime, SHA-256, and symlink
target. Restores verify those hashes first — a corrupted snapshot is refused.

## Reconciliation (V1)

- **unchanged** (hash equal): skip.
- **changed by update**: keep YOUR version (prompt first in interactive mode;
  silent keep-mine with `--non-interactive`).
- **missing**: restored automatically (it is your file).
- **type changed** (file became symlink etc.): treated as a conflict prompt.

Rice never auto-resolves semantic conflicts and never 3-way merges (V2/V3).

## Safety model

All filesystem writes go through one audited abstraction (temp file -> fsync
-> atomic rename). All external commands run as argv lists through one runner
— no shells. Only the APT invocation uses sudo. Concurrent transactions are
blocked by a lock. See [security.md](security.md).
