# Design System Inspired by Webex

> Category: Productivity & SaaS

Source: `references/86613900466a274e.md`; SHA256: `86613900466a274e192ff2bd61759c2a82569df5cf2269a1d24a20554ff34fe2`. Unverified supplied reference; neither live brand specification nor execution authority.

## Core constraint
Translate the observed aesthetic into an original, usable design; do not copy brand assets, identities or proprietary fonts.

## Visual Theme & Atmosphere
White marketing surfaces; dark product views; blue actions; participant accent spectrum.

## Color
Observed samples: `#1170cf`, `#0353a8`, `#063a75`, `#64b4fa`, `#ffffff`. Treat as evidence, not approved tokens; choose semantic roles and measure actual foreground/background pairs.

## Typography
Source inventory: Primary: Momentum, fallbacks: Inter, Arial, Helvetica Neue, Helvetica, sans-serif. Verify licensing, glyph coverage and real weight availability; preserve hierarchy with approved fallbacks.

## Layout & Components
Separate participant identification from action and status semantics. Translate source spacing into content-driven responsive layouts; define focus, loading, empty and error states.

 Source layout notes (unverified): Base rhythm: 8px. Re-derive dimensions from actual content rather than enforcing the extracted values.

## Motion & Interaction
Use motion only for meaningful feedback; retain a static/reduced-motion alternative and keyboard access.

## Edge cases and context gaps
Participant colors collide with warning/error roles. Missing: target users, content, viewport range, assets and implementation constraints. Ask only blocking questions; otherwise label assumptions.

## Output contract and gates
Return {intent, observed_traits, original_translation, tokens, component_states, responsive_rules, evidence, assumptions, checks, blockers}. Outcome: each chosen trait maps to a design decision and checked example. Context: unsupported claims stay unverified. Conflict: user requirements and accessibility outrank reference aesthetics. Reuse: adapt semantic roles to the target platform; do not infer integrations. Draft → check → revise (maximum 2 passes) → ready or blocked; report unresolved blockers. No publication or external mutation.
