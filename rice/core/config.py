"""rice configuration: ~/.config/rice/config.toml (spec §12).

Stored values keep ``~/...`` form on disk; in memory everything is expanded
against the effective home. Reading uses stdlib ``tomllib``; writing needs the
tiny ``tomli-w`` (stdlib has no TOML writer).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

import tomli_w

from rice.core.errors import ConfigError
from rice.core.fs import Filesystem

DEFAULT_DATA_DIR = "~/.local/share/rice"
KNOWN_APPS = ("hyprland", "waybar", "kitty", "wofi", "extra")


@dataclass
class RiceConfig:
    """What rice protects and where it stores its data."""

    data_dir: Path  # expanded, e.g. /home/u/.local/share/rice
    protected: dict[str, list[Path]]  # app name -> expanded absolute paths
    version: str = "0.1.0"


def config_path(home: Path | None = None) -> Path:
    """Config file location; injectable home keeps tests off the real one."""
    if home is None:
        return Path.home() / ".config" / "rice" / "config.toml"
    return home / ".config" / "rice" / "config.toml"


def expand_path(home: Path | None, value: str) -> Path:
    """Expand ~; anchor relative paths to home when a test home is injected.

    expanduser() is deliberately avoided: it reads the REAL $HOME, which would
    defeat the injected-home isolation used by tests and multi-user tooling.
    """
    base = home if home is not None else Path.home()
    p = Path(value)
    if p.parts and p.parts[0] == "~":
        p = base.joinpath(*p.parts[1:])
    elif not p.is_absolute():
        p = base / p
    return p


def load_config(fs: Filesystem, home: Path | None = None) -> RiceConfig:
    """Load config or raise ConfigError(3) telling the user to run init."""
    path = config_path(home)
    if not fs.exists(path):
        raise ConfigError("no rice configuration found; run 'rice init' first")
    try:
        raw = tomllib.loads(fs.read(path).decode("utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"config file {path} is invalid TOML: {exc}") from exc

    rice_tbl = raw.get("rice", {})
    prot_tbl = raw.get("protected", {})
    if not isinstance(rice_tbl, dict) or not isinstance(prot_tbl, dict):
        raise ConfigError(f"config file {path} has unexpected structure")

    data_dir_raw = rice_tbl.get("data_dir", DEFAULT_DATA_DIR)
    if not isinstance(data_dir_raw, str):
        raise ConfigError("[rice] data_dir must be a string")
    data_dir = expand_path(home, data_dir_raw)

    protected: dict[str, list[Path]] = {}
    for app, entries in prot_tbl.items():
        if not isinstance(entries, list) or not all(isinstance(e, str) for e in entries):
            raise ConfigError(f"[protected] {app} must be a list of path strings")
        protected[app] = [expand_path(home, e) for e in entries]

    return RiceConfig(
        data_dir=data_dir,
        protected=protected,
        version=str(rice_tbl.get("version", "0.1.0")),
    )


def save_config(cfg: RiceConfig, fs: Filesystem, home: Path | None = None) -> Path:
    """Persist config atomically; returns the path written.

    Paths under home are stored in ``~/...`` form (spec §12); anything else
    stays absolute. Paths are resolved() here, so callers should pass
    canonical paths when home itself sits behind a symlink.
    """
    base = (home if home is not None else Path.home()).resolve()

    def fmt(p: Path) -> str:
        try:
            return "~/" + p.resolve().relative_to(base).as_posix()
        except ValueError:
            return str(p)

    doc: dict[str, object] = {
        "rice": {"data_dir": fmt(cfg.data_dir), "version": cfg.version},
        "protected": {app: [fmt(p) for p in paths] for app, paths in sorted(cfg.protected.items())},
    }
    path = config_path(home)
    fs.write_atomically(path, tomli_w.dumps(doc).encode("utf-8"))
    return path


def protected_paths(cfg: RiceConfig) -> list[Path]:
    """Flattened, deduplicated, order-stable protected roots."""
    seen: set[Path] = set()
    out: list[Path] = []
    for app in (*KNOWN_APPS, *sorted(set(cfg.protected) - set(KNOWN_APPS))):
        for p in cfg.protected.get(app, []):
            if p not in seen:
                seen.add(p)
                out.append(p)
    return out
