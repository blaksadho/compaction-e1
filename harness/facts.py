"""Planted facts and synthetic operations-log chunks (notes/model.md §3).

A fact is (descriptor, code). Codes are 8 symbols over a 31-symbol alphabet that excludes the
confusable glyphs 0 O 1 I L (~39.6 bits), so a lost code cannot be re-guessed. Filler never contains
an 8-character run of uppercase code symbols: identifiers in filler are lowercase hex or digits.
"""

from __future__ import annotations

import random
import re
from dataclasses import asdict, dataclass

CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
CODE_LEN = 8
# A code-like token: 8 code symbols not embedded in a longer alphanumeric run.
CODE_TOKEN_RE = re.compile(r"(?<![A-Za-z0-9])[A-HJKMNP-Z2-9]{8}(?![A-Za-z0-9])")

KINDS = [
    "rollback token",
    "maintenance-window approval code",
    "on-call escalation PIN",
    "staging database password",
    "feature-flag override key",
    "deploy freeze exemption code",
    "backup restore passphrase",
    "vendor support contract ID",
    "break-glass access code",
    "canary release key",
]
SERVICE_A = ["billing", "search", "ledger", "auth", "media", "notify", "geo", "catalog", "fraud", "payout",
             "inventory", "session", "report", "audit", "pricing", "routing", "export", "ingest"]
SERVICE_B = ["worker", "api", "indexer", "gateway", "scheduler", "cache", "proxy", "sync", "store", "relay"]
LEVELS = ["INFO"] * 6 + ["DEBUG"] * 3 + ["WARN"] * 2 + ["ERROR"]
VERBS = ["request completed", "job finished", "cache refresh", "health check passed", "retrying upstream call",
         "connection pool resized", "batch flushed", "lease renewed", "config reloaded", "slow query logged",
         "rate limit applied", "shard rebalanced", "token refreshed", "queue depth sampled"]
PATHS = ["/v1/charge", "/v1/search", "/v2/items", "/healthz", "/v1/users", "/internal/sync", "/v1/export",
         "/v2/orders", "/metrics", "/v1/session"]


@dataclass(frozen=True)
class Fact:
    fact_id: int
    kind: str
    entity: str
    code: str
    round: int  # planting round t0
    line: int  # line index inside the planting chunk

    @property
    def descriptor(self) -> str:
        return f"the {self.kind} for {self.entity}"

    def to_json(self) -> dict:
        return asdict(self) | {"descriptor": self.descriptor}


def new_code(rng: random.Random, taken: set[str]) -> str:
    while True:
        code = "".join(rng.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        if code not in taken:
            taken.add(code)
            return code


def entities(rng: random.Random) -> list[str]:
    names = [f"{a}-{b}" for a in SERVICE_A for b in SERVICE_B]
    rng.shuffle(names)
    return names


def _ts(rng: random.Random, day: int) -> str:
    return f"2026-10-{day:02d}T{rng.randrange(24):02d}:{rng.randrange(60):02d}:{rng.randrange(60):02d}Z"


def filler_line(rng: random.Random, services: list[str], day: int) -> str:
    svc = rng.choice(services)
    pod = "".join(rng.choice("0123456789abcdef") for _ in range(6))
    verb = rng.choice(VERBS)
    extra = (f"path={rng.choice(PATHS)} status={rng.choice([200, 200, 200, 201, 204, 404, 429, 500, 503])} "
             f"latency_ms={rng.randrange(3, 2500)} trace=0x{rng.getrandbits(48):012x}")
    return f"{_ts(rng, day)} {rng.choice(LEVELS)} {svc}[pod-{pod}] {verb} {extra}"


def fact_line(rng: random.Random, fact: Fact, day: int) -> str:
    templates = [
        "{ts} NOTICE ops-bot: {kind} for {entity} is {code} (required before any change to {entity})",
        "{ts} NOTICE change-mgmt: issued {kind} {code} for {entity}; keep it for the rest of the incident",
        "{ts} NOTICE secrets-sync: {entity} {kind} set to {code}",
    ]
    return rng.choice(templates).format(ts=_ts(rng, day), kind=fact.kind, entity=fact.entity, code=fact.code)


@dataclass
class ChainMaterial:
    """Everything a chain needs, generated deterministically from one seed."""

    facts: list[Fact]
    chunks: list[str]  # chunks[t-1] is D_t
    absent: list[str]  # descriptors never planted (abstention probes)


def build_chain(seed: int, rounds: int, k_initial: int, k_fresh: int, lines_per_chunk: int,
                n_absent: int) -> ChainMaterial:
    """D_1 carries k_initial facts; D_t (t>=2) carries k_fresh new facts; facts are evenly spaced with jitter."""
    rng = random.Random(seed)
    ents = entities(rng)
    pairs = [(k, e) for e in ents for k in KINDS]
    rng.shuffle(pairs)
    n_facts = k_initial + k_fresh * (rounds - 1)
    if n_facts + n_absent > len(pairs):
        raise ValueError("not enough distinct descriptors")
    planted, absent_pairs = pairs[:n_facts], pairs[n_facts:n_facts + n_absent]
    services = ents[:24]
    taken: set[str] = set()
    facts: list[Fact] = []
    chunks: list[str] = []
    next_pair = 0
    for t in range(1, rounds + 1):
        k = k_initial if t == 1 else k_fresh
        if k > lines_per_chunk:
            raise ValueError("more facts than lines in a chunk")
        lines = [filler_line(rng, services, day=t) for _ in range(lines_per_chunk)]
        slots = sorted({min(lines_per_chunk - 1, int((j + rng.random()) * lines_per_chunk / k)) for j in range(k)})
        while len(slots) < k:  # jitter collisions: fill remaining free slots deterministically
            slots = sorted(set(slots) | {next(s for s in range(lines_per_chunk) if s not in slots)})
        for slot in slots:
            kind, entity = planted[next_pair]
            fact = Fact(len(facts), kind, entity, new_code(rng, taken), t, slot)
            facts.append(fact)
            lines[slot] = fact_line(rng, fact, day=t)
            next_pair += 1
        chunks.append("\n".join(lines))
    absent = [f"the {k} for {e}" for k, e in absent_pairs]
    return ChainMaterial(facts, chunks, absent)
