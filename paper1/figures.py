"""Figures for paper 1 (stdlib only): writes SVG + CSV pairs into paper1/fig/.

    python3 paper1/figures.py

F1 fig1_survival: S(g) of round-1 facts after g compactions (report.json S and bootstrap CI).
F2 fig2_stock:    mean planted facts present in the summary at each round r.
F3 fig3_hazard:   forest plot of the age effects from paper1/hazard_age_fresh.json, plus the Haiku rewrite arm
                  (Addendum C) from paper1/hazard_age_fresh_c.json. The Sonnet rewrite arm is omitted: its
                  manipulation check failed (§4.5), so its estimates are non-informative by the registered rule.
"""

from __future__ import annotations

import csv
import json
import math
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from harness.analyze import load_run  # noqa: E402

OUT = ROOT / "paper1" / "fig"
RUNS = {"haiku": ROOT / "runs" / "e1", "sonnet": ROOT / "runs" / "e1", "qwen32b": ROOT / "runs" / "e1-open"}
MODELS = ("haiku", "sonnet", "qwen32b")
LABEL = {"haiku": "Haiku", "sonnet": "Sonnet", "qwen32b": "Qwen32B"}
BUDGETS = ("B150", "B400")
# Okabe–Ito palette.
COLOR = {"haiku": "#D55E00", "sonnet": "#0072B2", "qwen32b": "#009E73", "extract": "#999999"}
DASH = {"B150": "6,4", "B400": None}
FONT = "font-family:Helvetica,Arial,sans-serif"
N_ROUNDS = 10


# ---------------------------------------------------------------- SVG helper

def fmt(v: float) -> str:
    return f"{v:.2f}".rstrip("0").rstrip(".")


class SVG:
    def __init__(self, width: float, height: float):
        self.w, self.h = width, height
        self.items: list[str] = [f'<rect x="0" y="0" width="{width}" height="{height}" fill="white"/>']

    def text(self, x, y, s, size=13, anchor="start", weight="normal", rotate=None, color="black"):
        tr = f' transform="rotate({rotate} {fmt(x)} {fmt(y)})"' if rotate is not None else ""
        self.items.append(
            f'<text x="{fmt(x)}" y="{fmt(y)}" font-size="{size}" text-anchor="{anchor}" font-weight="{weight}" '
            f'fill="{color}" style="{FONT}"{tr}>{escape(s)}</text>')

    def line(self, x1, y1, x2, y2, color="black", width=1.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.items.append(f'<line x1="{fmt(x1)}" y1="{fmt(y1)}" x2="{fmt(x2)}" y2="{fmt(y2)}" '
                          f'stroke="{color}" stroke-width="{width}"{d}/>')

    def polyline(self, pts, color, width=2.0, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        p = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in pts)
        self.items.append(f'<polyline points="{p}" fill="none" stroke="{color}" stroke-width="{width}" '
                          f'stroke-linejoin="round"{d}/>')

    def polygon(self, pts, color, opacity=0.18):
        p = " ".join(f"{fmt(x)},{fmt(y)}" for x, y in pts)
        self.items.append(f'<polygon points="{p}" fill="{color}" fill-opacity="{opacity}" stroke="none"/>')

    def marker(self, x, y, color, shape="circle", r=3.5, filled=True):
        fill = color if filled else "white"
        if shape == "square":
            self.items.append(f'<rect x="{fmt(x - r)}" y="{fmt(y - r)}" width="{fmt(2 * r)}" height="{fmt(2 * r)}" '
                              f'fill="{fill}" stroke="{color}" stroke-width="1.5"/>')
        elif shape == "diamond":
            d = r * 1.3
            pts = f"{fmt(x)},{fmt(y - d)} {fmt(x + d)},{fmt(y)} {fmt(x)},{fmt(y + d)} {fmt(x - d)},{fmt(y)}"
            self.items.append(f'<polygon points="{pts}" fill="{fill}" stroke="{color}" stroke-width="1.5"/>')
        else:
            self.items.append(f'<circle cx="{fmt(x)}" cy="{fmt(y)}" r="{fmt(r)}" fill="{fill}" '
                              f'stroke="{color}" stroke-width="1.5"/>')

    def errbar_h(self, x1, x2, y, color, cap=4):
        self.line(x1, y, x2, y, color, 1.6)
        self.line(x1, y - cap, x1, y + cap, color, 1.6)
        self.line(x2, y - cap, x2, y + cap, color, 1.6)

    def legend(self, x, y, entries, size=13, row=19, col_w=None):
        """entries: (label, color, dash, marker_shape|None, marker_filled). Laid out in rows, or columns if col_w."""
        for i, (lab, color, dash, shape, filled) in enumerate(entries):
            ex, ey = (x + i * col_w, y) if col_w else (x, y + i * row)
            self.line(ex, ey, ex + 30, ey, color, 2.0, dash)
            if shape:
                self.marker(ex + 15, ey, color, shape, filled=filled)
            self.text(ex + 37, ey + 4.5, lab, size)

    def save(self, path: Path):
        body = "\n".join(self.items)
        path.write_text(f'<?xml version="1.0" encoding="UTF-8"?>\n<svg xmlns="http://www.w3.org/2000/svg" '
                        f'width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}">\n{body}\n</svg>\n')


class Axes:
    """Linear data->pixel mapping over the box (x0, y0, w, h) with black axes, ticks and labels."""

    def __init__(self, svg: SVG, x0, y0, w, h, xlim, ylim):
        self.svg, self.x0, self.y0, self.w, self.h, self.xlim, self.ylim = svg, x0, y0, w, h, xlim, ylim

    def X(self, v):
        return self.x0 + (v - self.xlim[0]) / (self.xlim[1] - self.xlim[0]) * self.w

    def Y(self, v):
        return self.y0 + self.h - (v - self.ylim[0]) / (self.ylim[1] - self.ylim[0]) * self.h

    def frame(self, xticks, yticks, xlabel=None, ylabel=None, title=None, ytick_labels=True, grid=True,
              xtick_fmt=fmt, ytick_fmt=fmt):
        s = self.svg
        bottom, right = self.y0 + self.h, self.x0 + self.w
        if grid:
            for t in yticks:
                s.line(self.x0, self.Y(t), right, self.Y(t), "#E5E5E5", 1)
        s.line(self.x0, bottom, right, bottom, "black", 1.2)
        s.line(self.x0, self.y0, self.x0, bottom, "black", 1.2)
        for t in xticks:
            s.line(self.X(t), bottom, self.X(t), bottom + 5, "black", 1.2)
            s.text(self.X(t), bottom + 19, xtick_fmt(t), 12, "middle")
        for t in yticks:
            s.line(self.x0 - 5, self.Y(t), self.x0, self.Y(t), "black", 1.2)
            if ytick_labels:
                s.text(self.x0 - 8, self.Y(t) + 4, ytick_fmt(t), 12, "end")
        if xlabel:
            s.text(self.x0 + self.w / 2, bottom + 40, xlabel, 13, "middle")
        if ylabel:
            s.text(self.x0 - 44, self.y0 + self.h / 2, ylabel, 13, "middle", rotate=-90)
        if title:
            s.text(self.x0 + self.w / 2, self.y0 - 10, title, 13, "middle", "bold")


def write_csv(path: Path, header, rows):
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        for r in rows:
            w.writerow([f"{v:.4f}" if isinstance(v, float) else v for v in r])


# ---------------------------------------------------------------- data

def load_reports() -> dict[str, dict]:
    arms: dict[str, dict] = {}
    for d in sorted(set(RUNS.values())):
        arms |= json.loads((d / "report.json").read_text())["arms"]
    return arms


def survival(arm: dict) -> list[tuple[int, float, float, float]]:
    """(g, S, lo, hi) for g = 0..N_ROUNDS; S(0) = 1 by definition."""
    rows = [(0, 1.0, 1.0, 1.0)]
    for g in range(1, N_ROUNDS + 1):
        lo, hi = arm["ci"]["S"][str(g)]
        rows.append((g, arm["S"][str(g)], lo, hi))
    return rows


def stock(chains: list[dict]) -> list[float]:
    """Mean over chains of the number of planted facts present in the summary at rounds 1..N_ROUNDS."""
    tot = [0] * N_ROUNDS
    for c in chains:
        for sc in c["scores"]:
            tot[sc["round"] - 1] += sum(f["present"] for f in sc["facts"])
    return [t / len(chains) for t in tot]


def planted_so_far(r: int) -> int:
    return 16 + 4 * (r - 1)


# ---------------------------------------------------------------- figures

def fig1(reports: dict) -> dict:
    pw, ph, left, top, gap = 270, 260, 70, 40, 40
    svg = SVG(left + 3 * pw + 2 * gap + 20, top + ph + 120)
    rows, out = [], {}
    arms = [(m, f"{m}-{b}-plain", COLOR[m], b) for m in MODELS for b in BUDGETS]
    arms += [("extract", f"extract-{b}", COLOR["extract"], b) for b in BUDGETS]
    for name in [a[1] for a in arms]:
        out[name] = survival(reports[name])
        rows += [(name, g, s, lo, hi) for g, s, lo, hi in out[name]]
    for i, m in enumerate(MODELS):
        ax = Axes(svg, left + i * (pw + gap), top, pw, ph, (0, 10), (0, 1))
        ax.frame(range(0, 11, 2), [0, 0.25, 0.5, 0.75, 1.0], "compactions survived g",
                 "S(g), round-1 facts present" if i == 0 else None, LABEL[m], ytick_labels=(i == 0),
                 ytick_fmt=lambda t: f"{t:.2f}")
        for b in BUDGETS:  # extract reference, grey, no band
            d = out[f"extract-{b}"]
            svg.polyline([(ax.X(g), ax.Y(s)) for g, s, _, _ in d], COLOR["extract"], 1.8, DASH[b])
        for b in BUDGETS:
            d = out[f"{m}-{b}-plain"]
            svg.polygon([(ax.X(g), ax.Y(hi)) for g, _, _, hi in d] + [(ax.X(g), ax.Y(lo)) for g, _, lo, _ in d[::-1]],
                        COLOR[m])
        for b in BUDGETS:
            d = out[f"{m}-{b}-plain"]
            svg.polyline([(ax.X(g), ax.Y(s)) for g, s, _, _ in d], COLOR[m], 2.2, DASH[b])
            for g, s, _, _ in d:
                svg.marker(ax.X(g), ax.Y(s), COLOR[m], "circle" if b == "B400" else "square", 3,
                           filled=(b == "B400"))
    ly = top + ph + 70
    svg.legend(left, ly, [("plain, B400 (95% band)", "black", None, "circle", True),
                          ("plain, B150 (95% band)", "black", DASH["B150"], "square", False),
                          ("extract baseline, B400", COLOR["extract"], None, None, True),
                          ("extract baseline, B150", COLOR["extract"], DASH["B150"], None, True)], col_w=220)
    svg.text(left, ly + 30, "Line colour = compactor model (panel); shaded band = chain-bootstrap 95% CI.", 12,
             color="#444444")
    svg.save(OUT / "fig1_survival.svg")
    write_csv(OUT / "fig1_survival.csv", ["arm", "g", "S", "ci_lo", "ci_hi"], rows)
    return out


def fig2() -> dict:
    chains: dict[str, list[dict]] = {}
    for d in sorted(set(RUNS.values())):
        chains |= load_run(d)
    pw, ph, left, top, gap = 340, 300, 70, 40, 50
    svg = SVG(left + 2 * pw + gap + 30, top + ph + 120)
    series = {f"{m}-{b}-plain": stock(chains[f"{m}-{b}-plain"]) for m in MODELS for b in BUDGETS}
    series |= {f"extract-{b}": stock(chains[f"extract-{b}"]) for b in BUDGETS}
    rs = range(1, N_ROUNDS + 1)
    for i, b in enumerate(BUDGETS):
        ax = Axes(svg, left + i * (pw + gap), top, pw, ph, (1, 10), (0, 56))
        ax.frame(rs, range(0, 57, 8), "round r", "facts present in summary (mean)" if i == 0 else None,
                 f"budget {b}", ytick_labels=True)
        svg.polyline([(ax.X(r), ax.Y(planted_so_far(r))) for r in rs], "black", 1.5, "2,3")
        for m in ("extract",) + MODELS:
            name = f"{m}-{b}-plain" if m != "extract" else f"extract-{b}"
            pts = [(ax.X(r), ax.Y(v)) for r, v in zip(rs, series[name])]
            svg.polyline(pts, COLOR[m], 2.2)
            for x, y in pts:
                svg.marker(x, y, COLOR[m], "square" if m == "extract" else "circle", 3)
    ly = top + ph + 70
    svg.legend(left, ly, [(LABEL[m] + " plain", COLOR[m], None, "circle", True) for m in MODELS]
               + [("extract", COLOR["extract"], None, "square", True)], col_w=150)
    svg.legend(left, ly + 24, [("facts planted so far, 16 + 4(r−1)", "black", "2,3", None, True)])
    svg.save(OUT / "fig2_stock.svg")
    write_csv(OUT / "fig2_stock.csv", ["arm", "round", "mean_present", "planted_so_far"],
              [(name, r, v, planted_so_far(r)) for name, vals in series.items() for r, v in zip(rs, vals)])
    return series


def fig3() -> list:
    hz = json.loads((ROOT / "paper1" / "hazard_age_fresh.json").read_text())
    hz.update(json.loads((ROOT / "paper1" / "hazard_age_fresh_c.json").read_text()))
    arms = [f"{m}-{b}-plain" for m in MODELS for b in BUDGETS] + ["haiku-B150-plain-rewrite"]
    cols = [("b2", "β2: entry penalty (log-odds, age 2 vs age 1)"), ("b4-b2", "β4+ − β2: further decline")]
    rows = [(a, k, hz[a]["effects"][k], hz[a]["ci"][k]["lo"], hz[a]["ci"][k]["hi"], hz[a]["ci"][k]["p"])
            for a in arms for k, _ in cols]
    lim = (min(-0.5, math.floor(min(r[3] for r in rows))), max(0.5, math.ceil(max(r[4] for r in rows))))
    step = 0.5 if lim[1] - lim[0] <= 3 else 1.0
    ticks = [lim[0] + i * step for i in range(int(round((lim[1] - lim[0]) / step)) + 1)]
    left, top, pw, gap, rowh, sep = 150, 40, 370, 50, 36, 8
    ph = rowh * len(arms) + sep
    svg = SVG(left + 2 * pw + gap + 20, top + ph + 105)
    for i, (key, title) in enumerate(cols):
        ax = Axes(svg, left + i * (pw + gap), top, pw, ph, lim, (len(arms), 0))
        ax.frame(ticks, [], "log-odds (point estimate, 95% CI)", None, title, grid=False)
        svg.line(ax.X(0), top, ax.X(0), top + ph, "black", 1.2, "4,3")
        for j, a in enumerate(arms):
            m, b, _, *mode = a.split("-")
            rewrite = bool(mode)
            y = top + (j + 0.5) * rowh + (sep if rewrite else 0)
            if rewrite:
                svg.line(ax.x0, y - rowh / 2 - sep / 2, ax.x0 + pw, y - rowh / 2 - sep / 2, "#BBBBBB", 1)
            if i == 0:
                svg.text(left - 12, y + 4.5, f"{LABEL[m]} {b}" + (" rewrite" if rewrite else ""), 13, "end")
            e, l, h = hz[a]["effects"][key], hz[a]["ci"][key]["lo"], hz[a]["ci"][key]["hi"]
            svg.errbar_h(ax.X(l), ax.X(h), y, COLOR[m])
            shape = "diamond" if rewrite else ("circle" if b == "B400" else "square")
            svg.marker(ax.X(e), y, COLOR[m], shape, 4.5, filled=(b == "B400"))
    svg.legend(left, top + ph + 80, [("B400", "black", None, "circle", True), ("B150", "black", None, "square", False),
                                     ("B150, budget enforced by rewriting (Addendum C)", "black", None, "diamond", False)],
               col_w=120)
    svg.save(OUT / "fig3_hazard.svg")
    write_csv(OUT / "fig3_hazard.csv", ["arm", "effect", "estimate", "ci_lo", "ci_hi", "p"], rows)
    return rows


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    reports = load_reports()
    s = fig1(reports)
    st = fig2()
    fig3()
    print("F1 S(g):  arm  g=1  g=10")
    for name, d in s.items():
        print(f"  {name:20s} {d[1][1]:.3f}  {d[10][1]:.3f}")
    print("F2 stock at r=10:")
    for name, v in st.items():
        print(f"  {name:20s} {v[-1]:.1f}")


if __name__ == "__main__":
    main()
