# Recovery

## Interrupted transactions

If `rice update` is interrupted (power loss, kill -9, Ctrl-C), the journal at
`~/.local/share/rice/transactions/<id>.json` records exactly where it stopped.

```bash
$ rice status
[!] Interrupted transaction 20260821-130001 in state UPDATING; run 'rice doctor'

$ rice doctor --fix
[ok] protected-paths: 2/2 present
[!!] pending-transaction: state=UPDATING
[ok] last-snapshot-integrity: 2026-08-21T12-59-40Z verified
Recovered 1 interrupted transaction(s).
```

`doctor --fix` restores every tracked file from the referenced snapshot
(verified by hash first) and clears the journal. Recovery is idempotent — run
it twice and nothing changes the second time.

## Manual restore

```bash
rice restore                 # latest snapshot (asks confirmation)
rice restore <snapshot-id>   # explicit
```

Restore copies files over the current ones with full metadata (mode, owner,
group, mtime, symlink shape) and never deletes originals first.

## Failure semantics during update

| Failure                    | What rice does                                     | Exit |
|----------------------------|----------------------------------------------------|------|
| apt/dpkg lock held         | Refuses to start; never bypasses locks             | 5    |
| sudo fails                 | No reconciliation attempt                          | 9    |
| apt upgrade non-zero       | Leaves system as-is; snapshot kept for you         | 5    |
| conflict + abort choice    | Rolls back everything to the snapshot              | 6    |
| validation failure         | Offers rollback; auto-rollback if non-interactive  | 7    |

Rice protects configuration, not the operating system: it does not downgrade
packages or roll back kernels.
