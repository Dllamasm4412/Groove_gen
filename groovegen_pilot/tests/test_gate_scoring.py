from __future__ import annotations

from itertools import combinations

from gate_widget.scoring import (
    compute_all,
    compute_bradley_terry,
    compute_confidence,
    compute_rank_order,
)

FAMILIES = ["calm", "lofi", "latin", "rock", "hiphop"]


def _cmp(family_a: str, family_b: str, chosen: str, idx: int) -> dict:
    return {
        "pair_index": idx,
        "family_a": family_a,
        "family_b": family_b,
        "chosen": chosen,
        "timestamp": f"2026-09-09T12:00:{idx:02d}+00:00",
    }


def test_bt_recovers_true_ranking() -> None:
    comparisons: list[dict] = []
    idx = 0

    # calm beats every other family whenever compared.
    for other in ["lofi", "latin", "rock", "hiphop"]:
        comparisons.append(_cmp("calm", other, "a", idx))
        idx += 1

    # Fill remaining pair outcomes deterministically.
    others = ["lofi", "latin", "rock", "hiphop"]
    for a, b in combinations(others, 2):
        comparisons.append(_cmp(a, b, "a", idx))
        idx += 1

    bt_scores = compute_bradley_terry(comparisons, FAMILIES)
    rank = compute_rank_order(bt_scores)
    assert rank[0] == "calm"


def test_bt_handles_sweep() -> None:
    comparisons: list[dict] = []
    families = ["a", "b", "c", "d", "e"]

    for idx, (x, y) in enumerate(combinations(families, 2)):
        if "e" in (x, y):
            chosen = "a" if x == "e" else "b"
        else:
            chosen = "a"
        comparisons.append(_cmp(x, y, chosen, idx))

    bt_scores = compute_bradley_terry(comparisons, families)
    rank = compute_rank_order(bt_scores)

    assert rank[0] == "e"
    assert all(abs(v) < 1e6 for v in bt_scores.values())


def test_bt_handles_uniform() -> None:
    families = ["a", "b", "c", "d", "e"]
    idx_map = {fam: i for i, fam in enumerate(families)}
    comparisons: list[dict] = []

    # Regular tournament on 5 nodes: each family beats next two modulo 5.
    for idx, (x, y) in enumerate(combinations(families, 2)):
        ix = idx_map[x]
        iy = idx_map[y]
        if (iy - ix) % 5 in (1, 2):
            chosen = "a"
        else:
            chosen = "b"
        comparisons.append(_cmp(x, y, chosen, idx))

    bt_scores = compute_bradley_terry(comparisons, families)
    for fam in families:
        assert abs(bt_scores[fam] - 0.20) <= 0.05


def test_confidence_all_decisive() -> None:
    comparisons: list[dict] = []
    for idx, (x, y) in enumerate(combinations(FAMILIES, 2)):
        comparisons.append(_cmp(x, y, "a", idx))
    assert compute_confidence(comparisons, FAMILIES) == 1.0


def test_confidence_returns_zero_when_no_comparisons() -> None:
    assert compute_confidence([], FAMILIES) == 0.0


def test_compute_all_veto_reduces_admissible() -> None:
    families = ["a", "b", "c", "d", "e"]
    result = compute_all([], families, ["a", "c"])
    assert result["admissible_families"] == ["b", "d", "e"]
    assert result["primary_family_block_a"] == "b"
    assert result["primary_family_block_b"] == "d"


def test_compute_all_warns_when_one_admissible() -> None:
    families = ["a", "b", "c", "d", "e"]
    result = compute_all([], families, ["b", "c", "d", "e"])
    assert result["warning"] == "insufficient_admissible_families"
    assert result["primary_family_block_a"] is None
    assert result["primary_family_block_b"] is None
