# E1 addendum B: Qwen2.5-32B pinned arms with the tag-tolerant parser

Addendum to `prereg/E1.md` and `prereg/E1-open.md`. Registered 2026-11-05, before any chain of this addendum ran
and after the Addendum A results were known (`notes/e1_results.md`). This addendum is therefore a follow-up to a
diagnosed failure, not a blind test. Its purpose is to measure what the pinned tier does for Qwen2.5-32B once its
answers are parsed as intended. The registered A3 result (pinned < plain) stands and is reported unchanged.

## Frozen artifacts

| item | value |
|---|---|
| `configs/e1_open_b.json` | SHA-256 `ec418a4242c1fe2f4e43d5436796bf7cbbfa2439ff6a2a7a7793306a25e98b8e` |
| `harness/compactors.py` | SHA-256 `238677e3aae8c3b98ab0d4a529c44f552f8180980d99b34d3e4aa826531eb4f8` (`prereg/E1.md`, Deviation 2); all other harness files unchanged |
| model, server, flags, concurrency | identical to `prereg/E1-open.md`; the same server process that ran Addendum A |

## Design

- Arms (30 chains each, 10 rounds, same seeds and material as all E1 arms): `qwen32b-B150-pinned-v2` (pinned budget
  60) and `qwen32b-B400-pinned-v2` (pinned budget 160). They are identical to the Addendum A pinned arms except for
  the parser.
- Comparison arms: `qwen32b-B{150,400}-plain` from Addendum A (`runs/e1-open`), paired by chain seed. Analysis
  runs on a directory of symlinks to the four arm directories, so `harness/analyze.py` is unchanged.

## Hypotheses and decision rules

- **B3.** $S_{\text{pinned-v2}}(10)-S_{\text{plain}}(10)>0$ at each $B$. Paired chain-bootstrap 95% CI (2000
  resamples, seed 1) must exclude 0. Two tests, Holm-adjusted.
- **Manipulation check (descriptive, reported first).** The fraction of compaction calls with no parseable
  `SUMMARY` section, and the fraction of initial facts pinned at round 1. If more than 10% of calls in an arm are
  still unparseable, B3 for that arm is reported as non-informative.
- **Descriptive.** $S(10)$ against the Addendum A pinned arms (old parser), and against the Haiku/Sonnet pinned
  arms; the number of pinned facts lost (expected 0).

## Operational rules

As in `prereg/E1-open.md`: retries up to 3 attempts per chain, monitoring limited to chain status and cost.

## Deviations

(none)

## Operational log

- **2026-11-06, interruption.** The Mac mini running the model went down abruptly at about 00:29: the server log
  stops mid-request, there is no shutdown record and no panic report, and the Mac rebooted at 06:39. The machine
  running the harness also rebooted (up since 01:44), so a shared power or network outage is likely; the cause is
  unconfirmed.
  - At that point 23 of 30 B150 chains had completed. 4 chains (`023`–`026`) had partial traces with no
    `chain_end` record.
  - The runner was resumed at 07:45 with the unchanged config. As for any incomplete trace, it reran those chains
    from the start, overwriting the partial traces.
  - This is not a deviation: no chain failed, no attempt was counted, and no outcome was inspected.
- **2026-11-06 ~10:10, 4 chain errors caused by the operator.**
  - The SSH tunnel to the model server was a process tied to the operator's session. It was replaced by a detached
    auto-reconnecting tunnel, so that the session could be closed.
  - The 4 requests in flight were cut, and `http.client.RemoteDisconnected` is not among the exceptions the frozen
    backend retries. So chains `qwen32b-B400-pinned-v2/004`–`007` ended with `status: error` on their first
    attempt.
  - Under the registered retry rule (at most 3 attempts per chain), the runner's next attempt reruns them from the
    start with unchanged material. All other chains continued.
  - Not a deviation; reported for completeness. No outcome was inspected.
