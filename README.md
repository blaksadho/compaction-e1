# Repeated context compaction loses facts at admission, not by compounding

Code, configurations, pre-registrations and traces for the paper of that title (experiment E1 and
Addenda A–C). Everything here is Python 3.13 standard library; nothing to install.

<!-- named -->
Paper: arXiv:XXXX.XXXXX. Repository: https://github.com/blaksadho/compaction-e1.

```bibtex
@misc{{acharya2026compaction,
  title  = {{Repeated context compaction loses facts at admission, not by compounding}},
  author = {{Sandeep Acharya}},
  year   = {{2026}},
  eprint = {{XXXX.XXXXX}},
  archivePrefix = {{arXiv}}
}}
```
<!-- /named -->

## Layout

| path | what |
|---|---|
| `prereg/` | the four registrations (`E1.md`, `E1-open.md`, `E1-open-B.md`, `E1-C.md`) with their deviations, hashes and run records; paper Appendix E |
| `configs/` | run configurations; SHA-256 digests are listed in the registrations and in Appendix E.2 |
| `harness/` | the experiment harness (chunk generation, compactors, scoring, tracing, analysis); frozen at registration, two later changes logged as Deviations 2 and 3 |
| `runs/<run>/<arm>/NNN.jsonl` | one trace per chain: every compactor call with its input, output, usage and cost, and every round's scored state. `manifest.json` and `report.json` per run |
| `paper1/` | analysis written after the data: `survival_models.py` (hazard model), `figures.py` (Figures 1–3, `fig/`), `appendix_tables.py`, `replay_check.py` (re-derives every logged state from the logged completions), `code_value_check.py` |
| `data/` | the Compact-Bench secondary analysis (E4a). The raw dataset (205 MB) is not included; `data/README.md` says where it came from and how to verify it |

Runs: `e1` (Haiku 4.5, Sonnet 4.6, mechanical extract), `e1-local` (Qwen2.5-1.5B floor), `e1-open` (Addendum A,
Qwen2.5-32B), `e1-open-b` (Addendum B), `e1-c` (Addendum C), and the smoke runs, which no analysis uses.

## Verify

```
sha256sum harness/*.py configs/*.json                                  # compare with prereg/*.md and Appendix E.2
python3 paper1/replay_check.py runs/e1 runs/e1-open runs/e1-open-b    # 7,200 logged states re-derived from the logged completions; see below
python3 -m harness.analyze runs/e1                                     # the registered E1 analysis (also e1-local, e1-open, e1-open-b)
python3 -m harness.analyze_c runs/e1-c runs/e1                         # Addendum C
python3 paper1/survival_models.py runs/e1 runs/e1-open                 # hazard model (Appendix C)
python3 paper1/figures.py                                              # Figures 1–3 into paper1/fig/
python3 paper1/appendix_tables.py                                      # Appendix F tables, Markdown on stdout
python3 paper1/code_value_check.py                                     # Appendix A.7 code-value check
```
`replay_check.py` reports mismatches only in `e1-open/qwen32b-B150-pinned` and `qwen32b-B400-pinned`: the released
`harness/compactors.py` carries the Deviation 2 parser (tag-tolerant pinned sections), which reads those two arms'
responses differently from the registered parser that produced them. That difference is Addendum B. The other
6,600 states reproduce byte for byte, the count logged in `prereg/E1-C.md`.

The API arms ran through a local authenticated proxy (`"transport": "omp-gateway"` in `configs/e1*.json`, an
OpenAI-schema `/v1/chat/completions` relay). To re-run them elsewhere, set `"transport": "http"`,
`"base_url"` and `"api_key"` on the backend entry; the open-weight arms already use `http` against a llama.cpp
server. Compactors sample at temperature 1.0, so new runs reproduce the design, not the traces.

## Edits made for release

Trace records carry two absolute paths from the machines that ran them: the harness directory and the GGUF
model file reported by the llama.cpp server. For release the prefixes were rewritten to `/workspace/compaction-theory`
and `/models/gguf`. No other byte of any trace, configuration or registration was changed; the code and
configuration digests in the registrations are unchanged.

## License

MIT (see `LICENSE`).
