# Development

## Setup

Linux required (Ubuntu 24.04+/Debian 13+). Do not develop against Windows.

```bash
pip install -e .[dev]
ruff format .
ruff check .
mypy rice
pytest -q
```

## Rules of the house

Read [CLAUDE.md](../CLAUDE.md) — hard constraints, including: no
`shell=True`; no subprocess outside `core/runner.py`; no raw file IO outside
`core/fs.py`; no sudo in unit tests; every feature ships with tests.

## Test suites

| Directory      | Covers                                            |
|----------------|---------------------------------------------------|
| `tests/unit/`  | fs, runner, config, state, detector, snapshot, reconciler, validator, pkgmanagers |
| `tests/cli/`   | command contracts and exit codes via CliRunner    |
| `tests/integration/` | full transactions with scripted fakes       |
| `tests/recovery/`    | crash-journal scenarios                     |
| `tests/security/`    | tamper/traversal/symlink + static sweeps    |

Fixtures live in `tests/fixtures/<app>/{original,updated,conflicting}/`.

## CI

GitHub Actions runs lint/type/unit/cli/security/integration/recovery on
Ubuntu 24.04, latest, and Debian 13. All green before merge.
