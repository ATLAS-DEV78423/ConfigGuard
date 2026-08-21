# Architecture

Authoritative details: [ARCHITECTURE.md](../ARCHITECTURE.md) and spec §7–§23.

```
cli.py                 Typer entrypoint; RiceError -> exit codes
core/
  errors.py            one exception class per exit code
  fs.py                Filesystem seam (atomic writes, hashing, scope checks)
  runner.py            CommandRunner seam (argv lists; sudo prefix)
  loggingx.py          redacting logger
  config.py            config.toml load/save
  state.py             TransactionState machine + persisted journal
  detector.py          /etc/os-release + session + integrator discovery
  snapshot.py          create/verify/restore/list/delete/prune
  reconciler.py        post-update classification + resolution
  validator.py         per-app validation aggregation
  updater.py           run_protected_update(): locking, signals, recovery
pkgmanagers/           PackageManager ABC + APT impl
integrators/           DesktopIntegrator ABC + hyprland/waybar/kitty/wofi
```

Two seams make everything testable: modules never call raw filesystem or
subprocess APIs, so tests substitute fakes at exactly those boundaries.

The state machine guarantees every update ends in a known state even after a
power loss — see [concepts.md](concepts.md) and [recovery.md](recovery.md).
