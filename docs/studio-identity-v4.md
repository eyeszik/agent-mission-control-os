# Studio Identity System Builder v4 — Repository Mapping

This document maps the user-supplied `STUDIO_IDENTITY_SYSTEM_BUILDER v4.0.0`
methodology into Agent Mission Control without creating a second runtime
authority.

## Canonical mapping

| Source concept | Repository owner |
| --- | --- |
| Company/project facts | `BrandCore`, evidence records, project state |
| Contextual design methodology | `pg.studio_identity.v4` GuidancePack |
| Core branding methodology | `pg.branding.core` GuidancePack |
| Deliverable intent | `AssetRequirement` |
| Provider-neutral specification | `AssetSpec` |
| Selective expert context | `PromptContext` |
| Canonical prompt instructions | `PromptIR` |
| Runtime provider capability | `ProviderCapability` |
| Validated handoff | `PromptPackage` |
| Prompt compiler terminal | `PROMPT_PACKAGE_READY` |

## Preserved source principles

The implementation preserves these source-level rules:

1. contextual fitness outranks universal aesthetics;
2. facts, proposals, decisions, and actions remain distinguishable;
3. rule authority and provenance are explicit;
4. advanced modules activate only when the task requires them;
5. 8/4 spacing and similar conventions remain heuristics, not universal law;
6. trend signals are scoped, evidence-sensitive, and reversible;
7. accessibility intent is separate from tested conformance;
8. AI product controls activate only for products containing AI behavior;
9. implementation claims require actual runtime/tool evidence;
10. specification completeness is distinct from production readiness;
11. numerical confidence is diagnostic only unless a calibrated method exists;
12. mandatory acceptance gates cannot be overridden by aggregate scores.

## Prompt-only boundary

This repository layer compiles prompt packages. It does not execute final image,
video, 3D, publication, deployment, purchase, or other external creative side
effects. External provider/model details must be verified dynamically and
passed through typed provider-capability records.

## Future pack expansion

The same routing substrate can accept dedicated packs for graphic design,
motion, video/cinematography, marketing, web design, web development, and
time-aware design-trend research. Those packs should contain domain-specific
methodology only; they should not duplicate runtime authority or canonical
project facts.
