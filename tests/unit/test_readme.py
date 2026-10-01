"""The README's result tables come from saved runs: never edited by hand, never stale."""

from evals.readme_tables import README, load, render, replace_block


def test_readme_results_block_matches_the_saved_runs() -> None:
    text = README.read_text(encoding="utf-8")

    assert replace_block(text, render(load())) == text, (
        "README.md is out of date: run `uv run python -m evals.readme_tables --write`"
    )


def test_the_readme_reports_complete_runs_of_the_final_configuration() -> None:
    data = load()
    final, dev = data["agent_test"]["config"], data["agent_dev"]["config"]

    assert final["split"] == "test" and dev["split"] == "dev"
    for name in ("agent_test", "agent_dev", "agent_dev_dense", "agent_dev_bm25"):
        config = data[name]["config"]
        assert not config["partial"], f"{name} is a partial run"
        assert config["agent_prompt"] == final["agent_prompt"]
        assert config["judge_model"] == final["judge_model"]
    assert dev["retrieval_mode"] == final["retrieval_mode"] == "hybrid"
    assert data["agent_dev_dense"]["config"]["retrieval_mode"] == "dense"
    assert data["agent_dev_bm25"]["config"]["retrieval_mode"] == "bm25"
    assert data["retrieval_dev"]["config"]["split"] == "dev"
    assert data["retrieval_test"]["config"]["split"] == "test"
