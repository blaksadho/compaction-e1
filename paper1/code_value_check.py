"""Exploratory (not pre-registered): does erasure depend on the value of the code? (Appendix A.7, assumption E2.)

Every (fact, compaction) pair at which the fact is still present is one trial. Trials from all LLM arms of E1 and
Addendum A are pooled. Reported: erasure rate by the number of digits in the code, by repeated characters and by a
leading digit; and the Mantel-Haenszel log-odds of erasure for codes with >= 3 digits against < 3, stratified by
arm x age bin (1, 2, 3, 4+), with a chain-bootstrap 95% interval.

    python3 paper1/code_value_check.py [--boot 300] [--seed 1]
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.trace import read_trace  # noqa: E402

RUNS = (ROOT / "runs" / "e1", ROOT / "runs" / "e1-open")


def load_trials() -> list[tuple]:
    """(arm, chain file, age, erased, n_digits, has_repeat, leading_digit) per trial."""
    trials = []
    for run in RUNS:
        for path in sorted(run.glob("*/*.jsonl")):
            if path.parent.name.startswith("extract"):
                continue
            recs = read_trace(path)
            if not recs or recs[-1].get("status") != "ok":
                continue
            start = recs[0]
            code = {f["fact_id"]: f["code"] for f in start["facts"]}
            arm = start["arm"]["name"]
            seen: dict[int, dict[int, bool]] = defaultdict(dict)
            for r in recs:
                if r["kind"] == "score":
                    for f in r["facts"]:
                        seen[f["fact_id"]][f["generation"]] = f["present"]
            for fid, by_g in seen.items():
                for g in sorted(by_g):
                    cd = code[fid]
                    trials.append((arm, path.name, g, not by_g[g], sum(ch.isdigit() for ch in cd),
                                   len(set(cd)) < 8, cd[0].isdigit()))
                    if not by_g[g]:
                        break
    return trials


def mh_log_odds(trials: list[tuple]) -> float:
    cells: dict[tuple, list[int]] = defaultdict(lambda: [0, 0, 0, 0])  # e1, n1, e0, n0
    for arm, _, g, erased, digits, _, _ in trials:
        c = cells[(arm, min(g, 4))]
        if digits >= 3:
            c[0] += erased
            c[1] += 1
        else:
            c[2] += erased
            c[3] += 1
    num = den = 0.0
    for e1, n1, e0, n0 in cells.values():
        if n1 and n0:
            num += e1 * (n0 - e0) / (n1 + n0)
            den += e0 * (n1 - e1) / (n1 + n0)
    return math.log(num / den)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=300)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args(argv)
    trials = load_trials()
    print(f"trials: {len(trials):,}")

    def rate(sel):
        s = [t for t in trials if sel(t)]
        return sum(t[3] for t in s) / len(s), len(s)

    for k in range(0, 8):
        r, n = rate(lambda t, k=k: t[4] == k)
        if n:
            print(f"  {k} digits: erasure {r:.4f} (n={n:,})")
    for name, sel in (("repeated character", lambda t: t[5]), ("all distinct", lambda t: not t[5]),
                      ("leading digit", lambda t: t[6]), ("leading letter", lambda t: not t[6])):
        r, n = rate(sel)
        print(f"  {name}: erasure {r:.4f} (n={n:,})")
    by_chain: dict[tuple, list] = defaultdict(list)
    for t in trials:
        by_chain[(t[0], t[1])].append(t)
    chains = sorted(by_chain)
    point = mh_log_odds(trials)
    rng = random.Random(a.seed)
    boots = sorted(mh_log_odds([t for ch in (rng.choice(chains) for _ in chains) for t in by_chain[ch]])
                   for _ in range(a.boot))
    lo, hi = boots[int(0.025 * (a.boot - 1))], boots[int(0.975 * (a.boot - 1))]
    print(f"MH log-odds of erasure, >=3 digits vs <3, stratified by arm x age: {point:+.3f} [{lo:+.3f}, {hi:+.3f}]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
