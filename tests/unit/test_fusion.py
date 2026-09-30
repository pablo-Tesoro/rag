import pytest

from bank_assistant.retrieval.fusion import reciprocal_rank_fusion


def test_scores_follow_the_rrf_formula() -> None:
    fused = dict(reciprocal_rank_fusion([["a", "b"], ["b", "c"]], k=60))

    assert fused["a"] == pytest.approx(1 / 61)
    assert fused["b"] == pytest.approx(1 / 62 + 1 / 61)
    assert fused["c"] == pytest.approx(1 / 62)


def test_agreement_between_lists_beats_a_single_top_position() -> None:
    ranking = [item for item, _ in reciprocal_rank_fusion([["a", "b"], ["b", "c"]])]

    assert ranking == ["b", "a", "c"]


def test_ties_are_broken_deterministically() -> None:
    # "x" and "y" have the same score and the same best rank: fall back to the id.
    first = reciprocal_rank_fusion([["y"], ["x"]])
    second = reciprocal_rank_fusion([["x"], ["y"]])

    assert [item for item, _ in first] == [item for item, _ in second] == ["x", "y"]


def test_empty_rankings_fuse_to_nothing() -> None:
    assert reciprocal_rank_fusion([[], []]) == []


def test_k_must_be_positive() -> None:
    with pytest.raises(ValueError):
        reciprocal_rank_fusion([["a"]], k=0)
