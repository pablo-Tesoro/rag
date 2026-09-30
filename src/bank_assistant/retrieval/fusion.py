"""Reciprocal Rank Fusion (Cormack, Clarke & Büttcher, 2009).

score(d) = Σ_rankings 1 / (k + rank(d))

It fuses rankings using only positions, so the very different score scales of BM25
(unbounded) and cosine similarity ([-1, 1]) never have to be normalised against each other.
k = 60 is the value from the paper; larger k flattens the advantage of the top positions.
"""

from collections import defaultdict
from collections.abc import Sequence


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[str]], k: int = 60
) -> list[tuple[str, float]]:
    """Fuse ranked lists of ids (best first). Returns (id, score), best first.

    Ties are broken by the best individual rank, then by id, so the output is deterministic.
    """
    if k <= 0:
        raise ValueError("k must be positive")
    scores: dict[str, float] = defaultdict(float)
    best_rank: dict[str, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] += 1.0 / (k + rank)
            best_rank[item] = min(best_rank.get(item, rank), rank)
    return sorted(scores.items(), key=lambda pair: (-pair[1], best_rank[pair[0]], pair[0]))
