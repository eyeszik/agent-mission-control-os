# Design System Inspired by Bento

> Category: Layout & Structure

Source: `ee9bf8da9e4f7615.md`; SHA256: `ee9bf8da9e4f7615e22d4417a39540891b9312ce63b318ce480dfb6441ca8f59`. Status: attached-source observations; not live-verified authority. Original retained separately.

## Core constraint
Translate modular card hierarchy whose grouping reflects actual content relationships into original design; validate usability and identity rights before implementation.

## 1. Visual Theme & Atmosphere
Source direction: modular card hierarchy whose grouping reflects actual content relationships.

## 2. Color
Observed: Primary: #FAD4C0 — Token from style foundations. Secondary: #80A1C1 — Token from style foundations.

## 3. Typography
Observed: Scale: 12/14/16/20/24/32. Headings should carry the style personality; body text should optimize scanability and contrast.

## 4. Spacing & Grid
Observed: Spacing scale: 4/8/12/16/24/32. Align columns and modules to a predictable grid; avoid ad-hoc offsets.

## 5. Layout & Composition
Observed: Prefer clear content blocks with consistent internal padding. Use whitespace to separate concerns before adding borders or shadows.

## 6. Components
Observed: Buttons: primary action uses #FAD4C0; secondary actions stay neutral. Inputs: strong focus-visible states, clear labels, and predictable error messaging.

## 7. Motion & Interaction
Observed: Use subtle transitions that emphasize Primary (#FAD4C0) as the interaction signal. Default to short, purposeful transitions (150–250ms) with stable easing.

## 8. Voice & Brand
Observed: Tone should reflect the visual style: concise, confident, and product-specific. Keep microcopy action-oriented and avoid generic filler language.

## 9. Anti-patterns
Adapt source restrictions to the task; accessibility, semantic state, and authorized identity outrank style prescriptions.

## Translation contract
Context gaps: audience, task, platform, content, asset rights, supported themes. Conflict: Equal-looking boxes must not imply equal priority; mobile order must follow semantics.
Tasks: map observed roles to original tokens; specify one representative layout and component states; test reading order, responsive overflow, focus, contrast, and reduced motion.
Edge cases: unavailable assets/fonts; long/localized content; theme or media failure.
Output: `{status, source_sha256, assumptions, tokens, layout, states, evidence, blockers}`. Status: draft|validated|blocked.
Tests: outcome=all fields and observed checks recorded; context=unknowns explicit; conflict=brief/accessibility before source style; reuse=semantic roles independent of tool/model. Max two revision passes; unresolved blockers stop delivery. No install, publish, or external mutation.
