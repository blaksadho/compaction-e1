# Repeated-compaction harness (E1/E2)

Standard library only (Python ≥ 3.11). Notation: `notes/model.md` §3.

```
python3 -m harness.run configs/smoke.json --dry-run   # job list, no calls
python3 -m harness.run configs/smoke.json             # run; completed chains are skipped on re-run
python3 -m harness.analyze runs/smoke --boot 2000     # S(g), s_g, contrasts, chain-bootstrap CIs
```

## Backends

| transport | what it talks to | setup |
|---|---|---|
| `omp-gateway` | `omp auth-gateway stdio` subprocess; uses the credentials stored in omp. OpenAI chat schema, exact system prompt, `temperature` honoured | `omp` on PATH and logged in |
| `http` | any OpenAI-compatible `/v1/chat/completions` (llama.cpp, vLLM, Ollama) | start the server, set `base_url` |

Local model used in the smoke run (CPU, 4 threads):

```
LD_LIBRARY_PATH=$HOME/.local/opt/libgomp/usr/lib/x86_64-linux-gnu \
  ~/.local/opt/llama.cpp/llama-b12065/llama-server \
  -m ~/.local/share/gguf/qwen2.5-1.5b-instruct-q4_k_m.gguf --host 127.0.0.1 --port 8081 -c 8192 -t 4 --seed 1
```

`libgomp1` was unpacked from the Debian package without root (`apt-get download libgomp1 && dpkg -x …`).
Cost is computed from `prices_per_mtok` in the config (neither transport reports cost).
Checked 2026-11-03 against omp's own accounting: Haiku 4.5 = [1, 5], Sonnet 4.6 = [3, 15] USD per Mtok.

## Protocol per chain

1. `facts.build_chain(seed + chain, …)`: `k_initial` facts in $D_1$, `k_fresh` new facts in each later chunk,
   `lines_per_chunk` log lines per chunk, `n_absent` never-planted descriptors. Same seed ⇒ same material in every
   arm (paired design).
2. Each round: compactor maps (state, chunk) → state; budget enforced by `enforce`: `truncate` (default) cuts the
   lossy tier to $B$ words; `record` keeps the full output; `rewrite` (plain/verbatim) asks the same model to
   rewrite an over-budget draft to at most $B$ words, up to `max_rewrites` (default 2) standalone calls, then
   truncates as a last resort (`prereg/E1-C.md`).
3. Score: string scores for every planted-so-far fact, then one interpreter probe (fixed backend, shuffled question
   order) over planted + absent descriptors.

## Trace records (`runs/<name>/<arm>/<chain>.jsonl`)

| kind | fields |
|---|---|
| `chain_start` | `arm` (full arm config), `chain`, `seed`, `rounds`, `material`, `facts[]` (`fact_id, kind, entity, code, round, line, descriptor`), `absent[]` |
| `chunk` | `round`, `text`, `n_words`, `facts` (ids planted in this chunk) |
| `call` | `call` (`compact`/`rewrite`/`probe`), `round`, `model`, `system`, `user`, `response`, `finish_reason`, `input_tokens`, `output_tokens`, `cost_usd`, `latency_s`, `attempts` |
| `state` | `round`, `text` ($M_t$ as scored), `n_words`, `pinned[]`, `untruncated_words`, `truncated`, `untruncated` (full first draft when it was over budget); rewrite arms add `rewrites` (0–2) and `fallback_truncated` |
| `score` | `round`, `probed`, `facts[]` (`fact_id, planted_round, generation, present, present_norm, mutated, mutants, present_untruncated, pinned, answer, bound`), `absent[]` (`descriptor, answer, hallucinated, hallucinated_planted_code`) |
| `chain_end` | `status` (`ok`/`error`), `cost_usd`, `error`, `traceback` |

`runs/<name>/manifest.json` stores the config, its SHA-256, start time, Python/platform and the omp version.

## Arms

`instruction` ∈ `plain`, `verbatim`, `pinned` (needs `pinned_budget` $P<B$: exact tier carried by the harness,
lossy tier $B-P$; the response is parsed from `PIN:`/`SUMMARY:` headers or the equivalent `<PIN>`/`<pinned>`/
`<SUMMARY>` tags, and exact repeats of carried pins are skipped), or `compactor: "extract"` (format-aware
mechanical baseline, no model).
