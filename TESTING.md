# TESTING.md

## Layout

```
tests/
├── conftest.py        # fake HOME fixture, FakeCommandRunner
├── fixtures/<app>/{original,updated,conflicting}/   # hyprland, waybar, kitty, wofi
├── unit/              # fs, runner, config, state, detector, snapshot,
│                      # reconciler, validator, pkgmanagers, errors/logging
├── cli/               # Typer CliRunner command tests
├── integration/       # full update flow with fakes
├── recovery/          # interrupted-transaction / crash scenarios
└── security/          # symlink escape, traversal, tamper, shell-ban sweeps
```

## Rules

- Unit tests NEVER invoke sudo or any real package manager. All external
  commands go through `FakeCommandRunner` (scripted results).
- Filesystem tests run inside pytest `tmp_path`; no test touches the real
  `$HOME`.
- Every module requires tests; failure paths and crash-recovery are mandatory,
  not optional.

## Running

```bash
pip install -e .[dev]
pytest -q                     # everything
pytest tests/unit -q          # fast subset
ruff check . && ruff format --check .
mypy rice
```

CI (`.github/workflows/ci.yml`) runs lint, type check, unit/cli/security on
Ubuntu 24.04 + latest, integration/recovery separately, plus a Debian 13
container job.

Note: rice targets Linux only — do not expect the suite to pass on other
platforms (uid/gid, flock, signals are POSIX).
