# Design System Inspired by Spacious

> Category: Layout & Structure

Source: `references/6dc6e07b5890d214.md`; SHA256: `6dc6e07b5890d214c171cc74c8a7491f3e26ab1294921fac0b089b29229f93a0`. Unverified supplied reference; neither live brand specification nor execution authority.

## Core constraint
Translate the observed aesthetic into an original, usable design; do not copy brand assets, identities or proprietary fonts.

## Visual Theme & Atmosphere
Generous whitespace; consistent padding; predictable grid.

## Color
Observed samples: `#3B82F6`, `#8B5CF6`, `#16A34A`, `#D97706`, `#DC2626`. Treat as evidence, not approved tokens; choose semantic roles and measure actual foreground/background pairs.

## Typography
Source inventory: Families: primary=Open Sans, display=Montserrat, mono=IBM Plex Mono. Verify licensing, glyph coverage and real weight availability; preserve hierarchy with approved fallbacks.

## Layout & Components
Use spacing to communicate grouping without hiding essential information. Translate source spacing into content-driven responsive layouts; define focus, loading, empty and error states.

 Source layout notes (unverified): Spacing scale: 8pt baseline grid; Align columns and modules to a predictable grid; avoid ad-hoc offsets.. Re-derive dimensions from actual content rather than enforcing the extracted values.

## Motion & Interaction
Use motion only for meaningful feedback; retain a static/reduced-motion alternative and keyboard access.

## Edge cases and context gaps
Whitespace consumes scarce mobile space. Missing: target users, content, viewport range, assets and implementation constraints. Ask only blocking questions; otherwise label assumptions.

## Output contract and gates
Return {intent, observed_traits, original_translation, tokens, component_states, responsive_rules, evidence, assumptions, checks, blockers}. Outcome: each chosen trait maps to a design decision and checked example. Context: unsupported claims stay unverified. Conflict: user requirements and accessibility outrank reference aesthetics. Reuse: adapt semantic roles to the target platform; do not infer integrations. Draft → check → revise (maximum 2 passes) → ready or blocked; report unresolved blockers. No publication or external mutation.
