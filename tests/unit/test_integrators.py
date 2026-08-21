"""Integrator contracts: detection, config roots, read-only validation."""

from __future__ import annotations

from pathlib import Path

from support import FakeCommandRunner

from rice.core.fs import Filesystem
from rice.core.runner import RunResult
from rice.integrators import INTEGRATOR_CLASSES
from rice.integrators.hyprland import HyprlandIntegrator
from rice.integrators.kitty import KittyIntegrator
from rice.integrators.waybar import WaybarIntegrator, strip_jsonc_comments
from rice.integrators.wofi import WofiIntegrator


def make_home(tmp_path: Path, apps: list[str]) -> Path:
    home = tmp_path / "home"
    for app in apps:
        (home / ".config" / app).mkdir(parents=True)
    return home


def test_registry_order_fixed() -> None:
    assert [cls.name for cls in INTEGRATOR_CLASSES] == ["hyprland", "waybar", "kitty", "wofi"]


def test_detect_true_when_dir_exists_false_otherwise(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["hypr", "waybar"])
    fake = FakeCommandRunner()
    assert HyprlandIntegrator(home, fake).detect()
    assert WaybarIntegrator(home, fake).detect()
    assert not KittyIntegrator(home, fake).detect()
    assert not WofiIntegrator(home, fake).detect()


def test_config_dirs_only_existing_roots(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["kitty"])
    integ = KittyIntegrator(home, FakeCommandRunner())
    dirs = integ.config_dirs()
    assert dirs == [home / ".config" / "kitty"]


def test_wofi_picks_up_rofi_too(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["rofi"])
    integ = WofiIntegrator(home, FakeCommandRunner())
    assert integ.detect()
    assert integ.config_dirs() == [home / ".config" / "rofi"]


def test_base_validate_is_manual_check(tmp_path: Path) -> None:
    from rice.integrators.common import DesktopIntegrator

    class Bare(DesktopIntegrator):
        name = "bare"

        def detect(self) -> bool:
            return False

        def config_dirs(self) -> list[Path]:
            return []

    result = Bare(tmp_path, FakeCommandRunner()).validate(Filesystem())
    assert result.ok is None and "manual" in result.message


def test_hyprland_validate_reload_ok(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["hypr"])

    def script(args: list[str]) -> RunResult:
        if args[:2] == ["hyprctl", "--version"]:
            return RunResult(args=args, returncode=0)
        if args == ["hyprctl", "reload"]:
            return RunResult(args=args, returncode=0)
        return RunResult(args=args, returncode=1)

    result = HyprlandIntegrator(home, FakeCommandRunner(script=script)).validate(Filesystem())
    assert result.ok is True


def test_hyprland_validate_reload_failure_reports_message(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["hypr"])

    def script(args: list[str]) -> RunResult:
        if args[:2] == ["hyprctl", "--version"]:
            return RunResult(args=args, returncode=0)
        return RunResult(args=["hyprctl", "reload"], returncode=1, stderr="config error at line 3")

    result = HyprlandIntegrator(home, FakeCommandRunner(script=script)).validate(Filesystem())
    assert result.ok is False
    assert "line 3" in result.message


def test_hyprland_validate_unavailable_means_manual(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["hypr"])
    failing = FakeCommandRunner(results=[RunResult(args=[], returncode=1)])
    result = HyprlandIntegrator(home, failing).validate(Filesystem())
    assert result.ok is None and "manual" in result.message


def test_waybar_jsonc_comment_stripping() -> None:
    text = '{\n// a comment\n"a": 1\n}\n'
    assert '"a": 1' in strip_jsonc_comments(text)
    assert "//" not in strip_jsonc_comments(text)


def test_waybar_validate_parses_conflicting_fixture(tmp_path: Path) -> None:
    """The conflicting fixture uses jsonc comments; parse must succeed."""
    import shutil

    home = make_home(tmp_path, ["waybar"])
    src = Path(__file__).parents[1] / "fixtures" / "waybar" / "conflicting" / "config"
    dst = home / ".config" / "waybar" / "config"
    shutil.copy(src, dst)

    def script(args: list[str]) -> RunResult:
        return RunResult(args=args, returncode=1)  # waybar binary absent

    result = WaybarIntegrator(home, FakeCommandRunner(script=script)).validate(Filesystem())
    assert result.ok is True
    assert "parse ok" in result.message


def test_validators_never_mutate_configs(tmp_path: Path) -> None:
    home = make_home(tmp_path, ["waybar"])
    conf = home / ".config" / "waybar" / "config"
    conf.write_text('{"a": 1}')
    before = conf.read_text()
    WaybarIntegrator(home, FakeCommandRunner()).validate(Filesystem())
    assert conf.read_text() == before
