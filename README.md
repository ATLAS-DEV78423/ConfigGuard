# rice

Protect your Linux desktop "rice" during system updates.

`rice` wraps a system package update: it snapshots your customized desktop
configuration (Hyprland, Waybar, Kitty, Wofi/Rofi + user-selected extra
paths), runs the APT update, then detects any config changes caused by the
update and restores your customizations — with an interactive prompt when it
cannot safely auto-decide.

It protects **configuration integrity, preservation, and recovery**. It is
not a full-OS rollback tool.

## Status

v1.0.0. Targets Ubuntu 24.04+/Debian 13+ with APT and Hyprland desktops.
See `RICE_BUILD_SPEC.md` for scope.

## Install

```bash
pipx install rice-cli          # end users
```

From source:

```bash
git clone https://github.com/ATLAS-DEV78423/ConfigGuard && cd ConfigGuard
pip install .                  # or: pip install -e .[dev]
```

## Quick start

```bash
rice init                 # discover + choose configs to protect
rice status               # what is detected / protected / last snapshot
rice update               # snapshot -> apt upgrade -> reconcile -> validate
rice restore              # restore latest snapshot manually
```

## Commands

`init`, `status`, `snapshot [--pin]`, `update`, `diff [SNAPSHOT]`,
`restore [SNAPSHOT]`, `doctor [--fix]`, `snapshots list|show|delete|prune`.

Shell completion (bash/zsh/fish) is built in via Typer:
`rice --install-completion` / `rice --show-completion bash`.

Global flags (place immediately after `rice`): `--version`, `-v/--verbose`,
`--no-color`, `--quiet`, `--json`,
`--non-interactive`, `--dry-run`.

Exit codes: 0 success · 1 general · 2 usage · 3 config · 4 snapshot ·
5 update · 6 conflict · 7 validation · 8 recovery · 9 permission/sudo.

Docs: see `ARCHITECTURE.md`, `SECURITY.md`, `TESTING.md`, `CONTRIBUTING.md`,
and the `docs/` directory.

License: MIT.
