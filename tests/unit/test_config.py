"""RiceConfig: TOML round-trip, error on missing, path expansion, ordering."""

from __future__ import annotations

from pathlib import Path

import pytest

from rice.core.config import (
    KNOWN_APPS,
    RiceConfig,
    config_path,
    load_config,
    protected_paths,
    save_config,
)
from rice.core.errors import ConfigError
from rice.core.fs import Filesystem


def test_missing_config_raises_code3(tmp_path: Path) -> None:
    fs = Filesystem()
    with pytest.raises(ConfigError) as exc:
        load_config(fs, home=tmp_path)
    assert exc.value.exit_code == 3
    assert "rice init" in str(exc.value)


def test_save_load_round_trip(tmp_path: Path) -> None:
    fs = Filesystem()
    cfg = RiceConfig(
        data_dir=tmp_path / ".local/share/rice",
        protected={
            "hyprland": [tmp_path / ".config/hypr"],
            "extra": [tmp_path / ".config/user-paths"],
        },
    )
    save_config(cfg, fs, home=tmp_path)
    loaded = load_config(fs, home=tmp_path)
    assert loaded.data_dir == cfg.data_dir
    assert loaded.protected["hyprland"] == [tmp_path / ".config/hypr"]
    assert loaded.protected["extra"] == [tmp_path / ".config/user-paths"]


def test_config_file_shape_matches_spec(tmp_path: Path) -> None:
    """Spec §12 shape: [rice] + [protected] sections."""
    fs = Filesystem()
    cfg = RiceConfig(
        data_dir=tmp_path / "d", protected={"kitty": [tmp_path / ".config/kitty"]}
    )
    p = save_config(cfg, fs, home=tmp_path)
    text = fs.read(p).decode()
    assert "[rice]" in text and "[protected]" in text
    assert "data_dir" in text and "kitty" in text


def test_tilde_expansion_against_injected_home(tmp_path: Path) -> None:
    fs = Filesystem()
    raw = config_path(tmp_path)
    fs.write_atomically(
        raw,
        b'[rice]\ndata_dir = "~/.local/share/rice"\n\n[protected]\nwaybar = ["~/.config/waybar"]\n',
    )
    loaded = load_config(fs, home=tmp_path)
    assert loaded.data_dir == tmp_path / ".local/share/rice"
    assert loaded.protected["waybar"] == [tmp_path / ".config/waybar"]


def test_invalid_toml_raises_config_error(tmp_path: Path) -> None:
    fs = Filesystem()
    fs.write_atomically(config_path(tmp_path), b"[rice\ndata_dir=")
    with pytest.raises(ConfigError):
        load_config(fs, home=tmp_path)


def test_protected_paths_order_and_dedupe(tmp_path: Path) -> None:
    a = tmp_path / "a"
    b = tmp_path / "b"
    cfg = RiceConfig(
        data_dir=tmp_path / "d",
        protected={"extra": [b, a], "hyprland": [a], "waybar": [b]},
    )
    out = protected_paths(cfg)
    # KNOWN_APPS order first (hyprland, waybar, kitty, wofi, extra), deduped.
    assert out == [a, b]


def test_known_apps_constant() -> None:
    assert KNOWN_APPS == ("hyprland", "waybar", "kitty", "wofi", "extra")
