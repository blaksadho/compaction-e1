# E4 raw data

Downloaded 2026-11-03 for experiment E4, a secondary analysis of public datasets. The goals are (1) cascade-size tail distributions, testing $P(N>n)\sim n^{-1/2}$, and (2) per-compaction-boundary fact/detail loss.

```
data/
├── README.md                      (this file)
├── inspect_compact_bench.py       stdlib-only schema/summary dump (run from compaction-theory/)
└── raw/
    ├── compact-bench/             204 MB
    │   ├── hf/                    HF dataset snapshot (202 MB, every file, SHA256SUMS verified OK)
    │   ├── code/                  shallow git clone of the benchmark code (444 KB)
    │   ├── hf_api.json            HF API metadata at download time
    │   ├── hf_tree.json           HF recursive file listing (80 files, 211,425,108 bytes)
    │   ├── paper_2610.31710_abs.html
    │   └── paper_2610.31710_html.html
    └── khanal-reliability/        1.4 MB: paper only. NO episode logs (see §2)
        └── paper/                 arXiv LaTeX source (*.tex, main.bbl), PDF v1, abs + HTML pages
```

---

## 1. Compact-Bench (arXiv:2610.31710)

"Compact-Bench: Measuring What Context Compaction Costs Long-Horizon Coding Agents", arXiv submission dated 2026-10-22.

| item | value |
|---|---|
| HF dataset | https://huggingface.co/datasets/caijanfeng/compact-bench |
| HF revision downloaded | `ff20521e6a2293ba74317efb076f0c338ca5fb6b` (lastModified 2026-10-20T13:44:41Z), release `public-v1` (`release.json`) |
| download URL pattern | `https://huggingface.co/datasets/caijanfeng/compact-bench/resolve/<sha>/<path>` |
| code repo | https://github.com/cai-jianfeng/compact-bench, commit `9dd9a3f5a91b2de5acdf56cee2fc0a4d16dcefc5` (2026-10-20) |
| license | Apache-2.0 for the benchmark's own contributions. Snapshots, issue texts and quoted code keep their upstream licenses (`hf/NOTICE.md`) |
| redaction | 112 credential strings replaced consistently. The release notes say this is "not exhaustive anonymization" |
| format | JSON / JSONL only, no parquet. The HF viewer is disabled (`viewer: false`), so datasets-server conversion was neither needed nor available |
| skipped | nothing. Total size is 211 MB, below the 5 GB cap |

### Files

| path | bytes | records | content |
|---|---:|---:|---|
| `hf/e1/instances.json` | 570,655 | 35 | Task Preservation track: SWE-bench task metadata |
| `hf/e1/H3/*.H3.json` | 1,061,123 (35 files) | 1 per file | frozen pre-compaction history `H` and tool log `tlog_a` |
| `hf/e1/d3snap/*.tar.gz` | 135,109,945 (35 files) | – | working-directory snapshots, one per task |
| `hf/e1/prepass24.txt` | 542 | 24 ids | historical cohort list |
| `hf/e2/sessions.jsonl` | 69,691,869 | 146 | **Recurring-Detail Retention**: one boundary per session plus annotated recurring details ("atoms") |
| `hf/e3/chains.jsonl` | 4,964,076 | 106 chains / 224 boundaries | **Production-Chain Retention**: summaries recorded at real, repeated production compaction boundaries |

The filename prefixes e1/e2/e3 are internal track IDs. They map to Task Preservation, Recurring-Detail Retention and Production-Chain Retention, in that order.

### Schema: `e3/chains.jsonl` (the main E4 input)

| field | type | notes / example |
|---|---|---|
| `sess` | str | chain id, e.g. `"cid:1ebb50d5bb5c780c"` |
| `client` | str | harness that ran the session: `kimi-code-cli` 68, `claude-code` 28, `other` 10 |
| `n_bounds` | int | number of compaction boundaries: 2 → 96 chains, 3 → 8, 4 → 2 (224 in total) |
| `per_k[]` | list | one entry per boundary |
| `per_k[].k` | int | 1-based boundary index. Counts: k=1: 106, k=2: 106, k=3: 10, k=4: 2 |
| `per_k[].marker` | str | how the boundary was detected: `token_drop` 115, `kimi` 77, `claude` 29, `kimi_v2` 3. The paper's sessionizer uses either "a new compaction marker or a token drop below half the preceding count". `kimi`/`claude` are therefore client compaction markers, and `token_drop` is the token-count heuristic |
| `per_k[].form` | str | `embed` 134, `instr` 90. [INFERENCE] `instr` means the summary was produced in response to a compaction-instruction request. `embed` means the summary was found embedded in the next request's context. The repo does not document this field |
| `per_k[].S_k` | str | the production summary text actually used after boundary k. It is always an LLM summary written by the live harness |
| `per_k[].atomsF` | dict kind→list[str] | recurring details used in the **following ≤5 real requests**. Kinds are `path, sha, pr, url, kv, error, ip`. Empty at 84/224 boundaries, so only 140 boundaries are scoreable (106/27/6/1 at k=1..4, matching the paper) |
| `per_k[].done_files` | list[str] | files already written before the boundary. Used by the "triplet" error (a finished file reappears as pending in `S_k`). Non-empty at 16 boundaries |

No summarizer model name is recorded. Only `client` is available.

Example record (`sess` cid:1ebb50d5bb5c780c, with `S_k` and lists truncated):
```json
{"sess": "cid:1ebb50d5bb5c780c", "client": "kimi-code-cli", "n_bounds": 2,
 "per_k": [
  {"k": 1, "marker": "kimi", "form": "instr",
   "S_k": "I'm at a clean stopping point: the UI plan (phases A–D) is fully shipped and verified, and the roadmap Phases 1–5 are done except key-blocked items. ...",
   "atomsF": {"path": [".next/dev/server/app/commodities/page_client-reference-manifest.js", "..."],
              "sha": ["007e4b2", "14a54acaa863", "50e594441140"], "pr": ["131110", "667284"], "kv": ["API_ROUTES=[", "..."]},
   "done_files": []},
  {"k": 2, "marker": "token_drop", "form": "embed",
   "S_k": "You are Kimi Code CLI, an interactive general AI agent running on a user's computer. ...",
   "atomsF": {"path": ["..."], "sha": ["007e4b2", "..."], "pr": ["131110", "151515", "667284"], "url": ["http://localhost:3001\\", "..."], "kv": ["..."]},
   "done_files": []}]}
```

Official per-boundary metric (`code/harness/e3_score.py`): $R_k = |\{v\in \text{atomsF}_k : v \text{ is a substring of } S_k\}| \,/\, |\text{atomsF}_k|$. This is case-sensitive literal matching. `ratio_last_first` = $R_{\text{last}}/R_1$. Recomputed means from the downloaded file: $R_1=0.157$ (n=106), $R_2=0.199$ (27), $R_3=0.049$ (6), $R_4=0.018$ (1). This matches the paper's figure of 15.7% at the first boundary. Those means include prompt-only boundaries (§3); on summary boundaries alone, $R_1=0.173$ (80), $R_2=0.324$ (8), $R_3=0.028$ (1).

### Schema: `e2/sessions.jsonl`

| field | type | notes / example |
|---|---|---|
| `sample_id` | str | `"yi-1411fa3325861a-6"` |
| `sess` | str | session hash (146 distinct) |
| `client` | str | `kimi-code-cli` 73, `claude-code` 50, `opencode` 14, `other` 3, `fake-kimi-cli` 2, `kilocode` 2, `fake-claude-code` 1, `hertz` 1. The three `fake-*` sessions are simulated |
| `boundary_idx` | int | zero-based request index of the *artificial* boundary, ⌊0.65·n_reqs⌋ (most common values: 5, 6, 7) |
| `n_reqs` | int | requests in the session |
| `H[]` | list of messages | pre-boundary history: 27,868 messages in total. Fields: `role` (system/user/assistant/tool), `content` (str or content-block list), `tool_calls`, `tool_call_id` (e.g. `"Bash:0"`), `loss` (0/1; equals 1 exactly on the 11,737 assistant messages. [INFERENCE] a training-style mask, not an error flag) |
| `F_len` | int | future-window length cap in characters (450000, 600000, …) |
| `atoms[]` | list of `{kind, value}` | recurring details that are present before the boundary **and** needed in the future window. 9,330 in total: path 4606, url 1631, sha 1220, kv 1083, pr 315, error 280, ip 195. Example `{"kind": "path", "value": "./ADR-FORMAT.md"}` |
| `n_atoms` | int | equals `len(atoms)` |
| `future_req_ids` | list[str] | ids of 3–8 future requests. The payloads themselves are private and not released |

This track contains **no summaries**. To use it, run a compactor yourself: `code/harness/e2_score.py` applies 5 production prompts (claude, codex, opencode, gemini, kimi in `cb_common.PROMPTS`) through a model API, plus `anchor_index`, a mechanical regex-extraction baseline that needs no LLM (`cb_common.anchor_baseline`). Recall is the fraction of `atoms` that appear literally in the summary S. The paper reports at most 16.0% recall for LLM summaries versus 79.1% for mechanical extraction.

### Schema: `e1` (Task Preservation)

`instances.json` has 35 entries with SWE-bench fields: `repo, instance_id, base_commit, patch, test_patch, problem_statement, hints_text, created_at, version, FAIL_TO_PASS, PASS_TO_PASS, environment_setup_commit, difficulty`. `H3/<id>.H3.json` is `{"H": [ {role, content} … ], "tlog_a": [[tool, arg], …]}`, a single frozen boundary per task. Outcomes require rerunning the agent (model API, Linux and `patch`). There is only one boundary per task, so this track is of little direct use for E4.

---

## 2. Khanal, Tao, Zhou: "Beyond pass@1" (arXiv:2603.29231)

**Episode logs: no public release was found as of 2026-11-03.** The paper claims a release. The conclusion says "We release all code, tasks, trajectories, and evaluation results publicly". Appendix B says "the publicly released results repository … includes JSONL episode logs for all 23,392 episodes, per-task aggregates, and the analysis scripts". However, no URL appears anywhere in the abstract page, HTML, PDF or LaTeX source. The only URLs in the source are openrouter.ai, wandb.ai, matplotlib and the NeurIPS style file.

Places searched without finding the release:
- https://arxiv.org/abs/2603.29231 (v1 is the only version; the Comments field is empty), https://arxiv.org/html/2603.29231, https://arxiv.org/pdf/2603.29231v1, https://arxiv.org/src/2603.29231 (searched all .tex files for release, github, repository, zenodo and http)
- HF: https://huggingface.co/api/papers/2603.29231 (no linked repo), https://huggingface.co/api/arxiv/2603.29231/repos (`{"models":[],"datasets":[],"spaces":[]}`), dataset searches for `reliability`, `meltdown`, `long-horizon`, `khanal`, `pass1`, and author queries `ak-pydev`, `aadityakhanal`, `AadityaKhanal`, `khanala1`, `aaditya-khanal` (all empty)
- GitHub repository search: "reliability long-horizon agents meltdown", "meltdown onset point", "pass@1 reliability science", "reliability decay curve", "variance amplification factor", "graceful degradation score agent", "khanal reliability", "long-horizon reliability benchmark 396", "reliability-bench agents openrouter"
- Candidate author accounts `AadityaKhanal`, `ak-pydev` (NKU projects; likely the first author), `ak-codes-py` and `Aadityakhanal786`: none has a matching repo. `github.com/ak-pydev/beyond-pass1` and `/reliability-bench` return 404. The personal-website repo has no link.
- Zenodo API queries for "Beyond pass@1" and "reliability science framework": no matching record
- alphaxiv.org/abs/2603.29231, emergentmind MOP topic page, benchflow-ai/awesome-evals note, paperswithcode API: no code or data link
- `github.com/moro3one/floorline` implements pass^k and meltdown-onset metrics on JSONL but is a third-party tool with no paper data

**Request sent 2026-11-03** to khanala1@nku.edu (cc taoy1@, zhouj2@nku.edu) asking for the JSONL episode logs, for a secondary analysis of failure dynamics in long-horizon agents. Awaiting reply.

`raw/khanal-reliability/paper/` holds the paper itself, kept as the specification of the logs for when they become available:
- 396 tasks: 4 duration buckets (short / medium / long / very long) × 3 domains (SE software engineering, WR agentic web research, DP multi-file document processing), 33 tasks per cell
- 10 models via OpenRouter: Llama 3.1 8B, Mistral Nemo, Mistral Small 3.2, Qwen3 30B, Qwen3 32B, Llama 3.3 70B, MiniMax M2.5, GLM-4.5 Air, Kimi K2.5, DeepSeek V3
- 2 scaffolds: ReAct and Mem (`add_to_memory` scratchpad injected into the system prompt); k=3 repeats; 23,392 episodes
- logged per step: "tool calls, arguments, results, timestamps, token counts"
- run settings: max 70 steps, tool results truncated to 4,000 characters, a 120k-token per-episode input budget, a loop-detection abort (same tool+args ≥3 times within 6 steps), max 3 nudges
- **No compaction or summarization in either scaffold.** The paper does not describe context truncation; overflow is handled by the token budget abort
- **MOP definition** (`03_framework.tex`):
  - $p_t$ is the tool-call frequency over the window $[t-w,t]$ with $w=5$, and $H(t)=-\sum p_t\log p_t$
  - MOP is the first step $t^*$ with $H(t^*)>\theta_H$ and $H(t^*)-H(t^*-w)>\delta$; MOP $=\infty$ otherwise
  - the thresholds are auto-calibrated to $H^*=1.711$, $\delta^*=0.000$ on 1,590 short-horizon baseline episodes
  - MOP is therefore a label derived from tool-name sequences only, not from errors

---

## 3. Mapping to E4

### (2) Per-compaction-boundary detail loss / survival: Compact-Bench e3 (available)

- **Boundary index**: `per_k[].k`. **Compactor**: always the live production LLM summary, given by `S_k`, `client` and `marker`. `form` distinguishes `instr` from `embed`. There is no mechanical compactor in e3.
- **Per-boundary survival** of the details needed next: $R_k$ as computed in `e3_score.py`, i.e. the fraction of `atomsF[k]` contained literally in `S_k`.
- **Boundary validity (found 2026-11-03).** 109 of the 224 `S_k` texts, all `marker=token_drop, form=embed`, are the harness system prompt and nothing else ("You are Kimi Code CLI …", "You are Claude Code …"). Within a chain, successive such texts are identical except for the embedded session-start timestamp. These boundaries are therefore new sessions or subagent starts, not compactions, and an atom "kept" in them is static project information. The 90 `instr` boundaries are summaries; of the other 25 `embed` boundaries, 23 begin "The conversation so far has been compacted to …", one is a user message and one a `<system-reminder>` (kept in the summary set by the script's prefix rule).
- **Per-atom transitions across successive boundaries**: `data/e4a_boundary_survival.py` (output `data/e4a_report.json`). Every atom in `atomsF[k]` is used after boundary k, so it is back in context at compaction k+1, and dropped atoms can return. The absorbing erasure model ($S(g)=\prod s_g$) does not apply; the identifiable quantity is inertia $s-r$, with $s=P(\text{in }S_{k+1}\mid\text{in }S_k)$ and $r=P(\text{in }S_{k+1}\mid\text{not in }S_k)$. Only **4 chains (157 atoms)** have real summaries at two consecutive scoreable boundaries: $s=0.80$ [0.50, 1.00], $r=0.23$ [0.10, 0.49], inertia $0.57$ [0.01, 0.83] (chain bootstrap, 2000 reps; 4 clusters, so the interval is not reliable). The earlier pooled figure "283 of 1,492 retained atoms survive (≈19%)" was dominated by prompt-only boundaries and is withdrawn.
- **Kinds** (`path, sha, pr, url, kv, error, ip`) allow stratified loss rates.
- **Mechanical vs LLM compactor contrast**: on e2, `anchor_index` gives mechanical extraction offline. LLM-prompt summaries require API calls through `e2_score.py`. e2 has a single boundary per session, so it gives one-shot loss only.

### (1) Cascade sizes N and $P(N>n)$: no suitable data yet

- The Khanal logs are the intended source but are **unreleased**, so no cascade size N can be computed from them today. If they appear, N would be defined per episode from the step-level tool-call sequence: the run length of failing or erroring tool results after onset, or the steps from MOP $t^*$ to episode end, with loop-detector and budget aborts as censoring. MOP itself needs only the tool names, and the paper's thresholds can be reapplied. Horizon category is the duration bucket, and model and scaffold come from the run config. Error and retry flags would have to be parsed from tool results, which depends on the unseen schema.
- Compact-Bench has no step-level error or outcome labels per boundary chain. Proxies:
  - e2 `H[]` gives step-level tool traces (`tool_calls`, `tool_call_id`, `role: tool` content) for 146 real sessions, but only *before* one boundary, with no explicit error flags; errors would have to be regex-mined from tool output. The `error` atoms (280) are error-type strings that recur, not per-step failure flags.
  - e3 chains have at most 4 boundaries (96/106 have exactly 2), far too short for tail estimation over boundaries.

### Gaps and limitations

- No released Khanal episode logs: the cascade-tail part of E4 is blocked on this dataset.
- Neither the Khanal scaffolds nor e1/e2 contain multi-boundary compaction events. Only e3 does, at k ≤ 4, with sample sizes shrinking quickly with k (106/27/6/1 scoreable).
- Retention is literal substring matching. Paraphrased retention counts as a loss.
- `atomsF` only covers details that the next ≤5 requests actually used. That is a selection effect: unused details are unobserved.
- The summarizer model behind `S_k` is not recorded (only `client`). Some `token_drop`/`embed` `S_k` texts begin with the harness system prompt (see example k=2), so `S_k` may include more than the summary itself.
- e2 future payloads (`future_req_ids`) are private. Only the extracted atoms are released.
