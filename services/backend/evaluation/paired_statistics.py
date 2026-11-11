"""Paired binary estimates with source-stratified passage-cluster resampling."""
from collections import defaultdict
import math
import random


def percentile(values, probability):
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def wilson(successes, n):
    if n < 1:
        raise ValueError("Empty sample")
    z = 1.959963984540054
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [max(0.0, centre - radius), min(1.0, centre + radius)]


def paired_binary(rows, replicates=20000, seed=20261111):
    """Each row: before/after bool, source str, cluster str.

    Point estimate weights questions equally. Resample clusters within each source,
    retaining each source's original question weight. The interval is conditional
    on these five sources and labels; it does not model annotation bias.
    """
    if not rows or replicates < 2:
        raise ValueError("Rows and at least two replicates required")
    groups = defaultdict(lambda: defaultdict(list))
    for row in rows:
        if type(row["before"]) is not bool or type(row["after"]) is not bool:
            raise TypeError("Scores must be bool")
        groups[row["source"]][row["cluster"]].append(int(row["after"]) - int(row["before"]))
    n = len(rows)
    before = sum(row["before"] for row in rows)
    after = sum(row["after"] for row in rows)
    wins = sum(not row["before"] and row["after"] for row in rows)
    losses = sum(row["before"] and not row["after"] for row in rows)
    strata = []
    for clusters in groups.values():
        aggregates = [(sum(values), len(values)) for values in clusters.values()]
        weight = sum(size for _, size in aggregates) / n
        strata.append((aggregates, weight))
    rng = random.Random(seed)
    deltas = []
    for _ in range(replicates):
        total = 0.0
        for aggregates, weight in strata:
            resampled = rng.choices(aggregates, k=len(aggregates))
            total += weight * sum(s for s, _ in resampled) / sum(size for _, size in resampled)
        deltas.append(total)
    discordant = wins + losses
    p_exact = (min(1.0, 2 * sum(math.comb(discordant, k)
                              for k in range(min(wins, losses) + 1)) / 2 ** discordant)
               if discordant else 1.0)
    return {"n": n, "before_correct": before, "after_correct": after,
            "before_rate": before / n, "after_rate": after / n,
            "delta_pp": (after - before) / n * 100,
            "relative_improvement": (after - before) / before if before else None,
            "delta_95_cluster_bootstrap_pp": [100 * percentile(deltas, p) for p in (0.025, 0.975)],
            "before_95_wilson_iid": wilson(before, n), "after_95_wilson_iid": wilson(after, n),
            "wins": wins, "losses": losses, "both_correct": sum(r['before'] and r['after'] for r in rows),
            "both_wrong": sum(not r['before'] and not r['after'] for r in rows),
            "strata": len(groups), "clusters": sum(len(g) for g in groups.values()),
            "bootstrap_replicates": replicates, "bootstrap_seed": seed,
            "mcnemar_exact_iid_sensitivity_p": p_exact}
