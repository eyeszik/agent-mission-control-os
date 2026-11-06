# Prompt compilation benchmark

The optimization caches immutable verified guidance serialization by exact source bytes, with fresh caller-owned models. All eight pack files are still read on each load.

| Domain | Baseline median (ms) | Candidate median (ms) | Reduction | Identical serialized result |
|---|---:|---:|---:|---|
| graphic | 4.810 | 2.859 | 40.6% | yes |
| ui_ux | 10.157 | 7.995 | 21.3% | yes |
| storytelling | 4.629 | 2.602 | 43.8% | yes |
| branding | 4.352 | 2.444 | 43.8% | yes |
| marketing | 4.709 | 2.748 | 41.7% | yes |

Baseline: `d0c78fc78167702c77054d8529d7864b8aa6812c`. Candidate registry raw SHA-256: `bcb6e97f1749d01918f51e003815c9cb0e964c636fee701bc1f224b8b3f73927`.

Two 35-iteration trials per version and domain (70 warm samples per version/domain), in candidate/baseline/baseline/candidate order. Python 3.11.17. Only `compile_prompt_packages` is timed; imports and request construction are excluded. The first invocation is recorded separately and is not claimed as a warm speedup.

The runner was shared with regression work; these are descriptive local measurements, not a statistical significance or production latency claim. Different runtime overheads explain why UI/UX improves less than simpler prompts. All five full serialized outputs and prompt hashes matched both baseline trials. Wolfram independently recomputed percentage reduction, speedup ratios and absolute millisecond savings.

Reproduce with the same script and two checkouts:

```bash
git worktree add --detach /tmp/amc-prompt-baseline d0c78fc78167702c77054d8529d7864b8aa6812c
python scripts/benchmark_prompt_compiler.py --repo /tmp/amc-prompt-baseline --iterations 35 --output /tmp/baseline.json
python scripts/benchmark_prompt_compiler.py --iterations 35 --output /tmp/candidate.json
```

Repeat in reverse order, compare raw samples and result hashes, and record both source SHA-256 values. Dirty candidate checkouts are explicitly recorded, so a baseline Git HEAD is never misrepresented as the patched source. The [machine-readable summary](benchmarks/prompt-compiler.json) records source fingerprints and scope. No timing threshold is enforced in CI: behavioral/refusal tests avoid noisy-host false failures.

The compiler generates prompts and specifications. This benchmark does not measure rendered aesthetics, user task success, brand approval, WCAG conformance, marketing conversion, model latency or rendering speed. The [creative mission questions](creative-mission-questions.md) define how to investigate those separate outcomes.

Rollback: revert the guidance loader optimization and its single integrity pin together. Guidance packs, schemas, source hashes, policy and approval contracts need no migration. Cache contents are process-local and disposable; no new service or infrastructure is required.
