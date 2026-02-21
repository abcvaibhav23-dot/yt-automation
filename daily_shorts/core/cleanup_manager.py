"""Post-run cleanup utilities for generated artifacts."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, Optional

from config.settings import CACHE_DIR, FINAL_DIR, LOG_DIR, OUTPUT_DIR


@dataclass
class CleanupReport:
    removed_files: int = 0
    removed_dirs: int = 0


def _safe_unlink(path: Path, report: CleanupReport) -> None:
    if path.exists() and path.is_file():
        path.unlink(missing_ok=True)
        report.removed_files += 1


def _remove_empty_dirs(root: Path, report: CleanupReport) -> None:
    if not root.exists():
        return
    for d in sorted([p for p in root.rglob("*") if p.is_dir()], reverse=True):
        try:
            if not any(d.iterdir()):
                d.rmdir()
                report.removed_dirs += 1
        except OSError:
            continue


def _cleanup_output_dir(report: CleanupReport) -> None:
    if not OUTPUT_DIR.exists():
        return
    for p in OUTPUT_DIR.glob("*"):
        if p.is_file() and p.name != ".gitkeep":
            _safe_unlink(p, report)


def _cleanup_logs(max_keep: int, report: CleanupReport) -> None:
    if not LOG_DIR.exists():
        return
    logs = sorted([p for p in LOG_DIR.glob("run_*.log") if p.is_file()], key=lambda x: x.stat().st_mtime, reverse=True)
    for p in logs[max_keep:]:
        _safe_unlink(p, report)


def _cleanup_final_runs(channel: str, keep_runs: int, keep_current: Optional[Path], report: CleanupReport) -> None:
    if not FINAL_DIR.exists():
        return
    prefix = f"{channel}_"
    bundles = [d for d in FINAL_DIR.iterdir() if d.is_dir() and d.name.startswith(prefix)]
    bundles.sort(key=lambda x: x.stat().st_mtime, reverse=True)

    keep_set = set()
    if keep_current is not None:
        keep_set.add(keep_current.resolve())

    for b in bundles:
        if len(keep_set) >= keep_runs:
            break
        keep_set.add(b.resolve())

    for b in bundles:
        if b.resolve() in keep_set:
            continue
        for f in b.rglob("*"):
            if f.is_file():
                _safe_unlink(f, report)
        for d in sorted([x for x in b.rglob("*") if x.is_dir()], reverse=True):
            try:
                d.rmdir()
                report.removed_dirs += 1
            except OSError:
                pass
        try:
            b.rmdir()
            report.removed_dirs += 1
        except OSError:
            pass


def _cleanup_cache(max_age_days: int, report: CleanupReport) -> None:
    if not CACHE_DIR.exists():
        return
    cutoff = datetime.utcnow() - timedelta(days=max_age_days)
    for p in CACHE_DIR.glob("*"):
        if not p.is_file() or p.name == ".gitkeep":
            continue
        mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
        if mtime < cutoff:
            _safe_unlink(p, report)


def _cleanup_cache_from_previous_runs(run_started_at: datetime, report: CleanupReport) -> None:
    if not CACHE_DIR.exists():
        return
    for p in CACHE_DIR.glob("*"):
        if not p.is_file() or p.name == ".gitkeep":
            continue
        mtime = datetime.utcfromtimestamp(p.stat().st_mtime)
        if mtime < run_started_at:
            _safe_unlink(p, report)


def _cleanup_junk_files(root: Path, report: CleanupReport) -> None:
    for pattern in ("**/.DS_Store", "**/*.tmp", "**/*.temp"):
        for p in root.glob(pattern):
            if p.is_file():
                _safe_unlink(p, report)


def perform_post_run_cleanup(
    *,
    channel: str,
    keep_runs_per_channel: int = 2,
    keep_log_files: int = 20,
    cache_max_age_days: int = 7,
    clean_cache_by_run: bool = True,
    run_started_at: Optional[datetime] = None,
    keep_current_bundle: Optional[Path] = None,
) -> CleanupReport:
    report = CleanupReport()
    _cleanup_output_dir(report)
    _cleanup_logs(max_keep=max(1, keep_log_files), report=report)
    _cleanup_final_runs(
        channel=channel,
        keep_runs=max(1, keep_runs_per_channel),
        keep_current=keep_current_bundle,
        report=report,
    )
    if clean_cache_by_run and run_started_at is not None:
        _cleanup_cache_from_previous_runs(run_started_at=run_started_at, report=report)
    else:
        _cleanup_cache(max_age_days=max(1, cache_max_age_days), report=report)
    _cleanup_junk_files(Path(__file__).resolve().parents[1], report)
    _remove_empty_dirs(OUTPUT_DIR, report)
    _remove_empty_dirs(CACHE_DIR, report)
    return report
