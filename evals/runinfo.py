"""Provenance recorded with every evaluation run, so each number can be traced back."""

import hashlib
import subprocess
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = REPO_ROOT / "evals" / "results"


def git_commit(root: Path = REPO_ROOT) -> str:
    """Current commit, suffixed with "-dirty" if there are uncommitted changes.

    Results written to evals/results/ do not count: they are the harness's own output, and a
    run started right after another one would otherwise be marked dirty by its results."""
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],  # noqa: S607 - fixed command
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain", "--", ".", ":(exclude)evals/results"],  # noqa: S607
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{sha}-dirty" if dirty else sha


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def run_id(prefix: str) -> str:
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}_{prefix}"
