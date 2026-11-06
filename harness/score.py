"""Scoring of a compacted state against planted facts (notes/model.md §3 table).

String scores need no model: present, present_norm, mutated (Levenshtein 1-2 to the code, not equal to any planted
code). The interpreter probe asks a model, given only the state, for the code of each descriptor (planted so far
plus never-planted ones); exact answer = bound, any code-like answer to a never-planted descriptor = hallucination.
"""

from __future__ import annotations

import re

from .facts import CODE_TOKEN_RE, Fact

_NORM_DROP = re.compile(r"[\s\-_.:/]")


def levenshtein(a: str, b: str, cap: int = 3) -> int:
    """Edit distance, early exit once every cell of a row exceeds `cap`."""
    if abs(len(a) - len(b)) > cap:
        return cap + 1
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, cb in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb))
        if min(cur) > cap:
            return cap + 1
        prev = cur
    return prev[-1]


def string_scores(state_text: str, facts: list[Fact], all_codes: set[str]) -> dict[int, dict]:
    norm = _NORM_DROP.sub("", state_text).upper()
    tokens = set(CODE_TOKEN_RE.findall(state_text))
    out = {}
    for f in facts:
        present = f.code in state_text
        near = sorted(t for t in tokens if t not in all_codes and 1 <= levenshtein(t, f.code, 2) <= 2)
        out[f.fact_id] = {"present": present, "present_norm": present or f.code in norm,
                          "mutated": bool(near) and not present, "mutants": near}
    return out


PROBE_SYSTEM = ("You answer questions using only the notes you are given. If the notes do not contain the answer, "
                "reply UNKNOWN. Never guess.")


def probe_prompt(state_text: str, descriptors: list[str]) -> str:
    qs = "\n".join(f"{i}. What is {d}?" for i, d in enumerate(descriptors, 1))
    return ("Notes:\n<notes>\n" + (state_text or "(empty)") + "\n</notes>\n\nQuestions:\n" + qs + "\n\n"
            "Answer every question on its own line as `<number>: <exact code>` or `<number>: UNKNOWN`. "
            "Output nothing else.")


_ANSWER_RE = re.compile(r"^\s*(\d+)\s*[:.)\-]\s*(.*?)\s*$")


def parse_probe(text: str, n: int) -> list[str | None]:
    """Per question: the first code-like token answered, 'UNKNOWN', or None if unanswered/unparseable."""
    answers: list[str | None] = [None] * n
    for line in text.splitlines():
        m = _ANSWER_RE.match(line)
        if not m or not 1 <= int(m.group(1)) <= n:
            continue
        i, body = int(m.group(1)) - 1, m.group(2).strip("`*\"' ")
        code = CODE_TOKEN_RE.search(body)
        answers[i] = code.group(0) if code else ("UNKNOWN" if "UNKNOWN" in body.upper() else body[:40] or None)
    return answers
