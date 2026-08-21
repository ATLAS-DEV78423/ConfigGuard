"""Shared fixtures. Everything runs against an isolated fake $HOME.

Rice targets Linux only; the suite is executed in CI (Ubuntu/Debian).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from rice.core.fs import Filesystem

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture()
def fake_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isolated home pre-seeded with hyprland+waybar+kitty+wofi configs."""
    home = tmp_path / "home"
    home.mkdir(parents=True)
    for app in ("hyprland", "waybar", "kitty", "wofi"):
        src_root = FIXTURES / app / "original"
        if not src_root.is_dir():
            continue
        dest = home / ".config" / {"hyprland": "hypr", "wofi": "wofi"}.get(app, app)
        dest.mkdir(parents=True)
        for f in sorted(src_root.iterdir()):
            shutil.copy(f, dest)
    monkeypatch.setattr("rice.cli._HOME_OVERRIDE", home)
    return home


@pytest.fixture()
def fs() -> Filesystem:
    return Filesystem()
