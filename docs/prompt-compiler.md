# Prompt Compiler

The agency prompt compiler audits project content, preserves unresolved evidence gaps, compiles selective brand context, creates typed asset specifications, serializes provider-ready prompts, and stops at `PROMPT_PACKAGE_READY`.

It never invokes a media-generation provider or creates final assets.

## Run

```bash
make prompt-compile
```

or:

```bash
python3 orchestrate_brand_pipeline.py compile-prompts \
  --input sample_prompt_request.json \
  --output /tmp/prompt-packages.json
```

Use `--json` to print the complete machine-readable result.

## Input contract

The request accepts project content, optional explicit claims, pre-retrieved evidence, canonical `brand_core`, asset requirements, and optional provider capability records. High-materiality unresolved API, metric, legal, or market claims emit research requests and prevent prompt-package readiness until evidence is supplied.

## Five audit passes

1. `INTAKE+CLAIMS`
2. `GAP_HUNT`
3. `RESEARCH_BACKFILL`
4. `VALIDATE`
5. `SYNTH+REPORT`

Retrieval cannot silently rewrite the original claims.

## Generation firewall

The successful terminal state is `PROMPT_PACKAGE_READY`. A package contains the canonical AssetSpec, PromptIR, selected brand context, generic master prompt, optional provider variants, validation result, hashes, and unresolved non-blocking gaps.

There is no generation, rendering, post-processing, publication, or provider-job submission path in this compiler.
