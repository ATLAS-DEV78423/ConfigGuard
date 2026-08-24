# Rice Progression Plan — Road to v1.0.0 Release

**Goal:** Ship rice v1.0.0 — reviewed, CI-green, manually verified on real Linux
desktops, packaged, and installed-from-artifact.

**State of record:** commit `aeb96e8` on `master`. Three review rounds complete
(18 findings closed). Static gates green locally. CI is RED on one stale test
(see Phase 0). Nothing is released until every phase below is checked off.

**Ground rules:** `CLAUDE.md` governs everything below. V1 scope is locked —
no new features while marching to release. Every behavior change needs a
suite-wide grep for old-contract assertions before push (lesson from the
`test_validator.py` incident).

---

## Phase 0 — Green CI *(blocking everything else)*

**Status: OPEN** — run `32718882514` failed 3 jobs on one root cause.

- [ ] **0.1 Replace the stale waybar contract test.**
      `tests/unit/test_validator.py:29-40` pins the pre-B3 behavior
      (`ok is False`). Delete that test and insert:

```python
def test_waybar_valid_json_ok_invalid_json_is_manual_check(tmp_path: Path) -> None:
    """B3 contract: strict-parse failure is NOT proof of a broken config
    (the stripper is deliberately partial) -> ok=None, never ok=False."""
    home = tmp_path / "home"
    wb = home / ".config" / "waybar"
    wb.mkdir(parents=True)
    (wb / "config").write_text('{"clock": {"format": "%H:%M"}}')
    good = Validator(Filesystem(), FakeCommandRunner(), home).validate_all(["waybar"])
    assert good[0].ok is True

    (wb / "config").write_text("{not json")
    bad = Validator(Filesystem(), FakeCommandRunner(), home).validate_all(["waybar"])
    assert bad[0].ok is None
    assert "manual check needed" in bad[0].message
```

- [ ] **0.2 Sweep for any other old-contract pins before pushing:**

```bash
rg -n "ok is False|ok == False|\.ok\b.*False" tests/
rg -n "changed_packages|on_decision|metadata\.json|capture\(" rice/ tests/
```
      Expected: no hits outside historical docs (`references/`, build-plan).

- [ ] **0.3 Static gates:** `ruff check . && ruff format --check . && mypy rice`

- [ ] **0.4 Commit (`test: pin B3 waybar contract in validator suite`), push,
      confirm all four CI jobs green:

```bash
$env:GH_TOKEN="<token>"; gh run list --limit 1
gh run view <run-id> --json jobs | ConvertFrom-Json | % { $_.jobs | % { "$($_.name) => $($_.conclusion)" } }
```
      Expected: `lint + format + types`, `unit/cli/security (ubuntu-latest)`,
      `unit/cli/security (ubuntu-24.04)`, `integration + recovery`,
      `Debian 13 (trixie)` all `success`.

---

## Phase 1 — Real-Linux Verification *(CI cannot prove this part)*

> **Safety first:** `rice update` runs `sudo apt upgrade -y`. Do NOT first-run
> it on your daily driver. Use a throwaway Ubuntu 24.04 VM or a fresh Debian 13
> container/snapshot you can roll back.

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

- [ ] **2.1 Version bump:** `rice/__init__.py` and `pyproject.toml`
      0.1.0 → 1.0.0 (both files, keep `config.version` default in sync).
- [ ] **2.2 CHANGELOG.md:** summarize 0.1.0→1.0.0: three review rounds,
      restore-safety hoist (B1/B5/N1/N2), handler-level redaction (B2),
      waybar manual-check semantics (B3), tilde-form config storage (B4/B6),
      dead-API removals (-65 source lines net).
- [ ] **2.3 README install section:** add `pipx install rice-cli` path
      alongside dev checkout; verify documented commands all exist
      (`rg -o 'rice [a-z-]+' README.md docs/` vs `rice --help`).
- [ ] **2.4 Docs pass:** `docs/*.md` claims match reality (exit codes table,
      snapshots layout without metadata.json, completion via
      `--install-completion`).
- [ ] **2.5 Packaging smoke:** `python -m build` (or `uv build`) produces
      sdist+wheel; install wheel into a FRESH venv; `rice --version` works;
      entry point `rice = "rice.cli:app"` functional.
- [ ] **2.6 Final ponytail pass:** `/ponytail-audit` — expected verdict:
      nothing to cut.

---

## Phase 3 — Cut the Release

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
- [ ] Installable from artifact in a clean venv, offline of the repo checkout.
- [ ] Zero open review findings; audit verdict "Lean already."

## Standing Watchlist (known ceilings — do not "fix" casually)

| Item | Ceiling | Upgrade trigger |
|---|---|---|
| Waybar JSONC stripper | full-line `//` only; parse fail = manual check | if false-manual rate annoys real configs |
| `save_config` resolve symmetry | assumes canonical paths when home sits behind symlink | multi-user/network-home bug reports |
| Logging global-state reset | single-process assumption | pytest-xdist adoption |
| typer `--show-completion <shell>` | pinned by test; typer major bumps may shift arg order | typer upgrade |
