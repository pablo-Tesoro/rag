"""Provenance of evaluation runs: the commit and whether the tree had changes."""

import subprocess
from pathlib import Path

from evals.runinfo import git_commit


def _git(root: Path, *args: str) -> None:
    # Fixed command and arguments from this test only.
    subprocess.run(["git", *args], cwd=root, check=True, capture_output=True)  # noqa: S603, S607


def test_saved_results_do_not_make_the_tree_dirty_but_other_changes_do(tmp_path: Path) -> None:
    _git(tmp_path, "init", "-q")
    (tmp_path / "code.py").write_text("x = 1\n")
    _git(tmp_path, "add", ".")
    _git(tmp_path, "-c", "user.email=t@example.com", "-c", "user.name=t", "commit", "-qm", "init")
    clean = git_commit(tmp_path)

    (tmp_path / "evals" / "results").mkdir(parents=True)
    (tmp_path / "evals" / "results" / "run.json").write_text("{}")
    assert git_commit(tmp_path) == clean  # the harness's own output

    (tmp_path / "code.py").write_text("x = 2\n")
    assert git_commit(tmp_path) == f"{clean}-dirty"
