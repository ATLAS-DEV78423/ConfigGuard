# Snapshots

## Layout

```
~/.local/share/rice/
├── snapshots/
│   └── 2026-08-21T12-04-33Z/
│       ├── manifest.json     # per-file metadata incl. SHA-256
│       ├── metadata.json     # counts, pinned flag
│       └── files/            # copied configs, home-relative structure
├── transactions/<txn>.json   # journals, deleted when finished
├── logs/rice-YYYYMMDD.log
└── transaction.lock
```

Two snapshots taken in the same second get a `-N` suffix; ids stay unique.

## Commands

```bash
rice snapshot [--pin]          # capture now (honors --dry-run)
rice --json snapshots list      # id, file count, pinned flag (global flags go first)
rice snapshots show [ID]       # manifest details (default: latest)
rice snapshots delete ID       # asks confirmation; --force / --non-interactive needs it
rice --dry-run snapshots prune
```

`restore`, `diff`, and `snapshots show` default to the latest snapshot when no
id is given. In `--non-interactive` mode `delete` requires an explicit id plus
`--force`.

## Retention (`snapshots prune`)

Keeps: all pinned snapshots, the newest 10 unpinned, and anything created in
the last 30 days. Deletes the rest. Pinned snapshots are never pruned.

## Integrity

Every restore re-hashes every backup file against the manifest first
(SHA-256). Any mismatch aborts the restore before your live configs are
touched.
