"""Throwaway gate for prereg/E1-C.md step 6: replay logged compaction responses through the current LLMCompactor and
check that every logged state (text, pinned tier, truncated flag) and user prompt is reproduced byte for byte.

    python3 paper1/replay_check.py runs/e1 runs/e1-open runs/e1-open-b
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from harness.backends import Completion  # noqa: E402
from harness.compactors import LLMCompactor, State  # noqa: E402
from harness.trace import read_trace  # noqa: E402


class Replay:
    def __init__(self, responses: list[str]):
        self.responses = list(responses)
        self.users: list[str] = []

    def complete(self, system: str, user: str, max_tokens: int) -> Completion:
        self.users.append(user)
        return Completion(self.responses.pop(0), "stop", 0, 0, 0.0, 0.0, 1, "replay")


def check(path: Path) -> tuple[int, list[str]]:
    recs = read_trace(path)
    if not recs or recs[-1].get("kind") != "chain_end" or recs[-1].get("status") != "ok":
        return 0, []
    arm = recs[0]["arm"]
    if arm.get("compactor") != "llm":
        return 0, []
    calls = [r for r in recs if r["kind"] == "call" and r["call"] == "compact"]
    states = [r for r in recs if r["kind"] == "state"]
    be = Replay([c["response"] for c in calls])
    comp = LLMCompactor(be, arm["budget"], arm["instruction"], arm.get("pinned_budget", 0),
                        arm.get("enforce", "truncate"))
    chunks = [r["text"] for r in recs if r["kind"] == "chunk"]
    state, errs = State([], ""), []
    for i, (chunk, st) in enumerate(zip(chunks, states)):
        res = comp.compact(state, chunk)
        state = res.state
        if be.users[i] != calls[i]["user"]:
            errs.append(f"{path} r{i + 1}: user prompt differs")
        if state.render() != st["text"] or state.pinned != st["pinned"] or res.truncated != st["truncated"]:
            errs.append(f"{path} r{i + 1}: state differs")
    return len(states), errs


def main() -> int:
    n = bad = 0
    for run in sys.argv[1:]:
        for p in sorted(Path(run).glob("*/*.jsonl")):
            k, errs = check(p)
            n += k
            bad += len(errs)
            for e in errs[:3]:
                print(e)
    print(f"replayed {n} states, {bad} mismatches")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
