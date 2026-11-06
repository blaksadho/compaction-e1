"""Compactors: M_t = C_t(M_{t-1}, D_t) with |M_t| <= B words (notes/model.md §1, §3).

Arms (`instruction`):
- plain    : summarize for continuation.
- verbatim : plain + preserve identifiers/codes character for character.
- pinned   : the state has an exact tier P (pinned lines, carried forward by the harness, never re-written by the
             model: a noiseless sub-channel, Theorem B escape) and a lossy tier L = B - P written by the model.
             The model chooses which new lines to pin; the harness appends them while the tier has room.
- extract  : format-aware mechanical baseline (no model): keeps lines containing code-like tokens, newest last,
             evicting the oldest when over budget. Analogue of Compact-Bench's mechanical extraction.

Budget enforcement (`enforce`): 'truncate' cuts the lossy part to its word budget (theory-faithful |M_t| <= B);
'record' keeps the full output; 'rewrite' (plain/verbatim only, prereg/E1-C.md) asks the same model to rewrite an
over-budget draft to at most B words, up to `max_rewrites` calls, then truncates as a last resort. The first draft
is always logged as the untruncated output, so every scoring is available.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .backends import ChatBackend, Completion
from .facts import CODE_TOKEN_RE

SYSTEM = ("You are the context-compaction component of a long-running operations agent that is handling an "
          "ongoing incident. Your summary replaces the agent's working context: everything not in your summary "
          "is permanently unavailable to the agent.")

VERBATIM_RULE = ("Preserve every identifier, code, token, key, password and ID exactly, character for character, "
                 "together with what it belongs to.")


def words(text: str) -> int:
    return len(text.split())


def truncate_words(text: str, limit: int) -> str:
    """Keep the first `limit` whitespace-separated words, preserving line structure."""
    if limit <= 0:
        return ""
    out, n = [], 0
    for line in text.splitlines():
        toks = line.split()
        if n + len(toks) <= limit:
            out.append(line)
            n += len(toks)
        else:
            out.append(" ".join(toks[: limit - n]))
            break
    return "\n".join(out).strip()


@dataclass
class State:
    pinned: list[str]
    lossy: str

    def render(self) -> str:
        if not self.pinned:
            return self.lossy
        return "PINNED:\n" + "\n".join(self.pinned) + "\n\nSUMMARY:\n" + self.lossy

    def n_words(self) -> int:
        return words(self.render())


@dataclass
class CompactResult:
    state: State
    untruncated: str
    truncated: bool
    completion: Completion | None
    system: str | None
    user: str | None
    extra_calls: list[tuple[str, str, str, Completion]] = field(default_factory=list)  # (kind, system, user, comp)
    rewrites: int = 0
    fallback_truncated: bool = False


def _user_prompt(prev: State, chunk: str, budget: int, instruction: str, pinned_budget: int) -> str:
    parts = []
    if instruction == "pinned":
        used = sum(words(p) for p in prev.pinned)
        parts.append("Pinned facts (carried forward automatically and exactly; do not repeat them):\n<pinned>\n"
                     + ("\n".join(prev.pinned) or "(none)") + "\n</pinned>\n")
        prev_text = prev.lossy
        rule = (f"Output exactly two sections.\nPIN: zero or more new lines, one fact per line, to add to the pinned "
                f"facts. Pinned lines are kept verbatim for the rest of the task; the pinned tier has "
                f"{max(0, pinned_budget - used)} words of room left. Pin only what the agent must never lose.\n"
                f"SUMMARY: the updated summary, at most {budget - pinned_budget} words.")
    else:
        prev_text = prev.lossy
        rule = f"Hard limit: {budget} words."
        if instruction == "verbatim":
            rule += " " + VERBATIM_RULE
    parts.append("Previous summary (from earlier compactions):\n<summary>\n" + (prev_text or "(none)") + "\n</summary>\n")
    parts.append("New context since the previous summary:\n<context>\n" + chunk + "\n</context>\n")
    parts.append("Write the updated summary that replaces both. The agent will continue the incident using only "
                 "your summary" + (" and the pinned facts" if instruction == "pinned" else "") + ". " + rule)
    return "\n".join(parts)


_OPEN_PIN = re.compile(r"<\s*pin(?:ned)?\s*>", re.I)
_OPEN_SUMMARY = re.compile(r"<\s*summary\s*>", re.I)
_CLOSE_TAG = re.compile(r"<\s*/\s*(?:pin(?:ned)?|summary)\s*>", re.I)


def _parse_pinned(text: str) -> tuple[list[str], str]:
    """Split a PIN/SUMMARY response. Missing headers: everything is summary.

    Tag-form sections (`<PIN>…</PIN>`, `<pinned>…</pinned>`, `<SUMMARY>…</SUMMARY>`, any case) are read as the
    `PIN:`/`SUMMARY:` headers; some models answer in the tag style of the prompt (prereg/E1.md, Deviation 2)."""
    text = _CLOSE_TAG.sub("", _OPEN_SUMMARY.sub("SUMMARY:", _OPEN_PIN.sub("PIN:", text)))
    upper = text.upper()
    pin_at, sum_at = upper.find("PIN:"), upper.find("SUMMARY:")
    if sum_at < 0:
        return [], text.strip()
    summary = text[sum_at + len("SUMMARY:"):].strip()
    if pin_at < 0 or pin_at > sum_at:
        return [], summary
    pins = [ln.strip().lstrip("-*• ").strip() for ln in text[pin_at + len("PIN:"):sum_at].splitlines()]
    return [p for p in pins if p and p.lower() not in {"(none)", "none"}], summary


def _rewrite_prompt(text: str, budget: int) -> str:
    return (f"Your summary below is {words(text)} words, which is over the hard limit of {budget} words. Rewrite it "
            f"to at most {budget} words. The agent will continue the incident using only your summary.\n"
            f"<summary>\n{text}\n</summary>")


class LLMCompactor:
    def __init__(self, backend: ChatBackend, budget: int, instruction: str, pinned_budget: int = 0,
                 enforce: str = "truncate", max_tokens_factor: float = 3.0, max_rewrites: int = 2):
        if instruction not in {"plain", "verbatim", "pinned"}:
            raise ValueError(instruction)
        if instruction == "pinned" and not 0 < pinned_budget < budget:
            raise ValueError("pinned arm needs 0 < pinned_budget < budget")
        if enforce not in {"truncate", "record", "rewrite"}:
            raise ValueError(enforce)
        if enforce == "rewrite" and (instruction == "pinned" or max_rewrites < 1):
            raise ValueError("rewrite enforcement needs a non-pinned arm and max_rewrites >= 1")
        self.backend, self.budget, self.instruction = backend, budget, instruction
        self.pinned_budget, self.enforce, self.max_rewrites = pinned_budget, enforce, max_rewrites
        self.max_tokens = int(max_tokens_factor * budget) + 256

    def compact(self, prev: State, chunk: str) -> CompactResult:
        user = _user_prompt(prev, chunk, self.budget, self.instruction, self.pinned_budget)
        comp = self.backend.complete(SYSTEM, user, self.max_tokens)
        if self.instruction == "pinned":
            new_pins, lossy = _parse_pinned(comp.text)
            pinned = list(prev.pinned)
            used = sum(words(p) for p in pinned)
            for pin in new_pins:  # append in order while the exact tier has room; repeats of carried pins add nothing
                if pin in pinned:
                    continue
                if used + words(pin) <= self.pinned_budget:
                    pinned.append(pin)
                    used += words(pin)
            lossy_budget = self.budget - self.pinned_budget
        else:
            pinned, lossy, lossy_budget = [], comp.text.strip(), self.budget
        truncated = words(lossy) > lossy_budget
        extra: list[tuple[str, str, str, Completion]] = []
        fallback = False
        if truncated and self.enforce == "rewrite":
            while words(lossy) > lossy_budget and len(extra) < self.max_rewrites:
                rw_user = _rewrite_prompt(lossy, lossy_budget)
                rw = self.backend.complete(SYSTEM, rw_user, self.max_tokens)
                extra.append(("rewrite", SYSTEM, rw_user, rw))
                lossy = rw.text.strip()
            if words(lossy) > lossy_budget:
                fallback = True
                lossy = truncate_words(lossy, lossy_budget)
        elif truncated and self.enforce == "truncate":
            lossy = truncate_words(lossy, lossy_budget)
        return CompactResult(State(pinned, lossy), comp.text, truncated, comp, SYSTEM, user, extra, len(extra),
                             fallback)


class ExtractiveCompactor:
    """Mechanical baseline: retain lines with code-like tokens, FIFO-evict oldest beyond the word budget."""

    def __init__(self, budget: int):
        self.budget = budget

    def compact(self, prev: State, chunk: str) -> CompactResult:
        kept = [ln for ln in prev.lossy.splitlines() if ln.strip()]
        kept += [ln for ln in chunk.splitlines() if CODE_TOKEN_RE.search(ln)]
        full = "\n".join(kept)
        while kept and words("\n".join(kept)) > self.budget:
            kept.pop(0)
        return CompactResult(State([], "\n".join(kept)), full, words(full) > self.budget, None, None, None)
