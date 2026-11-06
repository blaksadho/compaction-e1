"""Survival analysis for a run directory (notes/model.md §3; analysis plan in prereg/E1.md).

    python3 -m harness.analyze runs/<name> [--boot 2000] [--json out.json]

Per arm and generation g: S(g) (initial facts, planted in D_1), pooled per-generation survival s_g (all facts:
present at g among present at g-1), bound rate, mutation rate, overflow rate, hallucination rate.
Uncertainty: percentile bootstrap over chains (the resampling unit; facts within a chain are dependent).
Hypothesis contrasts: d1 = s_1 - s_{2+} (H1 vs H0) and the OLS slope of s_g on g for g >= 2 (H2).
A binomial LRT of H0 vs H1 is also reported (secondary: it ignores within-chain dependence).
"""

from __future__ import annotations

import argparse
import json
import math
import random
from collections import defaultdict
from pathlib import Path

from .trace import read_trace

PER_G = ("S_num", "S_den", "trans_num", "trans_den", "bound_num", "bound_den", "mut", "n", "rg_num", "rg_den")
SCALARS = ("resurrect", "halluc", "absent_probes", "overflow", "states", "cost")


def load_run(run_dir: Path) -> dict[str, list[dict]]:
    """arm -> list of completed chains, each {'chain', 'seed', 'scores', 'states', 'calls', 'cost'}."""
    arms: dict[str, list[dict]] = defaultdict(list)
    for path in sorted(run_dir.glob("*/*.jsonl")):
        recs = read_trace(path)
        if not recs or recs[-1].get("kind") != "chain_end" or recs[-1].get("status") != "ok":
            continue
        by = defaultdict(list)
        for r in recs:
            by[r["kind"]].append(r)
        start = by["chain_start"][0]
        arms[start["arm"]["name"]].append(
            {"chain": start["chain"], "seed": start["seed"], "scores": by["score"], "states": by["state"],
             "calls": by["call"], "cost": recs[-1]["cost_usd"]})
    return dict(arms)


def chain_counts(chain: dict) -> dict:
    """Sufficient statistics of one chain, keyed by generation g (rg_*: keyed by 'round:generation')."""
    present: dict[int, dict[int, bool]] = defaultdict(dict)  # fact -> generation -> present
    planted: dict[int, int] = {}
    c: dict = {k: defaultdict(int) for k in PER_G} | {"resurrect": 0, "halluc": 0, "absent_probes": 0}
    for sc in chain["scores"]:
        for f in sc["facts"]:
            g = f["generation"]
            present[f["fact_id"]][g] = f["present"]
            planted[f["fact_id"]] = f["planted_round"]
            c["n"][g] += 1
            c["mut"][g] += f["mutated"]
            if f["planted_round"] == 1:
                c["S_den"][g] += 1
                c["S_num"][g] += f["present"]
            if f["bound"] is not None:
                c["bound_den"][g] += 1
                c["bound_num"][g] += f["bound"]
        for a in sc["absent"]:
            c["absent_probes"] += 1
            c["halluc"] += a["hallucinated"]
    for fid, by_g in present.items():
        for g, p in by_g.items():
            prev = True if g == 1 else by_g.get(g - 1)
            if prev is None:
                continue
            if prev:
                rg = f"{planted[fid] + g - 1}:{g}"
                c["trans_den"][g] += 1
                c["trans_num"][g] += p
                c["rg_den"][rg] += 1
                c["rg_num"][rg] += p
            elif p:
                c["resurrect"] += 1
    c["overflow"] = sum(s["truncated"] for s in chain["states"])
    c["states"] = len(chain["states"])
    c["cost"] = chain["cost"]
    return c


def pooled(counts: list[dict]) -> dict:
    tot: dict = {}
    for key in PER_G:
        d: dict = defaultdict(int)
        for c in counts:
            for g, v in c[key].items():
                d[g] += v
        tot[key] = d
    for key in SCALARS:
        tot[key] = sum(c[key] for c in counts)
    return tot


def _ratio(num: dict, den: dict, g: int) -> float | None:
    return num[g] / den[g] if den.get(g) else None


def half_life(S: dict) -> float | None:
    """First g with S(g) <= 1/2, interpolated on log S between neighbouring generations (S(0) = 1)."""
    seq = [(0, 1.0)] + [(g, S[g]) for g in sorted(S) if S[g] is not None]
    for (g0, v0), (g1, v1) in zip(seq, seq[1:]):
        if v1 <= 0.5 < v0:
            if v1 <= 0:
                return float(g1)
            return g0 + (math.log(0.5) - math.log(v0)) / (math.log(v1) - math.log(v0)) * (g1 - g0)
    return None


def within_round(tot: dict, young: int) -> float | None:
    """Mean over summary rounds r of s(r, g=young) - s(r, g>young): same round, same load, different content age.
    young=1 tests H1 (raw vs already-summarized content); young=2 tests H2 (generation drift among summarized)."""
    num, den = tot["rg_num"], tot["rg_den"]
    rounds = sorted({int(k.split(":")[0]) for k in den})
    diffs = []
    for r in rounds:
        y = f"{r}:{young}"
        old = [k for k in den if int(k.split(":")[0]) == r and int(k.split(":")[1]) > young]
        o_den = sum(den[k] for k in old)
        if den.get(y) and o_den:
            diffs.append(num[y] / den[y] - sum(num[k] for k in old) / o_den)
    return sum(diffs) / len(diffs) if diffs else None


def stats(tot: dict) -> dict:
    S = {g: _ratio(tot["S_num"], tot["S_den"], g) for g in sorted(tot["S_den"])}
    s = {g: _ratio(tot["trans_num"], tot["trans_den"], g) for g in sorted(tot["trans_den"])}
    later_num = sum(tot["trans_num"][g] for g in s if g >= 2)
    later_den = sum(tot["trans_den"][g] for g in s if g >= 2)
    s2p = later_num / later_den if later_den else None
    pts = [(g, v) for g, v in s.items() if g >= 2 and v is not None]
    slope = None
    if len(pts) >= 2:
        mg = sum(g for g, _ in pts) / len(pts)
        mv = sum(v for _, v in pts) / len(pts)
        sxx = sum((g - mg) ** 2 for g, _ in pts)
        slope = sum((g - mg) * (v - mv) for g, v in pts) / sxx if sxx else None
    return {
        "S": S, "s": s, "s1": s.get(1), "s2p": s2p,
        "d1": (s[1] - s2p) if s.get(1) is not None and s2p is not None else None,
        "slope": slope, "half_life": half_life(S), "d1w": within_round(tot, 1), "d2w": within_round(tot, 2),
        "bound": {g: _ratio(tot["bound_num"], tot["bound_den"], g) for g in sorted(tot["bound_den"])},
        "mutation_rate": {g: tot["mut"][g] / tot["n"][g] for g in sorted(tot["n"])},
        "resurrections": tot["resurrect"],
        "hallucination_rate": tot["halluc"] / tot["absent_probes"] if tot["absent_probes"] else None,
        "overflow_rate": tot["overflow"] / tot["states"] if tot["states"] else None,
        "cost_usd": tot["cost"],
    }


def lrt_h0_h1(tot: dict) -> dict | None:
    """Binomial LRT, H0: s_g = s for all g vs H1: s_1 free, s_g = s for g >= 2. Secondary (ignores clustering)."""
    def ll(k: int, n: int, p: float) -> float:
        if n == 0:
            return 0.0
        p = min(max(p, 1e-12), 1 - 1e-12)
        return k * math.log(p) + (n - k) * math.log(1 - p)

    n1, k1 = tot["trans_den"].get(1, 0), tot["trans_num"].get(1, 0)
    n2 = sum(v for g, v in tot["trans_den"].items() if g >= 2)
    k2 = sum(v for g, v in tot["trans_num"].items() if g >= 2)
    if not n1 or not n2:
        return None
    l0 = ll(k1 + k2, n1 + n2, (k1 + k2) / (n1 + n2))
    l1 = ll(k1, n1, k1 / n1) + ll(k2, n2, k2 / n2)
    stat = max(0.0, 2 * (l1 - l0))
    return {"chi2": stat, "df": 1, "p": math.erfc(math.sqrt(stat / 2))}


def bootstrap(counts: list[dict], n_boot: int, seed: int) -> dict:
    rng = random.Random(seed)
    reps = [stats(pooled([rng.choice(counts) for _ in counts])) for _ in range(n_boot)]

    def ci(values: list) -> list | None:
        v = sorted(x for x in values if x is not None)
        if len(v) < max(20, n_boot // 2):  # undefined in too many replicates to report
            return None
        return [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]

    def p_two_sided(values: list) -> float | None:
        """Bootstrap sign test of 0: 2 * min(P*(x <= 0), P*(x >= 0)), capped at 1 (for Holm, prereg/E1.md)."""
        v = [x for x in values if x is not None]
        if len(v) < max(20, n_boot // 2):
            return None
        return min(1.0, 2 * min(sum(x <= 0 for x in v), sum(x >= 0 for x in v)) / len(v))

    contrasts = ("d1", "slope", "d1w", "d2w")
    return {
        "S": {g: ci([r["S"].get(g) for r in reps]) for g in sorted({g for r in reps for g in r["S"]})},
        "s": {g: ci([r["s"].get(g) for r in reps]) for g in sorted({g for r in reps for g in r["s"]})},
        **{k: ci([r[k] for r in reps]) for k in ("s1", "s2p", "half_life", *contrasts)},
        "p": {k: p_two_sided([r[k] for r in reps]) for k in contrasts},
    }


def paired_contrast(chains_a: list[dict], chains_b: list[dict], n_boot: int, seed: int) -> dict | None:
    """S_a(G) - S_b(G) at the last generation G of initial facts, over chains present in both arms (same material
    seed), with a chain-bootstrap CI and sign p-value."""
    def final_S(chain: dict) -> tuple[int, float] | None:
        c = chain_counts(chain)
        if not c["S_den"]:
            return None
        g = max(c["S_den"])
        return g, c["S_num"][g] / c["S_den"][g]

    a = {c["seed"]: final_S(c) for c in chains_a}
    b = {c["seed"]: final_S(c) for c in chains_b}
    diffs = [a[s][1] - b[s][1] for s in sorted(set(a) & set(b)) if a[s] and b[s] and a[s][0] == b[s][0]]
    if not diffs:
        return None
    rng = random.Random(seed)
    reps = sorted(sum(rng.choice(diffs) for _ in diffs) / len(diffs) for _ in range(n_boot)) if n_boot else []
    out = {"n_pairs": len(diffs), "mean_diff": sum(diffs) / len(diffs), "ci": None, "p": None}
    if len(diffs) >= 2 and reps:
        out["ci"] = [reps[int(0.025 * (n_boot - 1))], reps[int(0.975 * (n_boot - 1))]]
        out["p"] = min(1.0, 2 * min(sum(x <= 0 for x in reps), sum(x >= 0 for x in reps)) / n_boot)
    return out



def fmt(x, nd=3) -> str:
    return "—" if x is None else f"{x:.{nd}f}"


def fmt_ci(c) -> str:
    return "" if not c else f" [{c[0]:.3f}, {c[1]:.3f}]"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json")
    ap.add_argument("--pair", action="append", default=[], metavar="ARM_A:ARM_B",
                    help="paired contrast S_A(G) - S_B(G) on shared material seeds (repeatable)")
    args = ap.parse_args(argv)
    arms = load_run(Path(args.run_dir))
    report = {}
    for arm, chains in sorted(arms.items()):
        counts = [chain_counts(c) for c in chains]
        tot = pooled(counts)
        report[arm] = {"chains": len(chains), **stats(tot), "lrt_h0_h1": lrt_h0_h1(tot),
                       "ci": bootstrap(counts, args.boot, args.seed) if len(chains) >= 2 else None}
    for arm, r in report.items():
        ci = r["ci"] or {}
        print(f"\n## {arm}  (chains={r['chains']}, cost=${r['cost_usd']:.4f})")
        print("| g | S(g) initial facts | s_g pooled | bound | mutated |")
        print("|---|---|---|---|---|")
        for g in sorted(set(r["S"]) | set(r["s"])):
            print(f"| {g} | {fmt(r['S'].get(g))}{fmt_ci((ci.get('S') or {}).get(g))} | "
                  f"{fmt(r['s'].get(g))}{fmt_ci((ci.get('s') or {}).get(g))} | {fmt(r['bound'].get(g))} | "
                  f"{fmt(r['mutation_rate'].get(g))} |")
        lrt = r["lrt_h0_h1"]
        print(f"s_1={fmt(r['s1'])}{fmt_ci(ci.get('s1'))}  s_2+={fmt(r['s2p'])}{fmt_ci(ci.get('s2p'))}  "
              f"d1={fmt(r['d1'])}{fmt_ci(ci.get('d1'))}  slope={fmt(r['slope'], 4)}{fmt_ci(ci.get('slope'))}  "
              f"half-life={fmt(r['half_life'], 2)}{fmt_ci(ci.get('half_life'))}")
        print(f"within-round: d1w={fmt(r['d1w'])}{fmt_ci(ci.get('d1w'))}  d2w={fmt(r['d2w'])}{fmt_ci(ci.get('d2w'))}")
        print("LRT H0 vs H1: " + ("—" if not lrt else f"chi2={lrt['chi2']:.2f}, p={lrt['p']:.3g}") +
              f"; resurrections={r['resurrections']}; hallucination={fmt(r['hallucination_rate'])}; "
              f"overflow={fmt(r['overflow_rate'])}")
    pairs = {}
    for spec in args.pair:
        a, b = spec.split(":")
        pairs[spec] = paired_contrast(arms.get(a, []), arms.get(b, []), args.boot, args.seed)
        r = pairs[spec]
        print(f"\npaired {a} - {b}: " + ("no shared chains" if not r else
              f"n={r['n_pairs']}, diff={r['mean_diff']:.3f}{fmt_ci(r['ci'])}, p={fmt(r['p'])}"))
    if args.json:
        Path(args.json).write_text(json.dumps({"arms": report, "pairs": pairs}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
