# Rice Progression Plan — Road to v1.0.0 Release

**Goal:** Ship rice v1.0.0 — reviewed, CI-green, manually verified on real Linux
desktops, packaged, and installed-from-artifact.

**State of record:** Phase 0 DONE (CI green, all five jobs, run
`32721099488`). Phase 2 DONE (hardening complete; wheel/sdist built).
Phase 1 BLOCKED ON OWNER (execution deferred from this machine by owner).
Phase 3 GATED on Phase 1. Three review rounds closed (18 findings).

**Ground rules:** `CLAUDE.md` governs everything below. V1 scope is locked —
no new features while marching to release. Every behavior change needs a
suite-wide grep for old-contract assertions before push (lesson from the
`test_validator.py` incident).

---

## Phase 0 — Green CI *(blocking everything else)*

**Status: DONE** — two commits, one extra finding found by reading raw logs.

- [x] **0.1 Replace the stale waybar contract test.**
      Done in `8b66634`: `tests/unit/test_validator.py` now pins
      `ok=None` + "manual check needed" for strict-parse failure (B3 contract).

- [x] **0.2 Sweep for any other old-contract pins before pushing:**
      Done in `8b66634`: remaining `ok is False` hits are all the hyprland
      hard-failure contract (hyprctl reload), which B3 never changed. Zero
      hits for removed APIs.

- [x] **0.3 Static gates:** ruff check / format / mypy clean.

- [x] **0.4 Push + confirm CI green.** Took TWO commits:
      - `8b66634` — stale-test fix: 4/5 green, but Debian trixie failed
        `test_completion_bash_zsh_fish`. Raw log showed `--show-completion`
        auto-detects the parent shell; the bare trixie container has none →
        `Exit(1)`. (The old assertion was too weak to catch that Ubuntu jobs
        were passing for the wrong reason too.)
      - `bc651c3` — test now sets typer's own seam
        `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION=1` and asserts the
        correct per-shell script fragment.
      - Run `32721099488`: **all five jobs success.**

---

## Phase 1 — Real-Linux Verification *(CI cannot prove this part)*

> **Status: BLOCKED ON OWNER** — owner explicitly deferred all execution
> from this machine ("I will test later"). Instructions below are final and
> paste-ready. Nothing in Phase 2/3 ships until these boxes are checked.

> **Safety first:** `rice update` runs `sudo apt upgrade -y`. Do NOT first-run
> it on your daily driver. Use a throwaway Ubuntu 24.04 VM or a fresh Debian 13
> container/snapshot you can roll back. (WSL was considered and rejected:
> not installed, needs admin+reboot, and the desktop VM is required anyway
> for drill 1.6.)

**Environment:** Ubuntu 24.04 desktop VM (Hyprland or Wayland session) +
Debian 13 trixie. On each:

```bash
sudo apt update && sudo apt install -y python3-pip python3-venv git
git clone https://github.com/ATLAS-DEV78423/ConfigGuard && cd ConfigGuard
python3 -m venv .venv && source .venv/bin/activate
pip install -e .[dev]
```

- [ ] **1.1 Full suite on bare metal:**

```bash
ruff check . && ruff format --check . && mypy rice
pytest tests/unit tests/cli tests/security -q     # expect: all pass
pytest tests/integration tests/recovery -q        # expect: all pass
```

- [ ] **1.2 Happy path against a REAL desktop session:**

```bash
rice --version                      # prints rice x.y.z (semver)
rice init                           # interactive: detect, protect, extra path
cat ~/.config/rice/config.toml      # tilde-form paths, [rice]+[protected]
rice status                         # distro/desktop/snapshot lines
rice snapshot                       # note the id
rice diff                           # "0 difference(s)"
```

- [ ] **1.3 Snapshot → breakage → restore round trip:**

```bash
cp ~/.config/hypr/hyprland.conf /tmp/hypr.bak   # your own belt-and-braces
echo "# drift" >> ~/.config/hypr/hyprland.conf
rice diff                                       # shows CHANGED + unified diff
rice restore                                    # confirm prompt
diff ~/.config/hypr/hyprland.conf /tmp/hypr.bak # identical
```

- [ ] **1.4 Broken-symlink restore drill (B1 regression, live):**

```bash
rice snapshot
ln -sfn ~/.config/hypr/nonexistent ~/.config/hypr/current-theme
rice restore            # must NOT crash; dangling link replaced cleanly
```

- [ ] **1.5 Recovery drill — interrupt a real update:**

```bash
rice update             # let apt start downloading, then Ctrl-C mid-flight
rice status             # "[!] Interrupted transaction ... run 'rice doctor'"
rice doctor             # pending-transaction check fails, exit 7
rice doctor --fix       # restores snapshot, exit 0
rice doctor             # clean, exit 0
```

- [ ] **1.6 Validation semantics:** corrupt waybar config to non-JSON, run
      `rice update` — expect `ok=None` ("manual check needed"), NO rollback
      offer (B3 contract). Then break hyprland config so `hyprctl reload`
      fails — expect rollback prompt (ok=False path still works).

- [ ] **1.7 Conflict flow:** edit a protected file so apt's package version
      differs; run `rice update`; answer `[3] diff`, then `[1] keep mine`.
      Verify journal decisions recorded paths only:
      `cat ~/.local/share/rice/transactions/*.json` (no file contents).

- [ ] **1.8 Lock + sudo mapping:** hold the dpkg lock
      (`sudo fuser /var/lib/dpkg/lock-frontend` from another shell simulating
      is enough to observe messaging via a second `rice update`) — expect the
      "another package manager is running" refusal, exit 5/9 family, never a
      bypass.

- [ ] **1.9 Log hygiene:** after all drills,
      `grep -riE "password|token|secret" ~/.local/share/rice/logs/` → no hits;
      spot-check redaction: `logger` output for secret-shaped strings shows
      `<redacted>` (B2 wiring).

---

## Phase 2 — Release Hardening

**Status: DONE (owner-deferred item noted in 2.5).**

- [x] **2.1 Version bump:** 0.1.0 → 1.0.0 in `rice/__init__.py`,
      `pyproject.toml`, `RiceConfig.version` default, `load_config` default,
      and the `docs/configuration.md` example.
- [x] **2.2 CHANGELOG.md:** created; Fixed/Removed/Changed/Verification
      sections reflect the actual three-round history.
- [x] **2.3 README:** pipx install path added alongside source checkout.
      Command audit found REAL drift: docs claimed a `rice version`
      subcommand that never shipped (only `--version` flag exists, pinned by
      CI test). Fixed README, REQUIREMENTS, spec §5 usage table,
      docs/installation.md to match shipped behavior.
- [x] **2.4 Docs pass:** suite-wide stale-claim grep clean
      (metadata.json / changed_packages / `rice completion` / absolute-path
      config examples all gone from living docs; historical archives
      untouched deliberately).
- [x] **2.5 Packaging smoke (build half):** `uv build` produces
      sdist+wheel for rice_cli-1.0.0; all 23 modules present, tests
      excluded, entry point declared. Also fixed setuptools' license-table
      deprecation (SPDX string now; old form breaks builds 2027).
      **DEFERRED to owner's Linux box:** fresh-venv wheel install +
      `rice --version` (executing rice off-Linux is forbidden by CLAUDE.md) —
      fold this into Phase 1 step 1.2.
- [x] **2.6 Final ponytail pass:** `/ponytail-audit` verdict:
      **"Lean already. Ship."** — net -0 lines, -0 deps.

---

## Phase 3 — Cut the Release

> **Status: GATED on Phase 1.** The Definition of Done requires the manual
> matrix green before tagging. Commands below are prepared, not executed.

- [ ] **3.1 Tag:** `git tag -a v1.0.0 -m "rice v1.0.0"` && push tag.
- [ ] **3.2 GitHub Release** with sdist+wheel attached and CHANGELOG body.
- [ ] **3.3 PyPI publish** — EXPLICIT DECISION POINT (owner call): `pipx`
      users need PyPI or a direct wheel URL. If PyPI: use trusted publishing
      or a token scoped to the project only.
- [ ] **3.4 Post-release dogfood window:** run real weekly updates via
      `rice update` on one machine for 1–2 weeks; file regressions before
      advertising the tool.

## Definition of Done

- [ ] All Phase 0–3 boxes checked.
- [ ] CI green on the release tag (all five jobs).
- [ ] Manual verification matrix (Phase 1) done on BOTH Ubuntu 24.04 and
      Debian 13.
- [ ] Installable from artifact in a clean venv, offline of the repo checkout
      (owner's Linux box: `pip install dist/rice_cli-1.0.0-py3-none-any.whl`
      in a fresh venv, then `rice --version`).
- [x] Zero open review findings; audit verdict "Lean already."

## Standing Watchlist (known ceilings — do not "fix" casually)

| Item | Ceiling | Upgrade trigger |
|---|---|---|
| Waybar JSONC stripper | full-line `//` only; parse fail = manual check | if false-manual rate annoys real configs |
| `save_config` resolve symmetry | assumes canonical paths when home sits behind symlink | multi-user/network-home bug reports |
| Logging global-state reset | single-process assumption | pytest-xdist adoption |
| typer `--show-completion <shell>` | test relies on `_TYPER_COMPLETE_TEST_DISABLE_SHELL_DETECTION` seam + per-shell script fragments | typer upgrade (seam renamed/removed) |
