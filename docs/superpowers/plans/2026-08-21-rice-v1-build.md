# Rice CLI V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline, recommended here) or superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the complete V1 of `rice`, a safety-critical Linux CLI that snapshots a user's desktop config, runs an APT update, and reconciles so customizations survive — per `RICE_BUILD_SPEC.md`.

**Architecture:** Layered Python package. Two testable seams (`Filesystem`, `CommandRunner`) mean no core module ever calls raw `open()`/`subprocess`. A persisted transaction-journal state machine makes every update crash-recoverable. Integrators (Hyprland/Waybar/Kitty/Wofi) and package managers (APT) are plugin ABCs.

**Tech Stack:** Python 3.11+, Typer (CLI), stdlib (`tomllib`, `difflib`, `hashlib`, `fcntl`, `signal`), `tomli-w` (TOML writer; stdlib has no writer). Dev: pytest, ruff, mypy.

**Spec:** `RICE_BUILD_SPEC.md` (authoritative) + `REQUIREMENTS.md` (traceability). This plan argues from the spec; both travel with the executor.

## Global Constraints

- **Platform:** Code targets Linux only. **DO NOT execute, compile, or run any rice code or tests on Windows.** Verification = CI on Ubuntu/Debian + user's manual testing. Every "run tests" step in this plan is deferred to CI.
- Python `>=3.11`; full type annotations; mypy passes; ruff clean.
- **No `shell=True`, no shell-string commands, anywhere.** All commands are argv lists.
- Zero direct `open()`/`os.remove`/`shutil` mutations in modules outside `core/fs.py`; zero direct subprocess outside `core/runner.py`.
- No sudo in unit tests — always `FakeCommandRunner`.
- Exit codes (exact): 0 success, 1 general, 2 usage, 3 config, 4 snapshot, 5 update, 6 conflict, 7 validation, 8 recovery, 9 permission/sudo.
- Writes only inside: `~/.config/rice/`, `~/.local/share/rice/`, protected paths from config.toml. Atomic writes everywhere (tmp → fsync → rename).
- Never log config file contents (hashes/metadata only); never touch sudo passwords.
- V1 exclusions (do NOT build): GUI/TUI, telemetry, 3-way merge, cloud sync, git integration, Arch/Fedora/Sway/i3, `/etc` edits, dist-upgrade.
- Runtime deps limited to: `typer`, `tomli-w`. Dev deps: `pytest`, `ruff`, `mypy`.
- Tests are written alongside each module but **executed only in CI** (Linux). Local step = write + re-read for import/type consistency.

## File Structure (final tree)

```
ConfigGuard/
├── RICE_BUILD_SPEC.md, REQUIREMENTS.md          # existing
├── pyproject.toml                               # Task 1
├── README.md, CLAUDE.md, ARCHITECTURE.md,
│   SECURITY.md, TESTING.md, CONTRIBUTING.md     # Tasks 1 & 15
├── .github/workflows/ci.yml                     # Task 15
├── rice/
│   ├── __init__.py                              # __version__
│   ├── cli.py                                   # Typer app, exit-code map, all commands
│   ├── core/
│   │   ├── __init__.py                          # empty
│   │   ├── errors.py                            # RiceError hierarchy w/ exit codes
│   │   ├── fs.py                                # Filesystem, FileMeta, scope checks
│   │   ├── runner.py                            # CommandRunner, RunResult
│   │   ├── loggingx.py                          # setup, redaction
│   │   ├── config.py                            # RiceConfig load/save (tomllib/tomli-w)
│   │   ├── state.py                             # TransactionState, TransactionJournal
│   │   ├── detector.py                          # OS/desktop/config discovery
│   │   ├── snapshot.py                          # create/verify/restore/list/delete/prune
│   │   ├── reconciler.py                        # diff classification + resolution
│   │   ├── validator.py                         # per-app validation
│   │   └── updater.py                           # run_protected_update orchestration
│   ├── pkgmanagers/
│   │   ├── __init__.py                          # empty
│   │   ├── base.py                              # PackageManager ABC
│   │   └── apt.py                               # APT impl
│   └── integrators/
│       ├── __init__.py                          # INTEGRATORS registry
│       ├── common.py                            # DesktopIntegrator ABC
│       ├── hyprland.py, waybar.py, kitty.py, wofi.py
└── tests/
    ├── conftest.py                              # fake HOME fixture, FakeCommandRunner
    ├── fixtures/{hyprland,waybar,kitty,wofi}/{original,updated,conflicting}/...
    ├── unit/                                    # fs, runner, config, state, detector,
    │                                            # snapshot, reconciler, validator, apt
    ├── integration/                             # full update flow w/ fakes
    ├── recovery/                                # interrupted-txn scenarios
    ├── security/                                # symlink escape, traversal, tamper, shell-ban
    └── cli/                                     # CliRunner command tests
```

Note on spec tree overlap: spec §7 lists `core/updater.py` as "PackageManager interface + APT impl" *and* §8 lists `pkgmanagers/base.py|apt.py`. Resolution (decided): adapters live in `pkgmanagers/`; `core/updater.py` holds the transaction orchestration `run_protected_update()`. No duplication.

---

### Task 1: Scaffold — packaging, docs skeletons, CI stub

**Files:** Create `pyproject.toml`, `rice/__init__.py`, all package `__init__.py`s (incl. `core/errors.py`, empty), `.gitignore`, `README.md` stub, `CLAUDE.md`, `CONTRIBUTING.md`, `ARCHITECTURE.md`, `SECURITY.md`, `TESTING.md` skeletons.

**Produces:** installable empty package; entry point `rice = "rice.cli:app"`; version `"0.1.0"` in `rice/__init__.py` (`__version__`). Docs skeletons carry the hard rules verbatim from spec §32 (CLAUDE.md), threat table §24 (SECURITY.md), test layout §26–27 (TESTING.md).

- [ ] Step 1: Write `pyproject.toml`

```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "rice-cli"
version = "0.1.0"
description = "Protect your Linux desktop rice during system updates"
requires-python = ">=3.11"
license = { text = "MIT" }
dependencies = ["typer>=0.12", "tomli-w>=1.0"]

[project.optional-dependencies]
dev = ["pytest>=8", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
rice = "rice.cli:app"

[tool.setuptools.packages.find]
include = ["rice*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B"]

[tool.mypy]
python_version = "3.11"
disallow_untyped_defs = true
warn_return_any = true
```

- [ ] Step 2: Create package dirs + `__init__.py`s; `rice/__init__.py` contains only `__version__ = "0.1.0"`.
- [ ] Step 3: Write doc skeletons (headers + rule lists from spec §24/§26/§32; content filled in Task 15).
- [ ] Step 4: Re-read files for consistency. Commit deferred to user decision.

---

### Task 2: `core/errors.py` + `core/loggingx.py`

**Files:** Create `rice/core/errors.py`, `rice/core/loggingx.py`; Test: `tests/unit/test_errors_logging.py`.

**Interfaces produced:**

```python
class RiceError(Exception):
    def __init__(self, message: str, exit_code: int = 1): ...
class UsageError(RiceError):      ...  # code 2
class ConfigError(RiceError):     ...  # code 3
class SnapshotError(RiceError):   ...  # code 4
class UpdateFailedError(RiceError): ...  # code 5
class ConflictError(RiceError):   ...  # code 6
class ValidationError_(RiceError): ...  # code 7  (name avoids clash with builtins context)
class RecoveryError(RiceError):   ...  # code 8
class SudoError(RiceError):       ...  # code 9
class ScopeViolation(RiceError):  ...  # code 1, security refusal

def setup_logging(data_dir: Path, *, verbose: bool, quiet: bool) -> logging.Handler
def redact(text: str) -> str        # masks token/password/secret key=value patterns
def log_file_summary(log: Logger, path: Path) -> None   # logs path+size+sha256[:12], never contents
```

`setup_logging`: file handler `<data_dir>/logs/rice-YYYYMMDD.log` + stderr stream handler; DEBUG if verbose else WARNING if quiet else INFO; attaches a filter that runs `redact()` on every record message.

- [ ] Step 1: Write tests: error codes match table exactly; `redact("password=hunter2")` masks value but keeps key; `log_file_summary` output contains hash not content; quiet suppresses INFO record.
- [ ] Step 2: Implement minimal classes/functions until contract met.
- [ ] Step 3: Re-read for type consistency.

---

### Task 3: `core/runner.py`

**Files:** Create `rice/core/runner.py`; Test: `tests/unit/test_runner.py`.

**Interfaces produced (spec §9):**

```python
@dataclass(frozen=True)
class RunResult:
    args: list[str]; returncode: int; stdout: str; stderr: str
    @property
    def ok(self) -> bool: return self.returncode == 0

class CommandRunner:
    def run(self, args: list[str], *, check: bool = False, timeout: float | None = None,
            env_extra: dict[str, str] | None = None) -> RunResult
    def capture(self, args: list[str], *, timeout: float | None = None) -> RunResult  # run + collect
    def privileged(self, args: list[str], *, env_extra: dict[str, str] | None = None) -> RunResult
```

Rules: single `subprocess.run(list_args, capture_output=True, text=True, shell=False)` call site in the whole codebase lives here. `privileged` prefixes `["sudo", "-n"]`? No: plain `["sudo"]` (sudo may prompt interactively for password — that's fine, it never reaches us). Env merge: `{**os.environ, **(env_extra or {})}`. `check=True` raises `RiceError(f"command failed: {args}", 1)` on non-zero.

- [ ] Step 1: Tests use a fake binary via `sys.executable -c` snippets? No subprocess allowed in tests either (keeps them fast/portable): instead subclass CommandRunner overriding `_execute` — no. Simpler: tests assert arg-construction by monkeypatching `subprocess.run` with a recorder stub returning canned RunResults. Assert: no `shell=True` kwarg ever passed; privileged prepends `["sudo"]`; env_extra merged; check=True raises.
- [ ] Step 2: Implement (~40 lines).
- [ ] Step 3: Re-read.

---

### Task 4: `core/fs.py` — Filesystem abstraction

**Files:** Create `rice/core/fs.py`; Test: `tests/unit/test_fs.py`.

**Interfaces (spec §9/§10):**

```python
@dataclass(frozen=True)
class FileMeta:
    path: str            # absolute canonical path as recorded
    type: str            # "file" | "symlink" | "dir"
    mode: int            # st_mode & 0o777
    uid: int; gid: int; size: int; mtime_ns: int
    sha256: str | None = None       # regular files only
    symlink_target: str | None = None

class Filesystem:
    def read(self, path: Path) -> bytes
    def write_atomically(self, path: Path, data: bytes) -> None
    def copy(self, src: Path, dst: Path) -> None           # copies content+mode, follows nothing
    def move(self, src: Path, dst: Path) -> None
    def remove(self, path: Path) -> None                   # caller must scope-check first
    def exists(self, path: Path) -> bool
    def is_symlink(self, path: Path) -> bool
    def readlink(self, path: Path) -> str
    def symlink(self, target: str, link: Path) -> None
    def metadata(self, path: Path) -> FileMeta             # lstat-based (never follows symlinks)
    def sha256(self, path: Path) -> str                    # streamed 64KiB chunks
    def ensure_dir(self, path: Path) -> None               # mkdir parents, exist_ok
    def free_space(self, path: Path) -> int                # shutil.disk_usage(path).free
    def walk_files(self, root: Path) -> Iterator[Path]     # recursive, does NOT follow dir symlinks

def canonicalize(path: Path) -> Path                   # os.path.realpath
def is_within(path: Path, roots: Sequence[Path]) -> bool   # realpath containment check
def require_within(path: Path, roots: Sequence[Path]) -> None  # raise ScopeViolation
```

`write_atomically`: `tempfile.mkstemp(dir=path.parent)` → write → `flush()` → `os.fsync(fd)` → close → `os.replace(tmp, path)` → fsync parent dir fd (open with `os.O_DIRECTORY`, guarded try/except). On any failure, unlink tmp in finally.

Symlink policy: `copy()` uses `shutil.copy2(src, dst, follow_symlinks=False)` for symlink args (copies link, not target); `walk_files` yields symlinks as entries without descending through them.

- [ ] Step 1: Tests (tmp_path based, pure stdlib, Windows-safe to WRITE but only run in CI): atomic overwrite replaces content; tmp file cleaned up on failure (monkeypatch os.replace to raise); sha256 matches `hashlib` reference vector; metadata round-trips mode; symlink metadata records target and type="symlink"; is_within catches `../` traversal; require_within raises ScopeViolation.
- [ ] Step 2: Implement (~120 lines).
- [ ] Step 3: Re-read.

---

### Task 5: `core/config.py`

**Files:** Create `rice/core/config.py`; Test: `tests/unit/test_config.py`.

**Interfaces:**

```python
DEFAULT_CONFIG_PATH = "~/.config/rice/config.toml"
DEFAULT_DATA_DIR = "~/.local/share/rice"

@dataclass
class RiceConfig:
    data_dir: Path                 # expanded
    protected: dict[str, list[Path]]   # app -> expanded paths ("extra" included)

def config_path(home: Path | None = None) -> Path      # home overrides ~ for tests
def load_config(home: Path | None = None) -> RiceConfig  # missing file -> ConfigError(code 3, "run rice init")
def save_config(cfg: RiceConfig, home: Path | None = None) -> None  # via Filesystem.write_atomically + tomli-w dumps
def protected_paths(cfg: RiceConfig) -> list[Path]     # flattened, deduped, order-stable
```

TOML shape exactly per spec §12 (`[rice] data_dir, version`; `[protected]` app keys incl. `extra`). Read with `tomllib`; write with `tomli_w.dumps`. All stored values keep `~/...` form on disk (portable), expanded in memory.

Tests monkeypatch HOME via the `home` param — no env mutation. Round-trip save→load equality; missing file raises ConfigError; tilde expansion works relative to injected home.

- [ ] Step 1: tests. Step 2: implement. Step 3: re-read.

---

### Task 6: `core/state.py` — journal + state machine

**Files:** Create `rice/core/state.py`; Test: `tests/unit/test_state.py`.

**Interfaces (spec §9/§17):**

```python
class TransactionState(str, Enum):
    IDLE="IDLE"; PREPARING="PREPARING"; SNAPSHOTTED="SNAPSHOTTED"; UPDATING="UPDATING";
    UPDATED="UPDATED"; RECONCILING="RECONCILING"; CONFLICT="CONFLICT"; VALIDATING="VALIDATING";
    COMMITTED="COMMITTED"; UPDATE_FAILED="UPDATE_FAILED"; RECOVERY="RECOVERY"; KNOWN_STATE="KNOWN_STATE"

ALLOWED: dict[TransactionState, frozenset[TransactionState]]  # exactly spec §17 diagram edges;
    # additionally every failure state {UPDATE_FAILED, CONFLICT} -> RECOVERY -> KNOWN_STATE;
    # COMMITTED, KNOWN_STATE are terminal (empty sets).

@dataclass
class TransactionRecord:            # spec §10
    txn_id: str; state: TransactionState; started_at: str; updated_at: str
    snapshot_id: str | None; packages: list[str]; decisions: list[dict]; error: str | None

class TransactionJournal:
    def __init__(self, fs: Filesystem, data_dir: Path): ...   # dir = data_dir/"transactions"
    def begin(self, txn_id: str) -> TransactionRecord
    def set_state(self, state: TransactionState) -> None      # validates ALLOWED; persists atomically
    def record(self, key: str, value: Any) -> None            # decisions.append / field set; persists
    def load(self) -> TransactionRecord | None                # None if no in-flight txn
    def clear(self) -> None                                   # remove journal file after COMMITTED/KNOWN_STATE
    def mark_finished_ok(self) -> None                        # -> COMMITTED then clear()
```

Journal file: `transactions/<txn_id>.json`, written via `fs.write_atomically`. `load()` returns most recent non-terminal journal (scan dir, parse latest mtime). Illegal transition raises `RecoveryError`? No — raises `ValueError`-free `RiceError("illegal transition X->Y")` code 1; callers treat as bug.

Tests: happy-path chain PREPARING→…→COMMITTED persists each step (read JSON between steps); UPDATING→UPDATE_FAILED allowed; PREPARING→COMMITTED rejected; load() reconstructs record from crafted crash file; clear removes file; idempotent double-clear OK.

- [ ] Step 1–3: tests → impl → re-read.

---

### Task 7: Integrators (`integrators/common.py` + 4 apps + registry)

**Files:** Create `rice/integrators/common.py`, `hyprland.py`, `waybar.py`, `kitty.py`, `wofi.py`, rewrite `integrators/__init__.py`; Test: `tests/unit/test_integrators.py`.

**Interfaces:**

```python
# common.py
@dataclass
class ValidationResult:
    app: str; ok: bool | None; message: str      # ok=None => manual check needed

class DesktopIntegrator(ABC):
    name: str
    def __init__(self, home: Path, runner: CommandRunner): ...
    @abstractmethod
    def detect(self) -> bool                     # marker config dir/file exists under home
    @abstractmethod
    def config_dirs(self) -> list[Path]          # protected roots (absolute, expanded)
    def validate(self, fs: Filesystem) -> ValidationResult   # default: ok=None "manual check needed"

# hyprland.py: name="hyprland", dirs=[~/.config/hypr], detect=dir exists
#   validate: if runner.capture(["hyprctl","--version"]).ok: reload attempt -> ok=bool(rc)
# waybar.py: dirs=[~/.config/waybar]; validate: which-style probe ["waybar","--help"] ok probe;
#   plus jsonc sanity: config file parses as JSON after stripping // comments (tiny regex stripper)
# kitty.py: dirs=[~/.config/kitty]; validate: ["kitty","--version"] probe; if ok try
#   ["kitty","--config",<main conf>,"--dry-run-config"]? unsupported flag -> fallback manual check
# wofi.py: dirs=[~/.config/wofi] + [~/.config/rofi] when present (CR-006 Wofi/Rofi);
#   validate: ["wofi","--version"] / ["rofi","--version"] probe, else manual check

# __init__.py
INTEGRATOR_CLASSES: list[type[DesktopIntegrator]]   # fixed order hyprland,waybar,kitty,wofi
```

Validation NEVER mutates configs (spec §20). Missing binary → `ok=None` + "manual check needed".

Fixtures: create `tests/fixtures/{app}/original/` minimal deterministic configs (hyprland.conf with monitor line @144; waybar config JSON; kitty.conf; wofi style) — used by unit + integration tests. `updated/` = same with @165 etc.; `conflicting/` = divergent variant.

- [ ] Step 1: fixtures. Step 2: tests (detect true/false vs fake home; config_dirs absolute; validator returns ok=None with FakeCommandRunner failing everything; waybar comment-strip parser handles `// c` lines). Step 3: implement. Step 4: re-read.

---

### Task 8: `core/detector.py`

**Files:** Create `rice/core/detector.py`; Test: `tests/unit/test_detector.py`.

**Interfaces:**

```python
@dataclass(frozen=True)
class Detection:
    distro_id: str | None      # from /etc/os-release ID (ubuntu/debian/...)
    version_id: str | None     # VERSION_ID
    like_id: str | None        # ID_LIKE
    desktop: str | None        # $XDG_SESSION_DESKTOP or $XDG_CURRENT_DESKTOP
    wayland: bool              # $WAYLAND_DISPLAY set

class Detector:
    def __init__(self, fs: Filesystem, home: Path, environ: Mapping[str, str]): ...
    def system(self) -> Detection                       # os-release read via fs.read (missing -> Nones)
    def candidates(self) -> list[tuple[str, list[Path]]] # [(name, dirs)] for integrators where detect()
```

Unsupported-distro handling: `update` flow warns but proceeds only if distro_id in {ubuntu, debian} or like contains debian — else ConfigError(3, "unsupported platform"). (Spec §16 conservative.)

Tests: canned os-release bytes; env dict injection; candidates reflect fake home layout; missing os-release tolerated.

---

### Task 9: `core/snapshot.py`

**Files:** Create `rice/core/snapshot.py`; Test: `tests/unit/test_snapshot.py` (+ round-trip in `tests/integration/test_snapshot_restore.py`).

**Interfaces:**

```python
RETENTION_KEEP = 10
RETENTION_DAYS = 30

@dataclass
class ManifestEntry:            # spec §10/§11
    rel_path: str               # relative to home, e.g. ".config/hypr/hyprland.conf"
    meta: FileMeta              # includes sha256, symlink_target
    backup_rel_path: str        # e.g. ".config/hypr/hyprland.conf" under files/

@dataclass
class SnapshotManifest:         # manifest.json
    timestamp: str              # UTC ISO, id format "%Y-%m-%dT%H-%M-%SZ"
    host: str; desktop: str | None
    packages_upgraded: list[str]  # empty for manual snapshots
    pinned: bool
    files: list[ManifestEntry]

class SnapshotStore:
    def __init__(self, fs: Filesystem, data_dir: Path, home: Path): ...
    def snapshots_root(self) -> Path
    def create(self, protected: list[Path], *, pinned: bool = False,
               packages: list[str] | None = None, dry_run: bool = False) -> SnapshotManifest
    def verify(self, snap_id: str) -> None                  # re-hash every backup file; mismatch -> SnapshotError(4)
    def restore(self, snap_id: str, *, dry_run: bool = False) -> list[str]  # restored rel_paths
    def list(self) -> list[SnapshotManifest]                # sorted oldest->newest
    def get(self, snap_id: str) -> SnapshotManifest         # KeyError -> SnapshotError
    def latest(self) -> SnapshotManifest | None
    def delete(self, snap_id: str, *, force_scope_check: bool = True) -> None
    def prune(self, *, dry_run: bool = False) -> list[str]  # deleted ids; keeps last 10 unpinned
                                                            # within 30 days + ALL pinned
```

create(): preflight disk space first (sum of source sizes ×1.1 margin vs `free_space(snapshots_root())` → SnapshotError(4) with required/available MB, FR-029); skip paths outside scope (`require_within` against protected roots, FR-027/SR-003); symlink whose realpath escapes scope → skipped with warning, recorded as refused (FR-028/SR-004); copy preserving structure under `files/<rel_path>`; write manifest.json + metadata.json atomically; verify() immediately after create (FR-001/002 invariant: VERIFY SNAPSHOT before UPDATE proceeds).

restore(): verify() FIRST (SR-005) → then copy-over each file with metadata (chmod/chown uid/gid/utime; chown wrapped try/except EPERM→warning); recreate symlinks (validated target within scope); never delete originals first (§21). Idempotent by construction (plain copy-over).

delete/prune: scope-check that resolved dir is under snapshots_root before any remove (SR-003). Prune rule: sort unpinned newest-first, keep first 10 AND anything newer than now−30d; delete rest; pinned never deleted.

Tests: round-trip create→mutate live file→restore→content+mode+mtime equal; verify detects tampered byte (flip one char in backup) → SnapshotError; insufficient-space abort via monkeypatched free_space; symlink escape skipped; prune keeps pinned + last 10 + fresh, deletes stale old 11th; delete refuses path outside snapshots root.

---

### Task 10: Package managers (`pkgmanagers/base.py`, `pkgmanagers/apt.py`)

**Files:** Create both; Test: `tests/unit/test_pkgmanagers.py`.

**Interfaces:**

```python
# base.py
@dataclass(frozen=True)
class UpdateResult:             # spec §10
    success: bool; exit_code: int
    upgraded: list[str]; stdout_tail: str; stderr_tail: str   # tails capped at ~4000 chars

class PackageManager(ABC):
    name: str
    @classmethod
    @abstractmethod
    def detect(cls, runner: CommandRunner) -> bool
    @abstractmethod
    def update(self, runner: CommandRunner) -> UpdateResult
    @abstractmethod
    def changed_packages(self) -> list[str]

# apt.py
class AptPackageManager(PackageManager):
    name = "apt"
    detect: runner.capture(["apt", "--version"]).ok
    update(runner):
        lock precheck: capture(["fuser", "/var/lib/dpkg/lock-frontend"]) rc==0
            -> UpdateFailedError? NO: UpdateResult(success=False, ...) with stderr msg
               "another package manager is running" (FR-032; never bypass locks)
        r1 = runner.privileged(["env", "DEBIAN_FRONTEND=noninteractive", "apt", "update"])
        if not r1.ok: return fail(r1)                      # sudo prompt-fail surfaces rc!=0 too
        r2 = runner.privileged(["env", "DEBIAN_FRONTEND=noninteractive", "apt", "upgrade", "-y"])
        success = r2.ok; upgraded parsed from r2.stdout
    changed_packages: regex ^Setting up (\S+) over stdout captured during update
```

No `--force-conf*` flags (spec §16). No apt-get. `dist-upgrade` unsupported (UsageError if ever requested). Sudo failure detection happens upstream: if r1/r2 stderr contains "sudo" + "password"/"not found" OR rc==1 with empty output → mapped to SudoError(9) by updater orchestration (single mapping point).

Tests (FakeCommandRunner scripted results): success path issues exactly two privileged calls, second ends `[..., "apt", "upgrade", "-y"]`, env var present in argv; nonzero r2 → success=False, state untouched; fuser rc==0 → immediate fail with lock message; changed_packages parses "Setting up foo (1.2)" lines; detect false when apt missing.

---

### Task 11: `core/reconciler.py`

**Files:** Create `rice/core/reconciler.py`; Test: `tests/unit/test_reconciler.py`.

**Interfaces:**

```python
class Verdict(Enum): UNCHANGED; CHANGED; MISSING_CURRENT; TYPE_CHANGED

@dataclass
class Finding:
    entry: ManifestEntry; verdict: Verdict
    unified_diff: str | None      # text files only, difflib.unified_diff, else None

@dataclass
class Resolution:
    kept_mine: int; used_new: int; unchanged: int; conflicts_resolved: int

class Reconciler:
    def __init__(self, fs: Filesystem, store: SnapshotStore, home: Path,
                 interactive: bool, confirm: Callable[[Finding], str] | None = None):
        ...
    def analyze(self, snap_id: str) -> list[Finding]        # pure read-only; feeds `diff` cmd too
    def resolve(self, snap_id: str,
                decide: DecisionCallback | None = None) -> Resolution
```

Decision rules (spec §18/§19, locked):
- UNCHANGED (sha equal) → skip.
- CHANGED → default action RESTORE MINE (copy snapshot file back with metadata).
  Interactive (no --non-interactive): prompt once per finding: `[1] keep mine [2] use new [3] diff [4] abort` (prompt shows first differing lines, §19 sample). `diff` prints unified_diff then re-prompts.
  Non-interactive: silently keep mine, append decision to journal via callback.
- MISSING_CURRENT (update deleted file) → auto restore (safe; it's ours).
- TYPE_CHANGED (file↔symlink/dir swap) → CONFLICT: cannot safely auto-decide → same prompt; non-interactive → keep-mine-with-warning.
- Abort at any prompt → raise ConflictError(6, ...) after orchestrator rolls back (orchestrator owns rollback; reconciler just raises `ConflictAborted` internal exception).

`confirm` param injects prompts for tests. `DecisionCallback = Callable[[Finding, str], str]` receiving suggested action.

Tests: unchanged skipped; changed + fake decide→keep restores bytes+mode; decide→use_new leaves current; non-interactive keeps mine without prompting; type change flags conflict; abort raises; analyze() returns diffs containing expected line fragments from fixtures.

---

### Task 12: `core/validator.py`

**Files:** Create `rice/core/validator.py`; Test: `tests/unit/test_validator.py`.

**Interface:**

```python
class Validator:
    def __init__(self, fs: Filesystem, runner: CommandRunner, home: Path): ...
    def validate_all(self, apps: list[str]) -> list[ValidationResult]
```

Delegates to each integrator's `validate(fs, runner)` (Task 7 signatures already carry runner). Aggregates; never mutates configs; missing binary → ok=None "manual check needed". Validation failure list drives updater's rollback offer (exit 7 path).

Tests: FakeCommandRunner returning ok → ok True; failing → ok False with message; unavailable → None.

---

### Task 13: `core/updater.py` — orchestration, locking, signals, recovery

**Files:** Create `rice/core/updater.py`; Test: `tests/integration/test_update_flow.py`, `tests/recovery/test_interrupted.py`.

**Interface:**

```python
class TransactionLock:                       # FR-030
    def __init__(self, data_dir: Path): ...
    def acquire(self) -> None                # flock LOCK_EX|LOCK_NB on data_dir/transaction.lock
                                             # busy -> RiceError("another rice transaction is running", 1)
    def release(self) -> None                # context manager; auto-release on crash (flock semantics)

@dataclass
class PreflightReport:
    ok: bool; problems: list[str]

def preflight(fs, cfg, det: Detector, pm: PackageManager | None, *, need_pm: bool) -> PreflightReport
    # supported distro; config present; protected paths exist; disk space (delegates store.create's own
    # check too); pm detected (when need_pm); apt lock reported as problem

def run_protected_update(*, fs, cfg, runner, home, interactive, dry_run,
                         on_decision: Callable[[dict], None] | None) -> int   # exit code
def recover_pending(journal, store, fs, *, apply: bool) -> tuple[str, bool]
    # returns (state_name, recovered_bool); apply=True performs restore-to-known-state (idempotent)
```

`run_protected_update` flow (the spec §17 machine, one branch per line):

1. `TransactionLock.acquire()` (dry_run skips lock? No — dry_run still reads; skip lock+pm, stop after analyze report).
2. Signal handlers SIGINT/SIGTERM/SIGHUP → log + raise SystemExit(130); finally-block leaves journal as-is (every transition already persisted; writes atomic ⇒ no torn state, FR-031).
3. Journal begin(txn_id=timestamp) → PREPARING.
4. Preflight; problems → journal UPDATE_FAILED? No: fail BEFORE journal-worthy mutation → mark RECOVERY→KNOWN_STATE not needed; simply clear journal + raise ConfigError/SnapshotError with report (exit 3/4).
5. `store.create(...)` → SNAPSHOTTED (snapshot_id recorded). `store.verify` inline in create.
6. UPDATING → `AptPackageManager().update(runner)`. Failure → UPDATE_FAILED (+error recorded), NO reconciliation (FR-018), raise UpdateFailedError(5) offering `rice restore <snap>` in message.
7. UPDATED → RECONCILING → `Reconciler.resolve` (decisions journaled). ConflictAborted → journal CONFLICT → rollback = `store.restore(snap)` → journal RECOVERY→KNOWN_STATE → re-raise ConflictError(6).
8. VALIDATING → `Validator.validate_all`. Any ok=False → journal RECOVERY → restore(snap) → KNOWN_STATE → warn + raise ValidationError_(7) unless interactive user declines rollback... Spec §20: offer rollback, exit 7 if unresolvable and user declines. Interactive decline → leave configs, journal KNOWN_STATE, return 7. Non-interactive → auto-rollback then 7.
9. Success → mark_finished_ok() (COMMITTED + clear). Return 0.

`recover_pending`: journal.load() non-terminal → report state; apply=True: if snapshot_id present → store.restore(id) (idempotent, SR-005 verify first) → journal RECOVERY→KNOWN_STATE→clear. Used by `status` (report only) and `doctor --fix` (apply).

Integration tests (FakeCommandRunner + tmp HOME + fixtures): 
- success end-to-end: seeded "update modifies hyprland.conf" simulated by mutating live file between snapshot and reconcile — achieved via FakeCommandRunner hook callback that mutates the file when apt upgrade runs. Assert final file = original content, exit 0, journal cleared.
- apt fails → exit 5, configs untouched, journal gone (marked failed→known-state? Spec §21 UPDATE_FAILED: leave system as-is, offer restore; journal cleared after recording UPDATE_FAILED + known state note) — assert status reports clean, restore available.
- conflict + non-interactive → keep-mine applied, decision logged, exit 0.
- validation failure (FakeRunner says hyprctl bad) + non-interactive → rollback done, exit 7, live file == snapshot content.
- second concurrent lock → RiceError code 1 (acquire twice in-process with second TransactionLock on same dir).
- recovery: hand-craft journal JSON in UPDATING with snapshot_id → recover_pending(report=True) names state; apply=True restores; running twice yields identical FS hashes (idempotency REQ-IDEMP-001).

---

### Task 14: `rice/cli.py` — Typer app, all commands, exit-code mapping

**Files:** Create `rice/cli.py`; Test: `tests/cli/test_commands.py`.

**Structure:** Single Typer app; global callback registers `--version/-v/--verbose/--no-color/--quiet/--json/--non-interactive/--dry-run` into a `Ctx` dataclass (module-level current-context object is the boring approach; Typer ctx.obj works too — use ctx.obj). Every command body wrapped by `map_errors(fn)` decorator: catches `RiceError` → print message (stderr) → `raise typer.Exit(e.exit_code)`; catches unexpected Exception → generic message + exit 1 (full trace only with --verbose). Typer's own usage errors already exit 2.

Commands (spec §5, exact):
- `init`: Detector.candidates → numbered list → prompt "protect these? [Y/n]" per-app toggles kept dead simple: confirm-all prompt + optional `-a/--all`; `--non-interactive` accepts all candidates (UR-009); `extra` prompt for comma-separated additional paths; save_config. `--json` prints resulting config.
- `status`: config-or-exit-3 (message says run `rice init`); Detection summary; protected paths; last snapshot; pending/in-flight txn via recover_pending(apply=False); honors --json (FR-033).
- `snapshot [--pin] [--dry-run]`: store.create(pinned=...) using protected paths.
- `update`: run_protected_update wiring; exit code passthrough.
- `diff [SNAPSHOT]`: Reconciler.analyze → human unified diffs or --json findings (PR-003: streams per-file, no giant buffers).
- `restore [SNAPSHOT]` (default latest; explicit id REQUIRED in --non-interactive): verify+restore; prints count.
- `doctor [--fix]`: health checks (config, protected paths exist, latest snapshot verifies, interrupted txn); --fix applies recover_pending(apply=True) + offers restore when verification fails; exit 0 healthy, 7 unfixable validation-ish issue, 8 recovery failure (FR-012).
- `snapshots list [--json]` / `snapshots show [SNAPSHOT] [--json]` / `snapshots delete SNAPSHOT [--force]` (confirm prompt unless force; explicit id mandatory in non-interactive) / `snapshots prune [--dry-run] [--json]`.
- `completion [bash|zsh|fish]`: prints Click-8 eval-source snippet: `eval "$(_RICE_COMPLETE=bash_source rice)"` (zero extra deps; documented).
- `version`: prints `rice <semver>` exit 0.

Signal handlers installed only inside update flow (Task 13), not globally.

CLI tests (Typer CliRunner, isolated fake HOME via conftest fixture that redirects config/data dirs through the `home` params — no real user dirs touched): `version` exits 0 semver regex; commands before init exit 3; init --non-interactive creates config.toml; snapshot→list shows entry; delete requires confirmation/force; status --json parses as JSON with expected keys; completion bash prints eval line; update happy path via FakeCommandRunner injection (cli builds runner through factory function `make_runner()` that tests monkeypatch).

conftest.py provides: `fake_home` (tmp dir with fixture configs copied into .config/...), `fake_runner` (scriptable FakeCommandRunner class defined HERE, reused across suites), `store`/`cfg` helpers.

---

### Task 15: Docs completion + CI workflow + final polish

**Files:** Fill `README.md`, `ARCHITECTURE.md`, `SECURITY.md`, `TESTING.md`, `CONTRIBUTING.md`, `CLAUDE.md`; add `docs/{installation,getting-started,concepts,configuration,snapshots,recovery,troubleshooting,security,architecture,development}.md` (concise, one page each); create `.github/workflows/ci.yml`.

CI (runs on push — this is where all tests actually execute):

```yaml
jobs:
  quality: ubuntu-latest; pip install -e .[dev]
    steps: ruff check . ; ruff format --check . ; mypy rice
  tests: matrix ["ubuntu-24.04", "ubuntu-latest"]; include debian-13 container job
    steps: pip install -e .[dev]; pytest tests/unit tests/cli tests/security -q
  integration: ubuntu-latest; pytest tests/integration tests/recovery -q
```

Final self-review pass against Definition of Done (spec §38) checklist; grep sweeps enforcing NFR-003/004 (`shell=True`, stray `subprocess.` outside runner, `open(` outside fs/config-stdlib-spots).

---

## Self-Review

**Spec coverage:** §5 CLI ↔ Task 14 (all 12 commands incl. snapshots subcommands, completion). §6 codes ↔ Task 2 + Task 14 mapping. §7/§9 interfaces ↔ Tasks 3,4,6,7,10 verbatim. §10 models ↔ Tasks 3(FileMeta),9(ManifestEntry/SnapshotManifest),10(UpdateResult),7(ValidationResult),6(TransactionRecord). §11 layout ↔ Task 9. §12 config ↔ Task 5. §13 discovery ↔ Task 8. §14 ownership ↔ Tasks 5/9 scope checks. §15/16 APT ↔ Task 10 (no force-conf flags, DEBIAN_FRONTEND, sudo via runner). §17 machine ↔ Tasks 6/13. §18/19 reconcile ↔ Task 11 (keep-mine default, 4-option prompt, non-interactive keep-mine, no auto semantic resolution). §20 validation ↔ Tasks 7/12. §21 recovery ↔ Tasks 9/13. §22 safety ↔ Task 4 (atomic writes, scoped remove, symlink refusal) + security tests. §23 sudo model ↔ Task 10 (single privileged site). §25 logging ↔ Task 2. §26/27 tests+fixtures ↔ every task + conftest. §28 CI ↔ Task 15. §29 packaging ↔ Task 1. §34–37 milestones ↔ task grouping (Tasks 1–6 ≈ M0, 7–9 ≈ M1, 10–14 ≈ M2, 15 ≈ M3). Gaps checked: FR-034 completion ✓ (Task 14), FR-029 space ✓ (Task 9), FR-030 lock ✓ (Task 13), FR-031 signals ✓ (Task 13), FR-032 apt-lock ✓ (Task 10), FR-033 json ✓ (Tasks 14), REQ-IDEMPOTENT recovery ✓ (Task 13 test).

**Placeholder scan:** none — every task has concrete interfaces, decision rules, or test contracts; behavior details defer to cited spec sections, which is intentional (spec is normative, not a placeholder).

**Type consistency:** `Filesystem`/`CommandRunner` instances threaded explicitly (no globals); `RunResult.ok`, `FileMeta.sha256`, `SnapshotManifest.files: list[ManifestEntry]`, `Resolution` fields, `recover_pending` tuple — cross-checked consistent across Tasks 9↔11↔13↔14. `ValidationError_` naming noted to avoid shadowing.

## Execution Notes (constraints from user)

- **Never execute rice code/tests/tooling on Windows.** No `pip install`, no `pytest`, no compile. Verification story: careful cross-reads locally + green CI after push + user's manual Linux testing.
- No pushes. Repo handed over ready-to-push; remote added when user shares the GitHub URL.
