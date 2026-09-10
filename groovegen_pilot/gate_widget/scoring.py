from __future__ import annotations

import numpy as np
from scipy.optimize import minimize


def compute_bradley_terry(comparisons: list[dict], families: list[str]) -> dict[str, float]:
    """Fit Bradley-Terry model via MLE on pairwise wins.

    Uses scipy.optimize.minimize on negative log-likelihood with L2
    regularization (lambda=0.01) and adds 0.5 pseudo-wins in each direction
    for every family pair. Returns normalized positive scores summing to 1.0.
    """
    if not families:
        return {}

    family_to_idx = {fam: i for i, fam in enumerate(families)}
    n = len(families)

    wins = np.zeros((n, n), dtype=float)

    # Laplace-like pseudo-wins: 0.5 each direction for every unordered pair.
    for i in range(n):
        for j in range(i + 1, n):
            wins[i, j] += 0.5
            wins[j, i] += 0.5

    for row in comparisons:
        fam_a = row.get("family_a")
        fam_b = row.get("family_b")
        chosen = row.get("chosen")
        if fam_a not in family_to_idx or fam_b not in family_to_idx:
            continue
        if chosen not in ("a", "b"):
            continue

        i = family_to_idx[fam_a]
        j = family_to_idx[fam_b]
        if i == j:
            continue
        if chosen == "a":
            wins[i, j] += 1.0
        else:
            wins[j, i] += 1.0

    if n == 1:
        return {families[0]: 1.0}

    l2_lambda = 0.01

    def objective(theta_free: np.ndarray) -> float:
        theta = np.concatenate([theta_free, np.array([0.0])])
        nll = 0.0
        for i in range(n):
            for j in range(i + 1, n):
                w_ij = wins[i, j]
                w_ji = wins[j, i]
                if w_ij <= 0.0 and w_ji <= 0.0:
                    continue

                # log p(i beats j) and log p(j beats i), stable form.
                log_denom = np.logaddexp(theta[i], theta[j])
                log_p_ij = theta[i] - log_denom
                log_p_ji = theta[j] - log_denom
                nll -= w_ij * log_p_ij + w_ji * log_p_ji

        nll += l2_lambda * float(np.dot(theta, theta))
        return float(nll)

    x0 = np.zeros(n - 1, dtype=float)
    res = minimize(objective, x0, method="L-BFGS-B")

    theta_hat = (
        np.concatenate([res.x, np.array([0.0])]) if res.success else np.zeros(n, dtype=float)
    )
    # Convert abilities to probabilities via softmax.
    shifted = theta_hat - np.max(theta_hat)
    exps = np.exp(shifted)
    probs = exps / np.sum(exps)

    return {fam: float(probs[family_to_idx[fam]]) for fam in families}


def compute_rank_order(bt_scores: dict[str, float]) -> list[str]:
    """Families sorted by score descending. Ties broken alphabetically (stable)."""
    return [
        fam
        for fam, _ in sorted(
            bt_scores.items(),
            key=lambda kv: (-kv[1], kv[0]),
        )
    ]


def compute_confidence(comparisons: list[dict], families: list[str]) -> float:
    """Mean pairwise margin across all family pairs seen in comparisons."""
    _ = families

    pair_wins: dict[tuple[str, str], dict[str, int]] = {}

    for row in comparisons:
        fam_a = row.get("family_a")
        fam_b = row.get("family_b")
        chosen = row.get("chosen")
        if not fam_a or not fam_b or fam_a == fam_b:
            continue
        if chosen not in ("a", "b"):
            continue

        p, q = sorted((fam_a, fam_b))
        rec = pair_wins.setdefault((p, q), {p: 0, q: 0})
        winner = fam_a if chosen == "a" else fam_b
        rec[winner] += 1

    if not pair_wins:
        return 0.0

    margins: list[float] = []
    for (p, q), rec in pair_wins.items():
        wins_p = rec[p]
        wins_q = rec[q]
        total = wins_p + wins_q
        if total == 0:
            continue
        margins.append(abs(wins_p - wins_q) / total)

    if not margins:
        return 0.0
    return float(sum(margins) / len(margins))


def compute_all(comparisons: list[dict], families: list[str], vetoes: list[str]) -> dict:
    """Compute profile-facing gate outputs from comparisons and vetoes."""
    bt_scores = compute_bradley_terry(comparisons, families)
    rank_order = compute_rank_order(bt_scores)
    confidence = compute_confidence(comparisons, families)

    veto_set = set(vetoes)
    admissible = [fam for fam in rank_order if fam not in veto_set]

    warning = None
    if len(admissible) < 2:
        primary_a = None
        primary_b = None
        warning = "insufficient_admissible_families"
    else:
        primary_a = admissible[0]
        primary_b = admissible[1]

    return {
        "bt_scores": bt_scores,
        "rank_order": rank_order,
        "confidence": confidence,
        "admissible_families": admissible,
        "primary_family_block_a": primary_a,
        "primary_family_block_b": primary_b,
        "warning": warning,
    }
