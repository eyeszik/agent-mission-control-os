# Design System Inspired by Runway

> Category: AI & LLM

Source: `f873f90495a932a5.md`; SHA256: `f873f90495a932a50d899f72600c231c76b3e706cdb17f90188747ad36613afc`. Status: attached-source observations; not live-verified authority. Original retained separately.

## Core constraint
Translate media-led cinematic browsing with restrained interface chrome into original design; validate usability and identity rights before implementation.

## 1. Visual Theme & Atmosphere
Source direction: media-led cinematic browsing with restrained interface chrome.

## 2. Color Palette & Roles
Observed: Runway Black (#000000): The primary page background and maximum-emphasis text. Deep Black (#030303): A near-imperceptible variant for layered dark surfaces. Dark Surface (#1a1a1a): Card backgrounds and elevated dark containers.

## 3. Typography Rules
Observed: Display / Hero: font abcNormal, size 48px (3rem), weight 400, line height 1.00 (tight), letter spacing 1.2px, notes Maximum size, film-title presence. Section Heading: font abcNormal, size 40px (2.5rem), weight 400, line height 1.00–1.10, letter spacing 1px to 0px, notes Feature section titles.

## 4. Component Stylings
Observed: Text: weight 600 at 14px abcNormal. Radius: small (4px) for button-like links. Background: transparent or Dark Surface (#1a1a1a).

## 5. Layout Principles
Observed: Base unit: 8px. Scale: 4px, 6px, 8px, 12px, 16px, 20px, 24px, 28px, 32px, 48px, 64px, 78px. Section vertical spacing: generous (48–78px).

## 6. Depth & Elevation
Observed: Flat (Level 0): treatment No shadow, no border, use Everything — the dominant state. Bordered (Level 1): treatment 1px solid #27272a, use Alert containers only. Dark Section (Level 2): treatment Dark bg (#000000 / #1a1a1a) with light text, use Hero, features, footer.

## 7. Do's and Don'ts
Adapt source restrictions to the task; accessibility, semantic state, and authorized identity outrank style prescriptions.

## 8. Responsive Behavior
Observed: Mobile: width <640px, key changes Single column, stacked images, reduced hero text. Tablet: width 640–768px, key changes 2-column image grids begin. Small Desktop: width 768–1024px, key changes Standard layout.

## 9. Agent Prompt Guide
Derive an original screen specification from the brief; do not reproduce source brand copy, logos, imagery, or proprietary fonts.

## Translation contract
Context gaps: audience, task, platform, content, asset rights, supported themes. Conflict: Several button values are explicitly speculative; video failure needs a readable static fallback.
Tasks: map observed roles to original tokens; specify one representative layout and component states; test reading order, responsive overflow, focus, contrast, and reduced motion.
Edge cases: unavailable assets/fonts; long/localized content; theme or media failure.
Output: `{status, source_sha256, assumptions, tokens, layout, states, evidence, blockers}`. Status: draft|validated|blocked.
Tests: outcome=all fields and observed checks recorded; context=unknowns explicit; conflict=brief/accessibility before source style; reuse=semantic roles independent of tool/model. Max two revision passes; unresolved blockers stop delivery. No install, publish, or external mutation.
