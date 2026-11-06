# E1 addendum A: open-weight 32B arms

Addendum to `prereg/E1.md`. Registered 2026-11-03, while `configs/e1.json` was running and before any chain of this
addendum ran. At registration only chain status and cost of the E1 API run had been seen, never outcomes (E1.md
operational rules). Design, outcomes, statistics and operational rules are those of `prereg/E1.md` unless stated
here.

## Why

The registered local arm (Qwen2.5-1.5B) hit a floor in the smoke run (no code retained at $B=150$), so it cannot
test the E1 hypotheses. A 32B model from the same family runs on available hardware (Mac mini M4 Pro, 64 GB) and
gives an open-weight compactor for the same confirmatory tests, plus a within-family size contrast with 1.5B.

## Frozen artifacts

| item | value |
|---|---|
| `configs/e1_open.json` | SHA-256 `52464c2e41ad0b235cb41df687b25059430d258ecb860963f2e48bb8bad8976a` |
| harness | unchanged; per-file hashes as in `prereg/E1.md` |
| model | `Qwen/Qwen2.5-32B-Instruct-GGUF` @ `a15e3cc10f8bbb2c0af6f8f1f34a32e3b060c09d`, Q4_K_M, 5 split files; SHA-256 listed below, verified against the Hugging Face LFS ids |
| server | Homebrew llama.cpp 0.7.0 (build 11669, commit 620d2225c), Metal; ``-c 32768 -np 4 --seed 1 -ngl 99` (4 slots × 8,192 tokens, the same per-request context as the 1.5B server)`; reached via SSH tunnel at `http://127.0.0.1:8082/v1` |

| split file | SHA-256 |
|---|---|
| `qwen2.5-32b-instruct-q4_k_m-00001-of-00005.gguf` | `403434e5c845452c013661d586b97d5a53cf207462d180a07c301eafa9390d05` |
| `qwen2.5-32b-instruct-q4_k_m-00002-of-00005.gguf` | `7371e5c5d717a8c20f526dbfce5d3f201dc3f02140d1c836314cd0756e02e8d7` |
| `qwen2.5-32b-instruct-q4_k_m-00003-of-00005.gguf` | `f023ccc294c3bd3b2eac5b2dd40dea3aa4ca1d06c7460ead67c36386cd62e8fc` |
| `qwen2.5-32b-instruct-q4_k_m-00004-of-00005.gguf` | `05fe76d941454390cd7aa0de3b342f83a1d1226a959479af85bbfae7cd93e771` |
| `qwen2.5-32b-instruct-q4_k_m-00005-of-00005.gguf` | `8c2e8ecc686129c37821bd9f3b3e251e6ae80deadd3d3348f7e3e84492a63c24` |

## Design

- Arms (30 chains each, 10 rounds, material and seeds identical to `configs/e1.json`, so chain $c$ is paired with
  chain $c$ of every Haiku/Sonnet arm): `qwen32b-B150-{plain,verbatim,pinned}` (pinned budget 60) and
  `qwen32b-B400-{plain,verbatim,pinned}` (pinned budget 160).
- Compactor sampling: temperature 1.0 and `seed: 1` in every request, as in the registered 1.5B arms. Interpreter
  probe: Haiku 4.5 at temperature 0, as in every E1 arm.
- Concurrency 4 (measured 1.33× the throughput of 1; ≈60 s per compaction call, so ≈1.5–2 days for 1,800 calls); budget cap $10 (probe calls only, about $0.02 per chain).

## Hypotheses and decision rules

**Confirmatory family A** (Holm–Bonferroni at $\alpha=0.05$ across these 4 tests, separate from the 8-test family
of `prereg/E1.md`): $d_{1w}$ and $d_{2w}$ for `qwen32b-B150-plain` and `qwen32b-B400-plain`, with the same
definitions, bootstrap (2000 chain resamples, seed 1) and sign p-values as E1.

**Predictions** (paired contrasts on shared seeds, 95% CI must exclude 0 in the stated direction):

- A3. $S_{\text{pinned}}(10)-S_{\text{plain}}(10)>0$ at each $B$.
- A4. $S_{\text{verbatim}}(10)-S_{\text{plain}}(10)>0$ at each $B$.
- A5. $S_{B=400}(10)-S_{B=150}(10)>0$ for plain arms.

**Floor rule** (fixed before data): an arm whose pooled $S(1)<0.10$ is declared at floor. Tests and predictions that
involve a floor arm are reported as non-informative, not as failures or successes. $d_{2w}$ also requires at least
20 facts at generation $\ge 3$ pooled across chains, otherwise it is non-informative.

**Descriptive.** Cross-model comparisons of $S(10)$ and $s_g$ against the Haiku/Sonnet arms with the same $B$ and
instruction (paired by chain; no decision rule, because models differ in more than one way). Size contrast
1.5B vs 32B at `B400-{plain,verbatim}`. Mutation and hallucination rates. Untruncated rescoring.

## Operational rules

- Run after `configs/e1.json` and `configs/e1_local.json` have finished, so the API run and the two local servers
  do not compete. Retry rule and exclusion as in E1 (at most 3 attempts per chain).
- Only chain status and cost are monitored until all 180 chains finish.

## Deviations

(none yet)
