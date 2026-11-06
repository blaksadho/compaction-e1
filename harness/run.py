"""Run a repeated-compaction experiment from a JSON config.

    python3 -m harness.run configs/smoke.json            # run (resumes: completed chains are skipped)
    python3 -m harness.run configs/smoke.json --dry-run  # print the job list and prompt sizes, no model calls

Design: paired. Chain c of every arm uses the same planted facts and chunks (seed = config seed + c) unless the
arm overrides `material`, so arm contrasts are within-chain. The interpreter probe uses one fixed backend for all
arms, so `bound` measures the state, not the interpreter.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import random
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from .backends import ChatBackend
from .compactors import ExtractiveCompactor, LLMCompactor, State, words
from .facts import build_chain
from .score import PROBE_SYSTEM, parse_probe, probe_prompt, string_scores
from .trace import ChainTrace, chain_completed

ROOT = Path(__file__).resolve().parent.parent


class Budget:
    def __init__(self, max_usd: float):
        self.max_usd, self.spent, self._lock = max_usd, 0.0, threading.Lock()

    def add(self, usd: float) -> None:
        with self._lock:
            self.spent += usd

    def check(self) -> None:
        if self.spent >= self.max_usd:
            raise RuntimeError(f"run budget exhausted: ${self.spent:.4f} >= ${self.max_usd}")


def material_params(cfg: dict, arm: dict) -> dict:
    return cfg["material"] | arm.get("material", {})


def make_compactor(arm: dict, backends: dict[str, ChatBackend]):
    if arm["compactor"] == "extract":
        return ExtractiveCompactor(arm["budget"])
    return LLMCompactor(backends[arm["backend"]], arm["budget"], arm["instruction"],
                        arm.get("pinned_budget", 0), arm.get("enforce", "truncate"),
                        max_rewrites=arm.get("max_rewrites", 2))


def call_record(trace: ChainTrace, budget: Budget, call_kind: str, rnd: int, system, user, comp) -> None:
    budget.add(comp.cost_usd)
    trace.write("call", call=call_kind, round=rnd, model=comp.model, system=system, user=user, response=comp.text,
                finish_reason=comp.finish_reason, input_tokens=comp.input_tokens, output_tokens=comp.output_tokens,
                cost_usd=comp.cost_usd, latency_s=round(comp.latency_s, 3), attempts=comp.attempts)


def run_chain(cfg: dict, arm: dict, chain: int, backends: dict[str, ChatBackend], budget: Budget, path: Path) -> dict:
    mat_cfg = material_params(cfg, arm)
    seed = cfg["seed"] + chain
    rounds = cfg["rounds"]
    mat = build_chain(seed, rounds, mat_cfg["k_initial"], mat_cfg["k_fresh"], mat_cfg["lines_per_chunk"],
                      mat_cfg["n_absent"])
    compactor = make_compactor(arm, backends)
    probe_cfg = cfg.get("probe")
    probe_backend = backends[probe_cfg["backend"]] if probe_cfg else None
    probe_rounds = set(range(1, rounds + 1)) if not probe_cfg or probe_cfg.get("rounds", "all") == "all" \
        else set(probe_cfg["rounds"])
    all_codes = {f.code for f in mat.facts}
    trace = ChainTrace(path)
    cost = 0.0
    try:
        trace.write("chain_start", arm=arm, chain=chain, seed=seed, rounds=rounds, material=mat_cfg,
                    facts=[f.to_json() for f in mat.facts], absent=mat.absent)
        state = State([], "")
        for rnd in range(1, rounds + 1):
            budget.check()
            chunk = mat.chunks[rnd - 1]
            trace.write("chunk", round=rnd, text=chunk, n_words=words(chunk),
                        facts=[f.fact_id for f in mat.facts if f.round == rnd])
            res = compactor.compact(state, chunk)
            if res.completion is not None:
                call_record(trace, budget, "compact", rnd, res.system, res.user, res.completion)
                cost += res.completion.cost_usd
            for kind, system, user, comp in res.extra_calls:  # rewrite calls (prereg/E1-C.md)
                call_record(trace, budget, kind, rnd, system, user, comp)
                cost += comp.cost_usd
            state = res.state
            text = state.render()
            extra_state = ({"rewrites": res.rewrites, "fallback_truncated": res.fallback_truncated}
                           if arm.get("enforce") == "rewrite" else {})
            trace.write("state", round=rnd, text=text, n_words=words(text), pinned=state.pinned,
                        untruncated_words=words(res.untruncated), truncated=res.truncated,
                        untruncated=res.untruncated if res.truncated else None, **extra_state)
            live = [f for f in mat.facts if f.round <= rnd]
            scores = string_scores(text, live, all_codes)
            untrunc = string_scores(res.untruncated, live, all_codes) if res.truncated else scores
            probed = probe_backend is not None and rnd in probe_rounds
            answers: list = [None] * (len(live) + len(mat.absent))
            if probed:
                descriptors = [f.descriptor for f in live] + mat.absent
                order = list(range(len(descriptors)))  # question order shuffled per round; answers mapped back
                random.Random(seed * 1000 + rnd).shuffle(order)
                user = probe_prompt(text, [descriptors[j] for j in order])
                comp = probe_backend.complete(PROBE_SYSTEM, user, 16 * len(descriptors) + 64)
                call_record(trace, budget, "probe", rnd, PROBE_SYSTEM, user, comp)
                cost += comp.cost_usd
                for pos, ans in enumerate(parse_probe(comp.text, len(descriptors))):
                    answers[order[pos]] = ans
            facts_out = []
            for i, f in enumerate(live):
                s = scores[f.fact_id]
                facts_out.append({"fact_id": f.fact_id, "planted_round": f.round, "generation": rnd - f.round + 1,
                                  **s, "present_untruncated": untrunc[f.fact_id]["present"],
                                  "pinned": any(f.code in p for p in state.pinned),
                                  "answer": answers[i], "bound": (answers[i] == f.code) if probed else None})
            absent_out = [{"descriptor": d, "answer": a, "hallucinated": a is not None and a != "UNKNOWN",
                           "hallucinated_planted_code": a in all_codes}
                          for d, a in zip(mat.absent, answers[len(live):])]
            trace.write("score", round=rnd, probed=probed, facts=facts_out,
                        absent=absent_out if probed else [])
        trace.write("chain_end", status="ok", cost_usd=cost)
        return {"arm": arm["name"], "chain": chain, "status": "ok", "cost": cost}
    except Exception as e:  # recorded, the run continues with other chains
        trace.write("chain_end", status="error", error=repr(e), traceback=traceback.format_exc(), cost_usd=cost)
        return {"arm": arm["name"], "chain": chain, "status": "error", "error": repr(e), "cost": cost}
    finally:
        trace.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("config")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--arms", help="comma-separated arm names to run (default: all)")
    args = ap.parse_args(argv)
    cfg_path = Path(args.config)
    raw = cfg_path.read_bytes()
    cfg = json.loads(raw)
    arms = cfg["arms"]
    if args.arms:
        wanted = set(args.arms.split(","))
        arms = [a for a in arms if a["name"] in wanted]
    out = ROOT / cfg["out_dir"]
    jobs = [(a, c) for a in arms for c in range(cfg["chains_per_arm"])]
    if args.dry_run:
        for a in arms:
            m = material_params(cfg, a)
            mat = build_chain(cfg["seed"], cfg["rounds"], m["k_initial"], m["k_fresh"], m["lines_per_chunk"],
                              m["n_absent"])
            print(f"{a['name']}: {cfg['chains_per_arm']} chains x {cfg['rounds']} rounds, "
                  f"{len(mat.facts)} facts, chunk words={words(mat.chunks[0])}")
        print(f"{len(jobs)} chains total")
        return 0
    used = {a["backend"] for a in arms if a["compactor"] == "llm"} | ({cfg["probe"]["backend"]} if cfg.get("probe") else set())
    backends = {name: ChatBackend(cfg["backends"][name]) for name in sorted(used)}
    out.mkdir(parents=True, exist_ok=True)
    (out / "manifest.json").write_text(json.dumps({
        "config": cfg, "config_path": str(cfg_path), "config_sha256": hashlib.sha256(raw).hexdigest(),
        "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "python": sys.version, "platform": platform.platform(),
        "omp_gateway_versions": {n: getattr(b.transport, "version", None) for n, b in backends.items()},
    }, indent=2))
    budget = Budget(float(cfg.get("max_cost_usd", 1.0)))
    todo = [(a, c) for a, c in jobs if not chain_completed(out / a["name"] / f"{c:03d}.jsonl")]
    print(f"{len(jobs) - len(todo)} chains already complete, {len(todo)} to run", flush=True)
    results = []
    try:
        with ThreadPoolExecutor(max_workers=int(cfg.get("concurrency", 1))) as pool:
            futs = [pool.submit(run_chain, cfg, a, c, backends, budget, out / a["name"] / f"{c:03d}.jsonl")
                    for a, c in todo]
            for fut in as_completed(futs):
                r = fut.result()
                results.append(r)
                print(f"[{len(results)}/{len(todo)}] {r['arm']} chain {r['chain']}: {r['status']} "
                      f"${r['cost']:.4f} (run total ${budget.spent:.4f})" + (f" {r['error']}" if r.get("error") else ""),
                      flush=True)
    finally:
        for b in backends.values():
            b.close()
    failed = [r for r in results if r["status"] != "ok"]
    print(f"done: {len(results) - len(failed)} ok, {len(failed)} failed, spent ${budget.spent:.4f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
