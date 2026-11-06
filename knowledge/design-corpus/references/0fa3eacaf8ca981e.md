# Design System Inspired by Retro

> Category: Retro & Nostalgic

Source: `ba3fdc8e5be05851.md`; SHA256: `ba3fdc8e5be058513ea6ff5f19938db831e94d7bbfc03da8383327a2f7e3a86e`. Status: attached-source observations; not live-verified authority. Original retained separately.

## Core constraint
Translate nostalgic display accents inside predictable information structure into original design; validate usability and identity rights before implementation.

## 1. Visual Theme & Atmosphere
Source direction: nostalgic display accents inside predictable information structure.

## 2. Color
Observed: Primary: #3B82F6 — Token from style foundations. Secondary: #8B5CF6 — Token from style foundations.

## 3. Typography
Observed: Scale: desktop-first expressive scale. Headings should carry the style personality; body text should optimize scanability and contrast.

## 4. Spacing & Grid
Observed: Spacing scale: 4/8/12/16/24/32. Align columns and modules to a predictable grid; avoid ad-hoc offsets.

## 5. Layout & Composition
Observed: Prefer clear content blocks with consistent internal padding. Use whitespace to separate concerns before adding borders or shadows.

## 6. Components
Observed: Buttons: primary action uses #3B82F6; secondary actions stay neutral. Inputs: strong focus-visible states, clear labels, and predictable error messaging.

## 7. Motion & Interaction
Observed: Use subtle transitions that emphasize Primary (#3B82F6) as the interaction signal. Default to short, purposeful transitions (150–250ms) with stable easing.

## 8. Voice & Brand
Observed: Tone should reflect the visual style: concise, confident, and product-specific. Keep microcopy action-oriented and avoid generic filler language.

## 9. Anti-patterns
Adapt source restrictions to the task; accessibility, semantic state, and authorized identity outrank style prescriptions.

## Translation contract
Context gaps: audience, task, platform, content, asset rights, supported themes. Conflict: Generic blue-purple tokens do not establish an era; Macondo body use requires legibility testing.
Tasks: map observed roles to original tokens; specify one representative layout and component states; test reading order, responsive overflow, focus, contrast, and reduced motion.
Edge cases: unavailable assets/fonts; long/localized content; theme or media failure.
Output: `{status, source_sha256, assumptions, tokens, layout, states, evidence, blockers}`. Status: draft|validated|blocked.
Tests: outcome=all fields and observed checks recorded; context=unknowns explicit; conflict=brief/accessibility before source style; reuse=semantic roles independent of tool/model. Max two revision passes; unresolved blockers stop delivery. No install, publish, or external mutation.
