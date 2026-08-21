"""Environment + config discovery (spec §13).

Reads /etc/os-release via Filesystem (never raw open), session info from an
injectable environ mapping, and asks each integrator what it can see.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from rice.core.fs import Filesystem, canonicalize
from rice.core.runner import CommandRunner
from rice.integrators import INTEGRATOR_CLASSES
from rice.integrators.common import DesktopIntegrator

SUPPORTED_DISTROS = frozenset({"ubuntu", "debian"})
DEBIAN_LIKE = frozenset({"debian"})


@dataclass(frozen=True)
class Detection:
    distro_id: str | None
    version_id: str | None
    like_id: str | None
    desktop: str | None
    wayland: bool

    @property
    def supported(self) -> bool:
        if self.distro_id in SUPPORTED_DISTROS:
            return True
        if self.like_id:
            return bool(DEBIAN_LIKE & {p.strip() for p in self.like_id.split(",")})
        return False


def parse_os_release(raw: bytes) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in raw.decode("utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        out[key.strip()] = value.strip().strip('"').strip("'")
    return out


class Detector:
    def __init__(
        self,
        fs: Filesystem,
        home: Path,
        runner: CommandRunner,
        environ: Mapping[str, str] | None = None,
        os_release_path: Path = Path("/etc/os-release"),
    ) -> None:
        self._fs = fs
        self.home = home
        self._environ = dict(environ) if environ is not None else dict(os.environ)
        self._os_release_path = os_release_path
        self._integrators = [cls(home, runner) for cls in INTEGRATOR_CLASSES]

    @property
    def integrators(self) -> list[DesktopIntegrator]:
        return list(self._integrators)

    def system(self) -> Detection:
        distro_id = version_id = like_id = None
        try:
            release = parse_os_release(self._fs.read(self._os_release_path))
            distro_id = release.get("ID") or None
            version_id = release.get("VERSION_ID") or None
            like_id = release.get("ID_LIKE") or None
        except OSError:
            pass  # unknown system: reported as unsupported downstream
        desktop = (
            self._environ.get("XDG_SESSION_DESKTOP")
            or self._environ.get("XDG_CURRENT_DESKTOP")
            or None
        )
        wayland = bool(self._environ.get("WAYLAND_DISPLAY"))
        return Detection(
            distro_id=distro_id,
            version_id=version_id,
            like_id=like_id,
            desktop=desktop,
            wayland=wayland,
        )

    def candidates(self) -> list[tuple[str, list[Path]]]:
        """[(name, existing config roots)] for every detected integrator."""
        out: list[tuple[str, list[Path]]] = []
        for integ in self._integrators:
            if integ.detect():
                dirs = [canonicalize(d) for d in integ.config_dirs()]
                if dirs:
                    out.append((integ.name, dirs))
        return out
