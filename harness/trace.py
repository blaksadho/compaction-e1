"""JSONL traces: one file per chain, one record per event. Record kinds:
chain_start, chunk, call, state, score, chain_end (see harness/README.md for fields)."""

from __future__ import annotations

import json
import time
from pathlib import Path


class ChainTrace:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._fh = path.open("w", encoding="utf-8")

    def write(self, kind: str, **fields) -> None:
        self._fh.write(json.dumps({"kind": kind, "ts": time.time(), **fields}, ensure_ascii=False) + "\n")
        self._fh.flush()

    def close(self) -> None:
        self._fh.close()


def read_trace(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def chain_completed(path: Path) -> bool:
    if not path.exists():
        return False
    last = None
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                last = line
    try:
        rec = json.loads(last) if last else {}
    except json.JSONDecodeError:
        return False
    return rec.get("kind") == "chain_end" and rec.get("status") == "ok"
