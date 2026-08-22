"""rice CLI (Typer). Every command routes failures through `safe`, which maps
RiceError.exit_code onto the process exit code (spec §6).

Test hook: `_HOME_OVERRIDE` lets the suite redirect $HOME without env games;
production always uses Path.home().
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar

import typer

from rice import __version__
from rice.core.config import RiceConfig, load_config, protected_paths, save_config
from rice.core.detector import Detector
from rice.core.errors import RecoveryError, RiceError, UsageError, ValidationError_
from rice.core.fs import Filesystem
from rice.core.loggingx import setup_logging
from rice.core.runner import CommandRunner
from rice.core.snapshot import SnapshotStore
from rice.core.state import TransactionJournal
from rice.core.updater import recover_pending

app = typer.Typer(
    name="rice",
    help="Protect your Linux desktop config during system updates.",
    no_args_is_help=True,
    add_completion=True,
)
snapshots_app = typer.Typer(help="Manage snapshots.", no_args_is_help=True)
app.add_typer(snapshots_app, name="snapshots")

_HOME_OVERRIDE: Path | None = None

F = TypeVar("F", bound=Callable[..., Any])


def safe(fn: F) -> F:
    """Map RiceError -> message on stderr + its exit code."""

    @wraps(fn)
    def inner(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except RiceError as exc:
            typer.echo(f"error: {exc.message}", err=True)
            raise typer.Exit(exc.exit_code) from exc

    return inner  # type: ignore[return-value]


@dataclass
class Ctx:
    verbose: bool = False
    quiet: bool = False
    json_out: bool = False
    non_interactive: bool = False
    dry_run: bool = False


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"rice {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit.",
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Debug output."),
    no_color: bool = typer.Option(False, "--no-color", help="Disable colored output."),
    quiet: bool = typer.Option(False, "--quiet", help="Warnings/errors only."),
    json_out: bool = typer.Option(False, "--json", help="Machine-readable output."),
    non_interactive: bool = typer.Option(
        False, "--non-interactive", help="No prompts; default safe actions."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Simulate without mutating."),
) -> None:
    ctx.obj = Ctx(
        verbose=verbose,
        quiet=quiet,
        json_out=json_out,
        non_interactive=non_interactive,
        dry_run=dry_run,
    )
    # Wire logging (spec §25). Config's data_dir when present, else the
    # default location; without a config there is simply no file handler.
    try:
        data_dir = load_config(_fs(), home=_home()).data_dir
    except RiceError:
        data_dir = _home() / ".local/share/rice"
    setup_logging(data_dir, verbose=verbose, quiet=quiet)


# ---- bootstrap helpers -------------------------------------------------------


def _home() -> Path:
    return _HOME_OVERRIDE or Path.home()


def _fs() -> Filesystem:
    return Filesystem()


def _detector() -> Detector:
    return Detector(_fs(), _home(), CommandRunner())


def _load_cfg() -> RiceConfig:
    return load_config(_fs(), home=_home())


def _store(cfg: RiceConfig) -> SnapshotStore:
    return SnapshotStore(_fs(), cfg.data_dir, _home())


def _echo_json(payload: Any) -> None:
    typer.echo(json.dumps(payload, indent=2, sort_keys=True))


def _confirm(prompt: str, ctx: Ctx, *, default_yes: bool = True) -> bool:
    if ctx.non_interactive:
        return default_yes
    answer = typer.confirm(prompt, default=default_yes)
    return bool(answer)


# ---- commands ----------------------------------------------------------------


@app.command()
@safe
def init(ctx: typer.Context) -> None:
    """Discover candidate configs and persist what to protect."""
    c: Ctx = ctx.obj
    det = _detector()
    detected = det.candidates()

    protected: dict[str, list[Path]] = {}
    if detected:
        typer.echo("Detected configurations:")
        for name, dirs in detected:
            for d in dirs:
                typer.echo(f"  {name:<10} {d}")
        if _confirm("Protect all detected configs?", c):
            protected.update(detected)
        elif not c.non_interactive:
            raw = typer.prompt("Numbers to EXCLUDE (comma-separated, blank=none)", default="")
            exclude = {s.strip() for s in raw.split(",") if s.strip()}
            for i, (name, dirs) in enumerate(detected, start=1):
                if str(i) not in exclude:
                    protected[name] = dirs

    extra: list[Path] = []
    if not c.non_interactive:
        raw = typer.prompt("Additional paths to protect (comma-separated, blank=none)", default="")
        for part in (s.strip() for s in raw.split(",") if s.strip()):
            p = Path(part).expanduser()
            if not p.is_absolute():
                p = _home() / p
            resolved = p.resolve()
            if not resolved.is_relative_to(_home().resolve()):
                raise UsageError(f"refusing extra path outside home: {resolved}")
            extra.append(resolved)
    if extra:
        protected["extra"] = extra

    cfg = RiceConfig(data_dir=_home() / ".local/share/rice", protected=protected)
    path = save_config(cfg, _fs(), home=_home())
    typer.echo(f"Saved {path}")
    if c.json_out:
        _echo_json(
            {
                "protected": {k: [str(p) for p in v] for k, v in protected.items()},
                "data_dir": str(cfg.data_dir),
            }
        )


@app.command()
@safe
def status(ctx: typer.Context) -> None:
    """Show detected system, protected configs, last snapshot/update."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    det = _detector()
    d = det.system()
    store = _store(cfg)
    latest = store.latest()

    pending = TransactionJournal(_fs(), cfg.data_dir).load()

    payload: dict[str, Any] = {
        "distro": {"id": d.distro_id, "version": d.version_id, "supported": d.supported},
        "desktop": d.desktop,
        "wayland": d.wayland,
        "data_dir": str(cfg.data_dir),
        "protected": {k: [str(p) for p in v] for k, v in sorted(cfg.protected.items())},
        "last_snapshot": (
            {"id": latest.timestamp, "files": len(latest.files), "pinned": latest.pinned}
            if latest
            else None
        ),
        "pending_transaction": (
            {"state": pending.state.value, "txn_id": pending.txn_id} if pending else None
        ),
    }
    if c.json_out:
        _echo_json(payload)
        return
    distro = payload["distro"]
    typer.echo(
        f"System: {distro['id'] or 'unknown'} {distro['version'] or ''}"
        f"{'' if distro['supported'] else ' (unsupported)'}"
    )
    typer.echo(f"Desktop: {d.desktop or 'unknown'}{' (Wayland)' if d.wayland else ''}")
    total = sum(len(v) for v in cfg.protected.values())
    typer.echo(f"Protected apps: {len(cfg.protected)} ({total} roots)")
    if latest:
        typer.echo(f"Last snapshot: {latest.timestamp} ({len(latest.files)} files)")
    else:
        typer.echo("Last snapshot: none")
    if pending:
        typer.echo(
            f"[!] Interrupted transaction {pending.txn_id} in state "
            f"{pending.state.value}; run 'rice doctor'"
        )


@app.command()
@safe
def snapshot(
    ctx: typer.Context,
    pin: bool = typer.Option(False, "--pin", help="Keep this snapshot forever."),
) -> None:
    """Manually snapshot protected configs."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    store = _store(cfg)
    det = _detector()
    manifest = store.create(
        protected_paths(cfg),
        pinned=pin,
        desktop=det.system().desktop,
        dry_run=c.dry_run,
    )
    if c.dry_run:
        typer.echo(f"Dry run: would snapshot {len(manifest.files)} files.")
    else:
        typer.echo(
            f"Snapshot {manifest.timestamp}: {len(manifest.files)} files"
            f"{' [pinned]' if pin else ''}"
        )


@app.command()
@safe
def restore(
    ctx: typer.Context,
    snap_id: str | None = typer.Argument(None, help="Snapshot id (default: latest)."),
) -> None:
    """Restore configs from a snapshot (verifies integrity first)."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    store = _store(cfg)
    if snap_id is None and c.non_interactive:
        raise UsageError("snapshot id required in --non-interactive mode")
    resolved = store.resolve_id(snap_id)
    if snap_id is None and not _confirm(f"Restore latest snapshot {resolved}?", c):
        raise typer.Abort()
    restored = store.restore(resolved, dry_run=c.dry_run)
    verb = "Would restore" if c.dry_run else "Restored"
    typer.echo(f"{verb} {len(restored)} files from {resolved}")


@snapshots_app.command("list")
@safe
def snapshots_list(ctx: typer.Context) -> None:
    """List all snapshots."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    snaps = _store(cfg).list_all()
    if c.json_out:
        _echo_json([{"id": m.timestamp, "files": len(m.files), "pinned": m.pinned} for m in snaps])
        return
    if not snaps:
        typer.echo("No snapshots.")
        return
    for m in snaps:
        typer.echo(f"{m.timestamp}  files={len(m.files):<4} {'pinned' if m.pinned else ''}")


@snapshots_app.command("show")
@safe
def snapshots_show(
    ctx: typer.Context,
    snap_id: str | None = typer.Argument(None, help="Snapshot id (default: latest)."),
) -> None:
    """Show one snapshot's manifest."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    store = _store(cfg)
    resolved = store.resolve_id(snap_id)
    manifest = store.get(resolved)
    if c.json_out:
        _echo_json(manifest.to_json())
        return
    typer.echo(
        f"Snapshot {manifest.timestamp} host={manifest.host} "
        f"desktop={manifest.desktop or '?'} pinned={manifest.pinned}"
    )
    typer.echo(f"Packages upgraded: {', '.join(manifest.packages_upgraded) or '(manual snapshot)'}")
    for e in manifest.files:
        kind = e.meta.type
        typer.echo(f"  [{kind:<7}] {e.rel_path}")


@snapshots_app.command("delete")
@safe
def snapshots_delete(
    ctx: typer.Context,
    snap_id: str = typer.Argument(..., help="Snapshot id (required)."),
    force: bool = typer.Option(False, "--force", help="Skip confirmation."),
) -> None:
    """Delete a snapshot after confirmation."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    if not force:
        if c.non_interactive:
            raise UsageError("--force required in --non-interactive mode")
        typer.confirm(f"Delete snapshot {snap_id}?", abort=True)
    _store(cfg).delete(snap_id)
    typer.echo(f"Deleted {snap_id}")


@snapshots_app.command("prune")
@safe
def snapshots_prune(ctx: typer.Context) -> None:
    """Prune per retention policy (keep last 10, 30 days, pinned)."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    doomed = _store(cfg).prune(dry_run=c.dry_run)
    verb = "Would delete" if c.dry_run else "Deleted"
    if c.json_out:
        _echo_json({"deleted": doomed})
    elif doomed:
        for sid in doomed:
            typer.echo(f"{verb} {sid}")
    else:
        typer.echo("Nothing to prune.")


COMPLETION_SNIPPETS = {
    "bash": 'eval "$(_RICE_COMPLETE=bash_source rice)"',
    "zsh": 'eval "$(_RICE_COMPLETE=zsh_source rice)"',
    "fish": "_RICE_COMPLETE=fish_source rice | source",
}


@app.command()
@safe
def update(ctx: typer.Context) -> None:
    """Full protected update: snapshot -> apt upgrade -> reconcile -> validate."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    from rice.core.reconciler import Action, Finding
    from rice.core.updater import run_protected_update

    def prompt_conflict(finding: Finding) -> Action:
        rel = finding.entry.rel_path
        typer.echo(f"\n[!] Conflict in ~/{rel} ({finding.verdict.value})")
        if finding.unified_diff:
            lines = finding.unified_diff.splitlines()
            shown = lines if len(lines) <= 30 else lines[:30] + ["... (truncated)"]
            for line in shown:
                typer.echo(f"    {line}")
            typer.echo("")
        while True:
            raw = typer.prompt("[1] keep mine  [2] use new  [3] diff  [4] abort", default="1")
            if raw.strip() == "1":
                return Action.KEEP_MINE
            if raw.strip() == "2":
                return Action.USE_NEW
            if raw.strip() == "3":
                if finding.unified_diff:
                    typer.echo(finding.unified_diff)
                else:
                    typer.echo("(binary file: no textual diff)")
                continue
            if raw.strip() == "4":
                return Action.ABORT
            typer.echo("choose 1-4", err=True)

    def ask_rollback(failures: list) -> bool:
        names = ", ".join(r.app for r in failures)
        return typer.confirm(
            f"Validation failed for {names}. Roll back to the pre-update snapshot?",
            default=True,
        )

    code = run_protected_update(
        fs=_fs(),
        cfg=cfg,
        runner=CommandRunner(),
        home=_home(),
        interactive=not c.non_interactive,
        dry_run=c.dry_run,
        decide=None if c.non_interactive else prompt_conflict,
        ask_rollback=None if c.non_interactive else ask_rollback,
    )
    raise typer.Exit(code)


@app.command()
@safe
def diff(
    ctx: typer.Context,
    snap_id: str | None = typer.Argument(None, help="Snapshot id (default: latest)."),
) -> None:
    """Show diffs between a snapshot and current configs."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    store = _store(cfg)
    resolved = store.resolve_id(snap_id)

    from rice.core.reconciler import Reconciler, Verdict

    findings = Reconciler(_fs(), store).analyze(resolved)
    interesting = [f for f in findings if f.verdict is not Verdict.UNCHANGED]

    if c.json_out:
        _echo_json(
            {
                "snapshot": resolved,
                "findings": [
                    {"path": f.entry.rel_path, "verdict": f.verdict.value} for f in interesting
                ],
            }
        )
        return

    typer.echo(f"Comparing snapshot {resolved}: {len(interesting)} difference(s)")
    for f in interesting:
        typer.echo(f"\n=== ~/{f.entry.rel_path} [{f.verdict.value}]")
        if f.unified_diff:
            typer.echo(f.unified_diff.rstrip())
        elif f.verdict is Verdict.TYPE_CHANGED:
            typer.echo(f"(type changed: snapshot={f.entry.meta.type})")
        else:
            typer.echo("(file is missing in current config)")


@app.command()
@safe
def doctor(
    ctx: typer.Context,
    fix: bool = typer.Option(False, "--fix", help="Attempt auto-fix where possible."),
) -> None:
    """Check rice health; optionally recover an interrupted transaction."""
    c: Ctx = ctx.obj
    cfg = _load_cfg()
    fs = _fs()
    store = _store(cfg)
    journal = TransactionJournal(fs, cfg.data_dir)

    checks: list[dict[str, Any]] = []

    roots = protected_paths(cfg)
    missing_roots = [p for p in roots if not p.exists()]
    checks.append(
        {
            "name": "protected-paths",
            "ok": len(missing_roots) == 0,
            "message": f"{len(roots) - len(missing_roots)}/{len(roots)} present",
        }
    )

    latest = store.latest()
    snap_ok = True
    snap_msg = "no snapshots yet"
    if latest is not None:
        try:
            store.verify(latest.timestamp)
            snap_ok, snap_msg = True, f"{latest.timestamp} verified"
        except RiceError as exc:
            snap_ok, snap_msg = False, str(exc)
    checks.append({"name": "last-snapshot-integrity", "ok": snap_ok, "message": snap_msg})

    pending = journal.load()
    txn_state = pending.state.value if pending else None
    checks.append(
        {
            "name": "pending-transaction",
            "ok": pending is None,
            "message": f"state={txn_state}" if pending else "none",
        }
    )

    recovered: list[str] = []
    if fix and pending is not None:
        try:
            _state, done = recover_pending(journal, store, apply=True)
        except RiceError as exc:
            raise RecoveryError(f"could not recover transaction: {exc.message}") from exc
        if done:
            recovered.append(txn_state or "?")
            checks[-1] = {
                "name": "pending-transaction",
                "ok": True,
                "message": f"recovered (was {txn_state})",
            }

    if c.json_out:
        _echo_json({"checks": checks, "fixed": recovered})
    else:
        for check in checks:
            mark = "ok" if check["ok"] else "!!"
            typer.echo(f"[{mark}] {check['name']}: {check['message']}")
        if recovered:
            typer.echo(f"Recovered {len(recovered)} interrupted transaction(s).")

    unresolved = [ch for ch in checks if not ch["ok"]]
    if unresolved:
        raise ValidationError_("; ".join(f"{ch['name']}: {ch['message']}" for ch in unresolved))


@app.command()
@safe
def completion(
    shell: str = typer.Argument(..., help="bash, zsh, or fish"),
) -> None:
    """Print shell completion setup (add to your shell rc file)."""
    snippet = COMPLETION_SNIPPETS.get(shell)
    if snippet is None:
        raise UsageError(f"unknown shell '{shell}': expected bash, zsh, or fish")
    typer.echo(f"# rice completion for {shell}")
    typer.echo(snippet)


if __name__ == "__main__":
    app()
