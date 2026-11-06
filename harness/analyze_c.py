"""Addendum C analysis (prereg/E1-C.md): does the entry penalty survive when the budget is enforced by rewriting?

    python3 -m harness.analyze_c runs/e1-c runs/e1 --boot 2000 --seed 1 --json runs/e1-c/report.json

Pairs each `<model>-B150-plain-rewrite` arm (first run dir) with `<model>-B150-plain` (second run dir) by material
seed. Statistics:
- manipulation check: share of states in which the rewrite loop ended over budget and fell back to truncation;
- d1w per arm (harness.analyze.within_round, young=1) with chain-bootstrap CI and sign p;
- C1: d1w(rewrite) - d1w(plain), paired bootstrap (one resample of seeds applied to both arms);
- C2: d1w(rewrite) < 0, i.e. the entry penalty persists without tail truncation;
- Holm over the 4 tests (C1, C2 for each model);
- descriptive: paired S(10) difference; the share of new facts among facts present in the first draft but dropped by
  the rewrite, against their share among facts present in the first draft.
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path

from .analyze import chain_counts, load_run, paired_contrast, pooled, within_round

MODELS = ("haiku", "sonnet")


def _ci(v: list[float]) -> list[float] | None:
    v = sorted(x for x in v if x is not None)
    if len(v) < 20:
        return None
    return [v[int(0.025 * (len(v) - 1))], v[int(0.975 * (len(v) - 1))]]


def _p(v: list[float]) -> float | None:
    v = [x for x in v if x is not None]
    if len(v) < 20:
        return None
    return min(1.0, 2 * min(sum(x <= 0 for x in v), sum(x >= 0 for x in v)) / len(v))


def holm(ps: list[float]) -> list[float]:
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adj, run = [0.0] * len(ps), 0.0
    for k, i in enumerate(order):
        run = max(run, min(1.0, (len(ps) - k) * ps[i]))
        adj[i] = run
    return adj


def manipulation(chains: list[dict]) -> dict:
    states = [s for c in chains for s in c["states"]]
    n = len(states)
    over = sum(bool(s.get("truncated")) for s in states)
    fb = sum(bool(s.get("fallback_truncated")) for s in states)
    rw = sum(int(s.get("rewrites", 0)) for s in states)
    return {"states": n, "draft_over_budget": over / n if n else None, "rewrite_calls": rw,
            "fallback_rate": fb / n if n else None, "informative": n > 0 and fb / n <= 0.10}


def rewrite_drops(chains: list[dict]) -> dict:
    """Facts present in the first draft (present_untruncated) vs absent from the final state (present), split by
    whether this is the fact's first compaction (new) or not (incumbent)."""
    c = {"draft_new": 0, "draft_inc": 0, "drop_new": 0, "drop_inc": 0}
    for ch in chains:
        for sc in ch["scores"]:
            for f in sc["facts"]:
                if not f["present_untruncated"]:
                    continue
                new = f["generation"] == 1 and f["planted_round"] > 1
                if f["generation"] == 1 and f["planted_round"] == 1:
                    continue  # round-1 facts enter an empty summary; excluded from the new/incumbent split
                c["draft_new" if new else "draft_inc"] += 1
                if not f["present"]:
                    c["drop_new" if new else "drop_inc"] += 1
    drops = c["drop_new"] + c["drop_inc"]
    drafts = c["draft_new"] + c["draft_inc"]
    return c | {"new_share_of_drops": c["drop_new"] / drops if drops else None,
                "new_share_of_draft": c["draft_new"] / drafts if drafts else None}


def analyse(rw: list[dict], pl: list[dict], n_boot: int, seed: int) -> dict:
    a = {c["seed"]: chain_counts(c) for c in rw}
    b = {c["seed"]: chain_counts(c) for c in pl}
    seeds = sorted(set(a) & set(b))
    d_rw = within_round(pooled([a[s] for s in seeds]), 1)
    d_pl = within_round(pooled([b[s] for s in seeds]), 1)
    rng = random.Random(seed)
    reps_rw, reps_diff = [], []
    for _ in range(n_boot):
        sample = [rng.choice(seeds) for _ in seeds]
        x = within_round(pooled([a[s] for s in sample]), 1)
        y = within_round(pooled([b[s] for s in sample]), 1)
        reps_rw.append(x)
        reps_diff.append(None if x is None or y is None else x - y)
    return {
        "n_pairs": len(seeds),
        "manipulation": manipulation(rw),
        "d1w_rewrite": d_rw, "d1w_rewrite_ci": _ci(reps_rw), "p_C2": _p(reps_rw),
        "d1w_plain": d_pl,
        "C1_diff": None if d_rw is None or d_pl is None else d_rw - d_pl, "C1_ci": _ci(reps_diff),
        "p_C1": _p(reps_diff),
        "S10_rewrite_minus_plain": paired_contrast(rw, pl, n_boot, seed),
        "rewrite_drops": rewrite_drops(rw),
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rewrite_run", type=Path)
    ap.add_argument("plain_run", type=Path)
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    rw_arms, pl_arms = load_run(a.rewrite_run), load_run(a.plain_run)
    out: dict = {}
    for m in MODELS:
        rw, pl = rw_arms.get(f"{m}-B150-plain-rewrite"), pl_arms.get(f"{m}-B150-plain")
        if rw and pl:
            out[m] = analyse(rw, pl, a.boot, a.seed)
    tests = [(m, k) for m in out for k in ("p_C1", "p_C2")]
    ps = [out[m][k] if out[m][k] is not None else 1.0 for m, k in tests]
    for (m, k), q in zip(tests, holm(ps) if ps else []):
        out[m][k.replace("p_", "holm_")] = q
    for m, r in out.items():
        mc = r["manipulation"]
        print(f"{m}: pairs={r['n_pairs']} fallback={mc['fallback_rate']:.3f} informative={mc['informative']} "
              f"draft_over={mc['draft_over_budget']:.2f} rewrites={mc['rewrite_calls']}")
        print(f"  d1w rewrite={r['d1w_rewrite']:+.3f} {r['d1w_rewrite_ci']} C2 holm p={r.get('holm_C2')}")
        print(f"  d1w plain  ={r['d1w_plain']:+.3f}  C1 diff={r['C1_diff']:+.3f} {r['C1_ci']} holm p={r.get('holm_C1')}")
        print(f"  S10 rewrite-plain={r['S10_rewrite_minus_plain']}")
        print(f"  drops={r['rewrite_drops']}")
    if a.json:
        a.json.write_text(json.dumps(out, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
