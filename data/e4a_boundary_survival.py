#!/usr/bin/env python3
"""E4(a): atom transitions across successive production compaction boundaries (Compact-Bench e3).

Usage: python3 data/e4a_boundary_survival.py [--boot 2000] [--seed 1] [--json out.json]   (from compaction-theory/)

For each chain and consecutive boundaries (k, k+1), take the atoms needed after both boundaries,
A = atomsF[k] ∩ atomsF[k+1] (identity = (kind, value)), and score literal presence in S_k and S_{k+1}
exactly as code/harness/e3_score.py does (case-sensitive substring). Cells:

    n11: in S_k and in S_{k+1}      n10: in S_k, dropped from S_{k+1}
    n01: not in S_k, in S_{k+1}     n00: in neither

Every atom in atomsF[k] is used after boundary k, so it is back in the context the next compaction reads.
The absorbing erasure model of notes/model.md §3 (S(g) = Π s_g, no resurrection) therefore does not apply;
what this data identifies is

    s = P(in S_{k+1} | in S_k),  r = P(in S_{k+1} | not in S_k),  inertia = s - r.

inertia = 0: each summary re-selects from the live context independently of what the previous summary kept
(no memory through the summary). inertia = 1: the summary channel alone decides survival.

Boundary validity: 109 of 224 S_k texts (all marker=token_drop, form=embed) are the harness system prompt and
nothing else. Within a chain, successive such texts differ only in the embedded session-start timestamp, so
these boundaries are new sessions or subagent starts, not summaries, and an atom "kept" in them is static project
information. They are flagged `prompt_only`; the primary estimates use pairs where both texts are summaries.
"""
import argparse
import json
import os
import random
from collections import defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw", "compact-bench", "hf")


def atoms(pk):
    return {(kind, v) for kind, vs in pk["atomsF"].items() for v in vs}


def is_prompt_only(s):
    return s.lstrip().startswith("You are")


def r_by_k(chains):
    """Official per-boundary R_k (e3_score.py rule), over all scoreable boundaries and over summary boundaries."""
    out = {}
    for label, keep in (("all", lambda s: True), ("summary", lambda s: not is_prompt_only(s))):
        by_k = defaultdict(list)
        for c in chains:
            for pk in c["per_k"]:
                vals = [v for vs in pk["atomsF"].values() for v in vs]
                if vals and keep(pk["S_k"]):
                    by_k[pk["k"]].append(sum(v in pk["S_k"] for v in vals) / len(vals))
        out[label] = {k: [sum(v) / len(v), len(v)] for k, v in sorted(by_k.items())}
    return out


def transitions(chains):
    """One row per (chain, k, atom) with presence at k and k+1 plus strata."""
    rows = []
    for ci, c in enumerate(chains):
        pks = sorted(c["per_k"], key=lambda p: p["k"])
        for a, b in zip(pks, pks[1:]):
            prompt_only = is_prompt_only(a["S_k"]) or is_prompt_only(b["S_k"])
            for kind, v in atoms(a) & atoms(b):
                rows.append({
                    "chain": ci, "k": a["k"], "kind": kind, "client": c["client"],
                    "forms": f'{a["form"]}->{b["form"]}', "prompt_only": prompt_only,
                    "x": v in a["S_k"], "y": v in b["S_k"],
                })
    return rows


def stats(rows):
    n = [[0, 0], [0, 0]]
    for r in rows:
        n[r["x"]][r["y"]] += 1
    kept, dropped = n[1][0] + n[1][1], n[0][0] + n[0][1]
    total = kept + dropped
    s = n[1][1] / kept if kept else None
    r = n[0][1] / dropped if dropped else None
    return {
        "n_atoms": total, "n11": n[1][1], "n10": n[1][0], "n01": n[0][1], "n00": n[0][0],
        "R_k": kept / total if total else None,
        "R_k1": (n[1][1] + n[0][1]) / total if total else None,
        "s": s, "r": r, "inertia": s - r if s is not None and r is not None else None,
        "n_chains": len({x["chain"] for x in rows}),
    }


def boot(rows, reps, seed):
    """Percentile CIs and sign p-value for s, r, inertia; chains are the resampling unit."""
    by_chain = defaultdict(list)
    for r in rows:
        by_chain[r["chain"]].append(r)
    ids = sorted(by_chain)
    rng = random.Random(seed)
    draws = defaultdict(list)
    for _ in range(reps):
        sample = [x for _ in ids for x in by_chain[rng.choice(ids)]]
        st = stats(sample)
        for key in ("s", "r", "inertia"):
            if st[key] is not None:
                draws[key].append(st[key])
    out = {}
    for key, xs in draws.items():
        xs.sort()
        out[key] = [xs[int(0.025 * len(xs))], xs[min(len(xs) - 1, int(0.975 * len(xs)))]]
    xs = draws["inertia"]
    if xs:
        out["p_inertia"] = min(1.0, 2 * min(sum(x <= 0 for x in xs), sum(x >= 0 for x in xs)) / len(xs))
    return out


def fmt(x):
    return "—" if x is None else f"{x:.3f}"


def report(name, rows, reps, seed):
    st = stats(rows)
    if reps and st["n_atoms"]:
        st["ci"] = boot(rows, reps, seed)
    ci = st.get("ci", {})

    def c(key):
        return f" [{fmt(ci[key][0])}, {fmt(ci[key][1])}]" if key in ci else ""

    print(f"| {name} | {st['n_chains']} | {st['n_atoms']} | {fmt(st['R_k'])} | {fmt(st['R_k1'])} | "
          f"{fmt(st['s'])}{c('s')} | {fmt(st['r'])}{c('r')} | {fmt(st['inertia'])}{c('inertia')} |")
    return st


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--json")
    args = ap.parse_args()

    chains = [json.loads(l) for l in open(os.path.join(ROOT, "e3/chains.jsonl"), encoding="utf-8") if l.strip()]
    rk = r_by_k(chains)
    out = {"R_k": rk}
    ks = sorted(rk["all"])
    print("| boundaries | " + " | ".join(f"R_{k} (n)" for k in ks) + " |")
    print("|---|" + "---|" * len(ks))
    for label in ("all", "summary"):
        print(f"| {label} | " + " | ".join(
            f"{rk[label][k][0]:.3f} ({rk[label][k][1]})" if k in rk[label] else "—" for k in ks) + " |")
    print()

    rows = transitions(chains)
    print("| stratum | chains | atoms | R_k | R_{k+1} | s = P(kept at k+1 · kept at k) | "
          "r = P(kept at k+1 · dropped at k) | inertia s−r |")
    print("|---|---|---|---|---|---|---|---|")
    out["all"] = report("all pairs", rows, args.boot, args.seed)
    clean = [r for r in rows if not r["prompt_only"]]
    out["clean"] = report("both summaries", clean, args.boot, args.seed)
    out["prompt_only"] = report("either boundary prompt-only", [r for r in rows if r["prompt_only"]],
                                args.boot, args.seed)
    for field in ("client", "kind"):
        for val in sorted({r[field] for r in clean}, key=str):
            sub = [r for r in clean if r[field] == val]
            out[f"clean/{field}={val}"] = report(f"both summaries, {field}={val}", sub, args.boot, args.seed)
    p = out["clean"].get("ci", {}).get("p_inertia")
    if p is not None:
        print(f"\nboth-summaries inertia sign p-value (bootstrap): {p:.4f}")
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)


if __name__ == "__main__":
    main()
