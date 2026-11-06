#!/usr/bin/env python3
"""Stdlib-only schema/summary inspection of the downloaded Compact-Bench files.

Usage: python3 data/inspect_compact_bench.py   (run from compaction-theory/)
Prints file sizes, record counts, a recursive field/type schema with truncated
example values, and per-boundary summaries for e3/chains.jsonl (Production-Chain
Retention: the multi-compaction track relevant to E4).
"""
import json
import os
from collections import Counter, defaultdict

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "raw", "compact-bench", "hf")


def trunc(v, n=80):
    s = json.dumps(v, ensure_ascii=False)
    return s if len(s) <= n else s[:n] + "..."


def schema(objs, prefix="", out=None, depth=0, max_depth=4):
    """Collect path -> (Counter of types, example) over a list of JSON values."""
    out = {} if out is None else out
    for o in objs:
        t = type(o).__name__
        ent = out.setdefault(prefix or "<root>", [Counter(), None])
        ent[0][t] += 1
        if ent[1] is None and not isinstance(o, (dict, list)):
            ent[1] = trunc(o)
    if depth >= max_depth:
        return out
    dicts = [o for o in objs if isinstance(o, dict)]
    keys = defaultdict(list)
    for d in dicts:
        for k, v in d.items():
            keys[k].append(v)
    for k, vs in keys.items():
        schema(vs, f"{prefix}.{k}" if prefix else k, out, depth + 1, max_depth)
    lists = [x for o in objs if isinstance(o, list) for x in o]
    if lists:
        schema(lists[:20000], prefix + "[]", out, depth + 1, max_depth)
    return out


def print_schema(name, objs, max_depth=4):
    print(f"\n### schema: {name} (n={len(objs)})")
    for path, (types, ex) in schema(objs, max_depth=max_depth).items():
        print(f"  {path:45s} {dict(types)}  {ex or ''}")


def main():
    print("## files")
    for dp, _, fs in sorted(os.walk(ROOT)):
        for f in sorted(fs):
            p = os.path.join(dp, f)
            if "/d3snap/" in p or "/H3/" in p:
                continue
            print(f"  {os.path.getsize(p):>10d}  {os.path.relpath(p, ROOT)}")
    for sub in ("e1/H3", "e1/d3snap"):
        d = os.path.join(ROOT, sub)
        fs = os.listdir(d)
        print(f"  {sum(os.path.getsize(os.path.join(d, f)) for f in fs):>10d}  {sub}/ ({len(fs)} files)")

    # e1
    inst = json.load(open(os.path.join(ROOT, "e1/instances.json"), encoding="utf-8"))
    inst_list = inst if isinstance(inst, list) else list(inst.values())
    print_schema("e1/instances.json", inst_list, max_depth=2)
    h3 = json.load(open(os.path.join(ROOT, "e1/H3/pallets__flask-5014.H3.json"), encoding="utf-8"))
    print_schema("e1/H3/pallets__flask-5014.H3.json", [h3], max_depth=3)

    # e2
    sess = [json.loads(l) for l in open(os.path.join(ROOT, "e2/sessions.jsonl"), encoding="utf-8") if l.strip()]
    print_schema("e2/sessions.jsonl", sess, max_depth=3)
    print("  clients:", Counter(s.get("client") for s in sess))
    print("  atom kinds:", Counter(a["kind"] for s in sess for a in s["atoms"]))
    print("  total atoms:", sum(len(s["atoms"]) for s in sess))
    print("  boundary_idx:", Counter(s.get("boundary_idx") for s in sess).most_common(10))
    print("  distinct sess:", len({s.get("sess") for s in sess}))

    # e3
    chains = [json.loads(l) for l in open(os.path.join(ROOT, "e3/chains.jsonl"), encoding="utf-8") if l.strip()]
    print_schema("e3/chains.jsonl", chains, max_depth=3)
    print("  clients:", Counter(c.get("client") for c in chains))
    print("  n_bounds dist:", sorted(Counter(c["n_bounds"] for c in chains).items()))
    print("  total boundaries:", sum(len(c["per_k"]) for c in chains))
    print("  marker:", Counter(pk.get("marker") for c in chains for pk in c["per_k"]))
    print("  form:", Counter(pk.get("form") for c in chains for pk in c["per_k"]))
    print("  atomsF groups:", Counter(g for c in chains for pk in c["per_k"] for g in pk["atomsF"]))
    # deterministic R_k (same rule as harness/e3_score.py): atom literally in S_k
    by_k = defaultdict(list)
    for c in chains:
        for pk in c["per_k"]:
            vals = [v for vs in pk["atomsF"].values() for v in vs]
            if vals:
                by_k[pk["k"]].append(sum(v in pk["S_k"] for v in vals) / len(vals))
    print("  mean R_k by k:", {k: (round(sum(v) / len(v), 3), len(v)) for k, v in sorted(by_k.items())})


if __name__ == "__main__":
    main()
