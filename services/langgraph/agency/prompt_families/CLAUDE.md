# agency/prompt_families

_Guidance for this directory, moved verbatim from the root `CLAUDE.md` so it loads only when working here. Cross-cutting rules stay in the root file._

## Prompt families and v10 prompt OS — decomposed, not injected

`agency/prompt_families/` compiles reusable prompt families through the existing prompt compiler. It freezes an `InvariantSet`, varies declared axes, rejects concepts whose SHA-256 signature repeats the `ConceptLedger` (repairing the highest-level axis first, at most 3 passes), and terminates at `PROMPT_PACKAGE_READY`. `AssetRequirement` gained additive `exact_text` (blocking if not preserved verbatim), typed `references` and `series`. `ComputationEvidence` never upgrades a premise to VERIFIED. Methodology lives in the `pg.copy_content.v1`, `pg.attention.hooks.v1` and `pg.visual_prompting.v1` packs. The supplied spec is provenance only (`docs/imported-specs/`). CLI: `prompt-family`. Details: `docs/brand-content-visual-prompt-os.md`.
