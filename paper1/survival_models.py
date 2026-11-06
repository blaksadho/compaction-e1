"""Exploratory (not pre-registered): separate the effect of a fact's age from the effect of load on erasure.

Every fact is erased at most once (0 resurrections in all arms), so each (fact, compaction) pair at which the
fact is still present is one Bernoulli trial: erased or not. Facts of all cohorts are pooled. A compaction at
round r acting on a fact planted at round p has age a = r - p + 1 (a = 1: its first compaction).

Model: logit h(r, a) = alpha_r + beta_a, with
  alpha_r  one effect per round: everything shared by all facts in that summary (load, fill, budget pressure);
  beta_a   age effects relative to a = 1, ages binned 1, 2, 3, 4+.
beta_2 < 0: a fact that survived its first compaction is safer than a new fact in the same summary (incumbency).
beta_3, beta_4+ < beta_2: the hazard keeps falling with age (survivability heterogeneity or age-ranked retention);
beta_3 = beta_4+ = beta_2: one cut at entry, then a constant age-independent hazard.
The estimates are fitted on (round, age) cell counts with a small ridge (lambda) so empty rounds stay finite.
Confidence intervals come from a chain bootstrap.
Usage: python3 paper1/survival_models.py runs/e1 runs/e1-open [--boot 1000] [--json out.json]
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.analyze import load_run  # noqa: E402

AGES = (1, 2, 3, 4)  # 4 = "4+"


def age_bin(a: int) -> int:
    return min(a, AGES[-1])


def chain_cells(chain: dict, fresh_only: bool = False) -> dict[tuple[int, int], list[int]]:
    """(round, age bin) -> [at_risk, erased] for one chain; fresh_only drops facts planted in round 1."""
    seq: dict[int, dict[int, bool]] = defaultdict(dict)
    planted: dict[int, int] = {}
    for sc in chain["scores"]:
        for f in sc["facts"]:
            seq[f["fact_id"]][f["generation"]] = f["present"]
            planted[f["fact_id"]] = f["planted_round"]
    cells: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for fid, by_g in seq.items():
        if fresh_only and planted[fid] == 1:
            continue
        for g in sorted(by_g):
            cell = cells[(planted[fid] + g - 1, age_bin(g))]
            cell[0] += 1
            if not by_g[g]:
                cell[1] += 1
                break
    return cells


def merge(cell_sets) -> dict[tuple[int, int], list[int]]:
    tot: dict[tuple[int, int], list[int]] = defaultdict(lambda: [0, 0])
    for cs in cell_sets:
        for k, (n, e) in cs.items():
            tot[k][0] += n
            tot[k][1] += e
    return tot


def _solve(A: list[list[float]], b: list[float]) -> list[float]:
    n = len(b)
    M = [row[:] + [b[i]] for i, row in enumerate(A)]
    for c in range(n):
        p = max(range(c, n), key=lambda r: abs(M[r][c]))
        M[c], M[p] = M[p], M[c]
        for r in range(c + 1, n):
            f = M[r][c] / M[c][c]
            for k in range(c, n + 1):
                M[r][k] -= f * M[c][k]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (M[r][n] - sum(M[r][k] * x[k] for k in range(r + 1, n))) / M[r][r]
    return x


def fit(cells: dict[tuple[int, int], list[int]], lam: float = 0.1, iters: int = 100) -> dict:
    """Penalised binomial logistic regression by Newton's method. Returns round and age effects and the deviance."""
    rounds = sorted({r for r, _ in cells})
    ages = [a for a in AGES[1:] if any(k[1] == a and v[0] for k, v in cells.items())]
    idx = {("r", r): i for i, r in enumerate(rounds)} | {("a", a): len(rounds) + j for j, a in enumerate(ages)}
    p = len(idx)
    rows = [(k, n, e) for k, (n, e) in cells.items() if n]
    x = [0.0] * p
    for _ in range(iters):
        g = [-lam * xi for xi in x]
        H = [[(lam if i == j else 0.0) for j in range(p)] for i in range(p)]
        for (r, a), n, e in rows:
            cols = [idx[("r", r)]] + ([idx[("a", a)]] if a != 1 else [])
            eta = sum(x[c] for c in cols)
            mu = 1 / (1 + math.exp(-eta))
            w = n * mu * (1 - mu)
            for c in cols:
                g[c] += e - n * mu
                for c2 in cols:
                    H[c][c2] += w
        step = _solve(H, g)
        x = [xi + si for xi, si in zip(x, step)]
        if max(abs(s) for s in step) < 1e-9:
            break
    beta = {a: x[idx[("a", a)]] for a in ages}
    return {"alpha": {r: x[idx[("r", r)]] for r in rounds}, "beta": beta}


def contrasts(beta: dict) -> dict:
    b = {1: 0.0} | beta
    out = {f"b{a}": b[a] for a in b if a != 1}
    if 2 in b and 3 in b:
        out["b3-b2"] = b[3] - b[2]
    if 2 in b and 4 in b:
        out["b4-b2"] = b[4] - b[2]
    return out


def raw_hazard(cells) -> dict[int, tuple[float | None, int]]:
    by_a: dict[int, list[int]] = defaultdict(lambda: [0, 0])
    for (_, a), (n, e) in cells.items():
        by_a[a][0] += n
        by_a[a][1] += e
    return {a: (e / n if n else None, n) for a, (n, e) in sorted(by_a.items())}


def analyse(chains: list[dict], n_boot: int, seed: int, fresh_only: bool = False) -> dict:
    per_chain = [chain_cells(c, fresh_only) for c in chains]
    cells = merge(per_chain)
    point = contrasts(fit(cells)["beta"])
    rng = random.Random(seed)
    boots: dict[str, list[float]] = defaultdict(list)
    for _ in range(n_boot):
        bc = contrasts(fit(merge(rng.choice(per_chain) for _ in per_chain))["beta"])
        for k, v in bc.items():
            boots[k].append(v)
    ci = {}
    for k, vs in boots.items():
        vs.sort()
        lo, hi = vs[int(0.025 * len(vs))], vs[min(len(vs) - 1, int(0.975 * len(vs)))]
        p_two = 2 * min(sum(v >= 0 for v in vs), sum(v <= 0 for v in vs)) / len(vs)
        ci[k] = {"lo": lo, "hi": hi, "p": min(1.0, p_two)}
    return {"n_chains": len(chains), "raw_hazard_by_age": raw_hazard(cells), "effects": point, "ci": ci}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("runs", nargs="+", type=Path)
    ap.add_argument("--boot", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--arms", help="substring filter on arm names")
    ap.add_argument("--fresh-only", action="store_true", help="drop facts planted in round 1 (cohort confound check)")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    out = {}
    for run in a.runs:
        for arm, chains in sorted(load_run(run).items()):
            if a.arms and a.arms not in arm:
                continue
            r = analyse(chains, a.boot, a.seed, a.fresh_only)
            out[arm] = r
            raw = "  ".join(f"a{k}:{'—' if h is None else f'{h:.3f}'}({n})" for k, (h, n) in r["raw_hazard_by_age"].items())
            eff = "  ".join(f"{k}={v:+.2f}[{r['ci'][k]['lo']:+.2f},{r['ci'][k]['hi']:+.2f}]"
                            for k, v in r["effects"].items())
            print(f"{arm:24} {raw}\n{'':24} {eff}")
    if a.json:
        a.json.write_text(json.dumps(out, indent=1, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
