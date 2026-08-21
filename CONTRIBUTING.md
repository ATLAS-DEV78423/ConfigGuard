# Contributing to rice

## Ground rules

1. Read `CLAUDE.md` — those rules are hard constraints (no `shell=True`, no
   writes outside approved paths, no sudo in unit tests, etc.).
2. Every feature or bugfix ships with tests. Failure paths count.
3. Keep V1 scope; new scope needs explicit approval in an issue first.

## Workflow

```bash
pip install -e .[dev]
ruff format .
ruff check .
mypy rice
pytest -q
```

- Format with ruff; line length 100.
- Conventional-ish commit subjects: `feat:`, `fix:`, `docs:`, `test:`,
  `chore:`.
- PRs must pass CI (lint, type check, unit/cli/security, integration,
  recovery) on Ubuntu and Debian jobs.

## Reporting bugs

Include: distro + version (`cat /etc/os-release`), desktop, exact command,
full terminal output, and `~/.local/share/rice/logs/<latest>.log`. Never paste
config file contents into issues.
