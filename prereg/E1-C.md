# E1 addendum C: budget enforced by rewriting instead of truncation

Addendum to `prereg/E1.md`. Registered 2026-11-06, before any code for the new mode was written and before any
chain of this addendum ran.

The E1 results are known. Exploratory analyses of them (`notes/e1_results.md`, section "Mechanism of the entry
penalty"; `paper1/draft.md` §4.5) found that:
- the models place new facts later in the summary than incumbents;
- Sonnet overruns the word budget in 97% of B150 states;
- essentially all of Sonnet's erasures are the harness's hard truncation cutting the tail.

So the registered entry penalty ($d_{1w}<0$) may be an artefact of how the budget is enforced. This addendum tests
that directly. It is a follow-up to an exploratory finding, not a blind test. The registered E1 results stand
unchanged.

Spend approved by the user on 2026-11-06: about $10.40 estimated from E1 token counts, with a $15 cap.

## Frozen artifacts

| item | value |
|---|---|
| `configs/e1_c.json` | SHA-256 `d1ebedba41ad217b2cc027f0e1818a75d5fed3c336f77a13243fa9b70bd70a83` |
| `harness/analyze_c.py` (analysis, written and smoke-tested on E1 data before any Addendum C data) | SHA-256 `2e50296966c4b2c6007e8631c5d103db52ff6710ed0aaa804856b21bc52a8678` |
| `harness/analyze.py` (unchanged; imported by `analyze_c.py`) | SHA-256 `8af937df30e4caf24357bae9b092aca4a19433184ffbb5586438888ee2b616cd` |
| `harness/compactors.py`, `harness/run.py` | changed to add the rewrite mode specified below. The change is made only after Addendum B (`prereg/E1-open-B.md`) has finished, because that run depends on the current files. The new hashes go in `prereg/E1.md` (Deviation 3) and in the Deviations section here, before the first chain. |

## Rewrite mode (`enforce: "rewrite"`, `max_rewrites: 2`)

The specification is fixed here, before implementation.

1. The compaction call is identical to the plain arm: same system prompt, same user prompt with the
   "Hard limit: 150 words." rule, same backend and temperature 1.0. Its output is the **first draft**.
2. If the draft is at most $B=150$ words, it is the new state.
3. If it is longer, the harness sends a standalone **rewrite call** to the same backend, with the same system prompt
   and the user message:
   `Your summary below is {n} words, which is over the hard limit of {B} words. Rewrite it to at most {B} words.
   The agent will continue the incident using only your summary.` followed by the draft inside
   `<summary>…</summary>`. The original chunk is not resent.
4. Step 3 repeats on the latest rewrite, up to `max_rewrites` = 2 calls in total. If the last rewrite is still over
   $B$ words, it is hard-truncated to $B$ words, exactly as in the plain arm, and the state is flagged
   `fallback_truncated`.
5. Logging:
   - Every rewrite call is logged as a `call` record with `call: "rewrite"`.
   - The `state` record gains `rewrites` (calls used, 0–2) and `fallback_truncated`.
   - `truncated` and `untruncated` refer to the **first draft**, so `present_untruncated` means present in the
     first draft, and `overflow_rate` is the rate of first drafts over budget.
6. Arms with `enforce` = `truncate` or `record` are unaffected. Before the first chain, this is checked by
   replaying logged E1 responses through the new code and comparing states byte for byte.

## Design

- Arms, 30 chains each, 10 rounds, with the same seeds, material, probe and backends as `configs/e1.json`:
  `haiku-B150-plain-rewrite` and `sonnet-B150-plain-rewrite`. Concurrency 6.
- Comparison arms: `haiku-B150-plain` and `sonnet-B150-plain` from E1 (`runs/e1`), paired by chain seed.
  The only difference is the enforcement step. (The API model snapshots may have changed since 2026-11-04. This
  cannot be controlled and is reported as a limitation.)

## Hypotheses and decision rules

All CIs are 95% percentile chain-bootstrap intervals (2000 resamples, seed 1). P-values are bootstrap sign tests.
Computation: `python3 -m harness.analyze_c runs/e1-c runs/e1 --boot 2000 --seed 1 --json runs/e1-c/report.json`.

- **Manipulation check (reported first).** If more than 10% of an arm's states end in `fallback_truncated`, that
  arm's C1 and C2 are reported as non-informative, because tail truncation is then still substantially in effect.
- **C1 (truncation artefact).** $d_{1w}(\text{rewrite})-d_{1w}(\text{plain})$ per model, using a paired bootstrap
  in which one resample of chain seeds is applied to both arms.
  - The artefact account predicts $>0$: the entry penalty shrinks when the model chooses what to drop.
  - Two-sided test.
- **C2 (penalty persists).** $d_{1w}(\text{rewrite})$ per model.
  - $<0$ with Holm-adjusted $p<0.05$ means the entry penalty survives without tail truncation: the model itself
    drops new content first.
  - $>0$ means the model drops incumbents first when it chooses.
- **Family.** Holm–Bonferroni at $\alpha=0.05$ over the 4 tests (C1 and C2 × 2 models).
- **Registered interpretation.**
  - C1 > 0 and C2 not significant: the entry penalty in E1 is attributable to budget enforcement by truncation.
  - C2 < 0: models deprioritise new content even when choosing.
  - Both C1 > 0 and C2 < 0: partly both.
- **Floor rule.** As in `prereg/E1-open.md`: an arm with pooled $S(1)<0.10$ is non-informative.
- **Descriptive (no decision rule).**
  - $S(10)$ paired difference, rewrite − plain.
  - Among facts present in the first draft, the share of new facts among those the rewrite removes, against the new
    share of the draft.
  - Rewrite calls per state, draft overflow rate and cost.
  - The exploratory hazard model of `paper1/survival_models.py`, applied unchanged to the new arms.

## Operational rules

- **Order.**
  1. Addendum B finishes.
  2. The rewrite mode is implemented, and the hashes are logged.
  3. The replay check passes.
  4. A smoke run uses 1 chain per arm and 2 rounds under the separate output directory `runs/e1-c-smoke`. Smoke
     outputs are checked only for format and logging; no outcomes are computed.
  5. The full run starts.
- Retries: up to 3 attempts per chain, as in E1. Monitoring is limited to chain status and cost. Cap $15; if the
  cap stops the run, completed chains are analysed and the shortfall is reported.

## Deviations

(none)

## Implementation record (before the first chain)

- 2026-11-06, after Addendum B finished at 15:28. The rewrite mode was implemented and tested on a staged copy
  while Addendum B was running, without touching the registered files, then copied in.
- New SHA-256: `harness/compactors.py` `8bd036a34ac17c03205f027804aa45a5dc2913b0ba6e8cf947509b1fbdbe7dee` and
  `harness/run.py` `9e86884fd715fec7ba64ba54612339f0b726dea3886ce21ba2ca42f3ccfcbbbd` (`prereg/E1.md`, Deviation 3).
  `configs/e1_c.json`, `harness/analyze_c.py` and `harness/analyze.py` are unchanged from the hashes above.
- Replay check (step 6): 6,600 logged states reproduced exactly.
- Offline checks with a fake backend:
  - under budget: no rewrite;
  - over budget: one rewrite, with the registered prompt;
  - still over after 2 rewrites: truncation of the last rewrite, flagged `fallback_truncated`;
  - `truncate` and `record` unchanged;
  - a full fake chain logs `compact → rewrite → probe`, and the cost adds up exactly.
