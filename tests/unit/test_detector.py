"""Detector: os-release parsing, session env, candidate discovery."""

from __future__ import annotations

from pathlib import Path

from support import FakeCommandRunner

from rice.core.detector import Detection, Detector, parse_os_release
from rice.core.fs import Filesystem

UBUNTU_RELEASE = b'NAME="Ubuntu"\nID=ubuntu\nVERSION_ID="24.04"\n'
DEBIAN_RELEASE = b'ID=debian\nVERSION_ID="13"\n'
ARCH_RELEASE = b"ID=arch\nID_LIKE=arch\n"


def make_detector(
    tmp_path: Path,
    release: bytes | None = None,
    environ: dict[str, str] | None = None,
    apps: list[str] | None = None,
) -> Detector:
    fs = Filesystem()
    if release is not None:
        p = tmp_path / "os-release"
        p.write_bytes(release)
    else:
        p = tmp_path / "missing-os-release"
    home = tmp_path / "home"
    for app in apps or []:
        (home / ".config" / app).mkdir(parents=True)
    return Detector(fs, home, FakeCommandRunner(), environ=environ, os_release_path=p)


def test_parse_os_release_strips_quotes() -> None:
    out = parse_os_release(UBUNTU_RELEASE)
    assert out["ID"] == "ubuntu" and out["VERSION_ID"] == "24.04"


def test_ubuntu_supported(tmp_path: Path) -> None:
    det = make_detector(tmp_path, UBUNTU_RELEASE)
    d = det.system()
    assert isinstance(d, Detection)
    assert d.distro_id == "ubuntu" and d.supported


def test_debian_supported(tmp_path: Path) -> None:
    assert make_detector(tmp_path, DEBIAN_RELEASE).system().supported


def test_arch_unsupported(tmp_path: Path) -> None:
    assert not make_detector(tmp_path, ARCH_RELEASE).system().supported


def test_missing_release_is_unsupported_not_crash(tmp_path: Path) -> None:
    d = make_detector(tmp_path, release=None).system()
    assert d.distro_id is None and not d.supported


def test_desktop_and_wayland_from_environ(tmp_path: Path) -> None:
    det = make_detector(
        tmp_path,
        UBUNTU_RELEASE,
        environ={"XDG_SESSION_DESKTOP": "hyprland", "WAYLAND_DISPLAY": "wayland-1"},
    )
    d = det.system()
    assert d.desktop == "hyprland" and d.wayland


def test_candidates_reflect_home_layout(tmp_path: Path) -> None:
    det = make_detector(tmp_path, UBUNTU_RELEASE, apps=["hypr", "kitty"])
    names = [name for name, _dirs in det.candidates()]
    assert names == ["hyprland", "kitty"]


def test_candidates_empty_when_nothing_detected(tmp_path: Path) -> None:
    assert make_detector(tmp_path, UBUNTU_RELEASE, apps=[]).candidates() == []
