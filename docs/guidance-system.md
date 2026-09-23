# Selective Guidance System

The prompt compiler now supports repository-owned expert guidance packs that are
selected per asset instead of being globally injected into every prompt.

## Authority boundary

Guidance is advisory methodology. It cannot replace or mutate:

1. runtime policy and security constraints;
2. verified evidence;
3. explicit project constraints;
4. canonical `BrandCore`;
5. `AssetRequirement` / `AssetSpec`;
6. mandatory accessibility requirements;
7. provider capability truth;
8. the `PROMPT_PACKAGE_READY` generation firewall.

The canonical relationship is:

```
verified state + asset intent + selected expert guidance
→ PromptContext
→ PromptIR
→ generic master prompt
→ verified provider adaptation
→ PROMPT_PACKAGE_READY
```

## Files

- `agency/guidance/models.py` — strict typed contracts.
- `agency/guidance/registry.py` — deterministic loader, duplicate-key checks,
  reference checks, and content hashing.
- `agency/guidance/router.py` — deterministic weighted routing.
- `agency/guidance/packs/branding.yaml` — first canonical methodology pack.

Pack files use the JSON-compatible subset of YAML 1.2. This is deliberate:
JSON is valid YAML 1.2, while the stdlib parser avoids aliases, custom tags,
implicit booleans, parser-specific coercion, and an additional runtime
dependency.

## Routing

Routing is based primarily on typed request metadata:

- prompt family;
- asset type;
- channel;
- required brand domains;
- required provider capabilities;
- task/objective tags.

The weighted score is normalized over the dimensions a pack actually declares,
then clipped to `[0, 1]`. Explicit exclusions win. Equal scores are broken by
pack id, making route selection reproducible.

Guidance sections can further declare `activate_when.any` and
`activate_when.all` predicates. A per-pack section count and character budget
prevents context flooding.

## Invalidation

The guidance selection hash includes registry version, registry hash, router
version, selected packs, selected sections, and selected content. A pack or
router change therefore changes downstream context and prompt hashes without
changing `BrandCore`.

## Future packs

The same substrate is intended for graphic design, design systems, UI/UX, web
design, web development, motion, video, storyboarding, marketing, advertising,
social, copywriting, presentation, print, packaging, creative technology, and
time-aware design-trend intelligence.

Trend packs must remain `TREND_INTELLIGENCE` and carry freshness/provenance
metadata before they are allowed to influence current-work recommendations.

## Agent-specific skills

Claude Code or other agent-specific skills may be generated as adapters over
these packs. They are not the canonical source; the repository packs remain the
source of truth.


## Studio Identity System Builder v4

`pg.studio_identity.v4` is a higher-order contextual methodology pack derived
from the project owner's `STUDIO_IDENTITY_SYSTEM_BUILDER v4.0.0`. It depends
on `pg.branding.core` and activates only for broader system work such as brand
identity systems, design systems, product UI systems, cross-platform identity,
campaign systems, brand-film systems, and implementation-aware design work.

It does **not** replace `BrandCore`, runtime policy, evidence state, approvals,
or provider capability truth.

The pack contributes selectively routed directive channels for:

- strategy and project-contract compilation;
- evidence, authority, provenance, and conflict resolution;
- identity-system methodology;
- trend intelligence;
- token architecture;
- product UI and accessibility;
- AI product experiences;
- asset planning;
- prompt compilation;
- engineering and operations;
- versioning and handoff;
- QA and evidence-based terminal status.

The pack preserves free-form `output_targets` for human-facing intent and uses
typed `directive_targets` for deterministic PromptIR routing.

### Dependency semantics

Guidance dependencies are resolved before final selection. If
`pg.studio_identity.v4` is selected, `pg.branding.core` is included even
when the core pack would not independently meet the relevance threshold.
Explicitly excluding a required dependency causes the dependent pack to be
rejected rather than silently running with missing methodology.

### Evidence-based acceptance

The compiler retains legacy confidence fields for backward compatibility and
diagnostics, but release/readiness decisions use explicit acceptance state:

- `PASS` — applicable mandatory prompt-package checks passed;
- `PARTIAL` — the package is usable but non-blocking evidence gaps or bounded
  validation repairs remain;
- `BLOCKED` — required canonical inputs or evidence prerequisites are absent;
- `FAIL` — prompt validation produced a blocking failure.

Numerical confidence never overrides a blocking acceptance criterion.

### Runtime provider discovery

Provider and model catalogs are intentionally outside the guidance packs.
Capabilities for image, video, speech, APIs, or deployment must be supplied as
current `ProviderCapability` evidence at runtime. This prevents transient
vendor/model details from becoming stale canonical brand methodology.

The repository therefore treats media providers, external API transports, and
terminal clients as optional execution surfaces downstream from prompt
compilation. The prompt compiler itself still stops at
`PROMPT_PACKAGE_READY`.
