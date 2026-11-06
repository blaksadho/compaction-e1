"""Appendix tables for paper 1 (stdlib only): prints Markdown to stdout.

    python3 paper1/appendix_tables.py > /tmp/appendix_tables.md

Sources: runs/*/report.json (harness.analyze output, 2,000 chain-bootstrap resamples, seed 1),
runs/e1-c/arms_report.json (same analysis on the Addendum C arms), paper1/hazard_age*.json
(paper1/survival_models.py) and paper1/fig/fig2_stock.csv (paper1/figures.py).

Appendix C: C1 S(g), C2 s_g, C3 per-arm summary, C4 paired contrasts, C5 fact stock.
Appendix D: the Qwen2.5-1.5B floor arms.
Appendix F: hazard model, all cohorts (F1) and fresh cohorts (F2), with raw hazards by age (F3).
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs"
N_ROUNDS = 10

# (report file, arms to include, in display order); arm names as in the reports.
ARM_SOURCES = [
    (RUNS / "e1" / "report.json", [
        "haiku-B150-plain", "haiku-B150-verbatim", "haiku-B150-pinned",
        "haiku-B400-plain", "haiku-B400-verbatim", "haiku-B400-pinned",
        "haiku-B150-plain-K8", "haiku-B150-plain-K32",
        "sonnet-B150-plain", "sonnet-B150-verbatim", "sonnet-B150-pinned",
        "sonnet-B400-plain", "sonnet-B400-verbatim", "sonnet-B400-pinned",
        "sonnet-B150-plain-K8", "sonnet-B150-plain-K32",
        "extract-B150", "extract-B400"]),
    (RUNS / "e1-open" / "report.json", [
        "qwen32b-B150-plain", "qwen32b-B150-verbatim", "qwen32b-B150-pinned",
        "qwen32b-B400-plain", "qwen32b-B400-verbatim", "qwen32b-B400-pinned"]),
    (RUNS / "e1-open-b" / "report.json", ["qwen32b-B150-pinned-v2", "qwen32b-B400-pinned-v2"]),
    (RUNS / "e1-c" / "arms_report.json", ["haiku-B150-plain-rewrite", "sonnet-B150-plain-rewrite"]),
]
LOCAL_REPORT = RUNS / "e1-local" / "report.json"
PAIR_SOURCES = [RUNS / "e1" / "report.json", RUNS / "e1-open" / "report.json", RUNS / "e1-open-b" / "report.json"]
C_REPORT = RUNS / "e1-c" / "report.json"
HAZARD_ALL = ROOT / "paper1" / "hazard_age.json"
HAZARD_FRESH = ROOT / "paper1" / "hazard_age_fresh.json"
HAZARD_FRESH_C = ROOT / "paper1" / "hazard_age_fresh_c.json"
STOCK_CSV = ROOT / "paper1" / "fig" / "fig2_stock.csv"


def load(path: Path) -> dict:
    return json.loads(path.read_text())


def f(x, nd=3) -> str:
    return "—" if x is None else f"{x:.{nd}f}".replace("-", "−")


def pm(x, nd=3) -> str:
    return "—" if x is None else f"{x:+.{nd}f}".replace("-", "−")


def ci(c, nd=3, signed=False) -> str:
    if not c:
        return "—"
    g = pm if signed else f
    return f"[{g(c[0], nd)}, {g(c[1], nd)}]"


def est_ci(x, c, nd=3, signed=False) -> str:
    return "—" if x is None else f"{(pm if signed else f)(x, nd)} {ci(c, nd, signed)}"


def pval(p) -> str:
    if p is None:
        return "—"
    return "< 0.001" if p < 0.0005 else f"{p:.3f}"


def label(arm: str) -> str:
    """Report arm name -> table label."""
    model, rest = arm.split("-", 1)
    name = {"haiku": "Haiku", "sonnet": "Sonnet", "qwen32b": "Qwen 32B", "qwen1.5b": "Qwen 1.5B",
            "extract": "extract"}[model]
    rest = rest.replace("B150", "150").replace("B400", "400").replace("-", ", ")
    rest = rest.replace("pinned, v2", "pinned (Addendum B)").replace("plain, rewrite", "plain, rewrite (Addendum C)")
    rest = rest.replace("plain, K8", "plain, K=8").replace("plain, K32", "plain, K=32")
    return f"{name}, {rest}"


def arms() -> list[tuple[str, dict]]:
    out = []
    for path, names in ARM_SOURCES:
        rep = load(path)["arms"]
        for n in names:
            out.append((n, rep[n]))
    return out


def table(header: list[str], rows: list[list[str]]) -> str:
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(r) + " |" for r in rows]
    return "\n".join(lines)


# ------------------------------------------------------------------ Appendix C

def c1_survival(rows_in) -> str:
    rows = []
    for name, r in rows_in:
        S, cS = r["S"], r["ci"]["S"]
        rows.append([label(name)] + [f(S.get(str(g))) for g in range(1, N_ROUNDS + 1)] + [ci(cS.get("10"))])
    return table(["arm"] + [f"$S({g})$" for g in range(1, N_ROUNDS + 1)] + ["95% CI of $S(10)$"], rows)


def c2_per_generation(rows_in) -> str:
    rows = []
    for name, r in rows_in:
        s = r["s"]
        rows.append([label(name)] + [f(s.get(str(g))) for g in range(1, N_ROUNDS + 1)])
    return table(["arm"] + [f"$s_{{{g}}}$" for g in range(1, N_ROUNDS + 1)], rows)


def c3_summary(rows_in) -> str:
    rows = []
    for name, r in rows_in:
        c = r["ci"]
        hl = r["half_life"]
        mut = max(r["mutation_rate"].values()) if r["mutation_rate"] else None
        rows.append([
            label(name), str(r["chains"]),
            est_ci(r["s1"], c["s1"]), est_ci(r["s2p"], c["s2p"]),
            est_ci(r["d1w"], c["d1w"], signed=True), pval(c["p"]["d1w"]),
            est_ci(r["d2w"], c["d2w"], signed=True), pval(c["p"]["d2w"]),
            est_ci(r["slope"], c["slope"], 4, signed=True),
            "none" if hl is None else f"{hl:.2f} {ci(c['half_life'], 2)}",
        ])
    return table(["arm", "chains", "$s_1$", "$s_{2+}$", "$d_{1w}$", "$p$", "$d_{2w}$", "$p$",
                  "OLS slope of $s_g$, $g\\ge2$", "half-life (rounds)"], rows)


def c3b_secondary(rows_in) -> str:
    rows = []
    for name, r in rows_in:
        b = r["bound"]
        mut = max(r["mutation_rate"].values()) if r["mutation_rate"] else None
        rows.append([
            label(name), f(b.get("1")), f(b.get("10")), f"{100 * mut:.1f}%" if mut is not None else "—",
            str(r["resurrections"]), f"{100 * r['hallucination_rate']:.1f}%", f"{100 * r['overflow_rate']:.0f}%",
            f"{r['cost_usd']:.2f}",
        ])
    return table(["arm", "bound, $g=1$", "bound, $g=10$", "max mutation rate", "resurrections",
                  "hallucination", "overflow", "cost (USD)"], rows)


def c4_pairs() -> str:
    rows = []
    for path in PAIR_SOURCES:
        for spec, r in load(path)["pairs"].items():
            a, b = spec.split(":")
            rows.append([label(a), label(b), str(r["n_pairs"]), est_ci(r["mean_diff"], r["ci"], signed=True),
                         pval(r["p"])])
    c = load(C_REPORT)
    for m in ("haiku", "sonnet"):
        r = c[m]["S10_rewrite_minus_plain"]
        rows.append([label(f"{m}-B150-plain-rewrite"), label(f"{m}-B150-plain"), str(r["n_pairs"]),
                     est_ci(r["mean_diff"], r["ci"], signed=True), pval(r["p"])])
    return table(["arm A", "arm B", "pairs", "$S_A(10)-S_B(10)$ [95% CI]", "$p$"], rows)


def c5_stock() -> str:
    by_arm: dict[str, dict[int, float]] = {}
    planted: dict[int, int] = {}
    with STOCK_CSV.open() as fh:
        for row in csv.DictReader(fh):
            by_arm.setdefault(row["arm"], {})[int(row["round"])] = float(row["mean_present"])
            planted[int(row["round"])] = int(row["planted_so_far"])
    rows = [["planted so far"] + [str(planted[r]) for r in range(1, N_ROUNDS + 1)]]
    for name, vals in by_arm.items():
        rows.append([label(name)] + [f"{vals[r]:.1f}" for r in range(1, N_ROUNDS + 1)])
    return table(["arm"] + [f"$r={r}$" for r in range(1, N_ROUNDS + 1)], rows)


# ------------------------------------------------------------------ Appendix D


def d_local() -> str:
    rep = load(LOCAL_REPORT)["arms"]
    rows = []
    for name in ("qwen1.5b-B400-plain", "qwen1.5b-B400-verbatim"):
        r = rep[name]
        c = r["ci"]
        mut = max(r["mutation_rate"].values())
        rows.append([
            label(name), str(r["chains"]), est_ci(r["S"]["1"], c["S"]["1"]), est_ci(r["S"]["2"], c["S"]["2"]),
            f(r["S"].get("3")), f(r["S"]["10"]), f"{r['half_life']:.2f} {ci(c['half_life'], 2)}",
            f(r["s"]["1"]), f(r["s"]["2"]),
            f(r["bound"]["1"]), f"{100 * mut:.2f}%", str(r["resurrections"]),
            f"{100 * r['hallucination_rate']:.1f}%", f"{100 * r['overflow_rate']:.0f}%",
        ])
    return table(["arm", "chains", "$S(1)$", "$S(2)$", "$S(3)$", "$S(10)$", "half-life", "$s_1$", "$s_2$",
                  "bound, $g=1$", "max mutation", "resurrections", "hallucination", "overflow"], rows)


# ------------------------------------------------------------------ Appendix F

def hazard_table(path: Path, names: list[str] | None = None) -> str:
    d = load(path)
    rows = []
    for arm in (names or list(d)):
        r = d[arm]
        e, c = r["effects"], r["ci"]

        def cell(k):
            return "—" if k not in e else f"{pm(e[k], 2)} [{pm(c[k]['lo'], 2)}, {pm(c[k]['hi'], 2)}]"

        rows.append([label(arm), cell("b2"), cell("b3"), cell("b4"), cell("b3-b2"), cell("b4-b2")])
    return table(["arm", "$\\beta_2$", "$\\beta_3$", "$\\beta_{4^+}$", "$\\beta_3-\\beta_2$",
                  "$\\beta_{4^+}-\\beta_2$"], rows)


def raw_hazard_table(path: Path, names: list[str] | None = None) -> str:
    d = load(path)
    rows = []
    for arm in (names or list(d)):
        raw = d[arm]["raw_hazard_by_age"]
        cells = []
        for a in ("1", "2", "3", "4"):
            h, n = raw.get(a, (None, 0))
            cells.append("—" if h is None else f"{h:.3f} ({n:,})")
        rows.append([label(arm)] + cells)
    return table(["arm", "age 1", "age 2", "age 3", "age 4+"], rows)


def round_effects_table(fresh_only: bool) -> str:
    """Fitted entry hazard sigma(alpha_r) per round for the six plain arms (point estimates, no bootstrap)."""
    import math
    import sys

    sys.path.insert(0, str(ROOT))
    from harness.analyze import load_run  # noqa: E402
    from paper1.survival_models import chain_cells, fit, merge  # noqa: E402

    runs = {"haiku": RUNS / "e1", "sonnet": RUNS / "e1", "qwen32b": RUNS / "e1-open"}
    loaded = {d: load_run(d) for d in set(runs.values())}
    rows = []
    for model, run in runs.items():
        for b in ("B150", "B400"):
            arm = f"{model}-{b}-plain"
            cells = merge(chain_cells(c, fresh_only) for c in loaded[run][arm])
            alpha = fit(cells)["alpha"]
            rows.append([label(arm)] + ["—" if r not in alpha else f"{1 / (1 + math.exp(-alpha[r])):.3f}"
                                        for r in range(1, N_ROUNDS + 1)])
    return table(["arm"] + [f"$r={r}$" for r in range(1, N_ROUNDS + 1)], rows)


def main() -> None:
    all_arms = arms()
    fresh = [n for n, _ in all_arms if n.endswith("-plain") or "-plain-K" in n]
    print("<!-- generated by paper1/appendix_tables.py -->\n")
    print("### Table C1\n")
    print(c1_survival(all_arms) + "\n")
    print("### Table C2\n")
    print(c2_per_generation(all_arms) + "\n")
    print("### Table C3\n")
    print(c3_summary(all_arms) + "\n")
    print("### Table C4\n")
    print(c3b_secondary(all_arms) + "\n")
    print("### Table C5\n")
    print(c4_pairs() + "\n")
    print("### Table C6\n")
    print(c5_stock() + "\n")
    print("### Table D1\n")
    print(d_local() + "\n")
    print("### Table F1 (all cohorts)\n")
    print(hazard_table(HAZARD_ALL, [n for n, _ in all_arms if not n.endswith(("-v2", "-rewrite"))]) + "\n")
    print("### Table F2 (fresh cohorts)\n")
    print(hazard_table(HAZARD_FRESH, fresh) + "\n")
    print(hazard_table(HAZARD_FRESH_C) + "\n")
    print("### Table F3 (raw hazard by age, fresh cohorts; at-risk counts in parentheses)\n")
    print(raw_hazard_table(HAZARD_FRESH, fresh) + "\n")
    print(raw_hazard_table(HAZARD_FRESH_C) + "\n")
    print("### Table F4 (fitted entry hazard by round, all cohorts; fresh cohorts in the second table)\n")
    print(round_effects_table(False) + "\n")
    print(round_effects_table(True) + "\n")


if __name__ == "__main__":
    main()
