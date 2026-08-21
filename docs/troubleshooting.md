# Troubleshooting

## "no rice configuration found; run 'rice init'" (exit 3)

You have not initialized. Run `rice init` (or `rice init --non-interactive`
to accept all detected configs).

## "another rice transaction appears to be running"

A previous update/restore is still running, or was killed leaving a stale
lock at `~/.local/share/rice/transaction.lock`. Check with `ps aux | grep rice`;
if nothing is running and `rice doctor` reports no pending transaction,
remove the lock file.

## "another package manager is running" (exit 5)

APT/dpkg is busy (Synaptic, unattended-upgrades, another terminal). Wait for
it to finish; rice never bypasses dpkg locks.

## Update failed with exit 9

sudo could not authenticate. Run the command again in an interactive terminal
so sudo can prompt normally.

## Update failed mid-way (exit 5)

Your system packages may be partially upgraded — that is apt's business, not
rice's. Your configs were NOT touched. `rice restore <snapshot>` if you want
the pre-update config state anyway.

## Hyprland looks broken after an update

```bash
rice diff          # what changed vs the snapshot?
rice restore       # put back your last known-good config
hyprctl reload
```

If a NEW hyprland version changed its config format, restoring your old file
restores compatibility only until you migrate — check Hyprland release notes.

## Snapshot restore refuses ("hash mismatch", exit 4)

The backup data changed after creation (disk fault, manual tampering). Rice
will not restore unverified data. Delete that snapshot only if you are sure:
`rice snapshots delete <id> --force`.

## Where are the logs?

`~/.local/share/rice/logs/rice-YYYYMMDD.log`. Logs contain metadata only,
never config contents.
