# Design System Inspired by NVIDIA

> Category: Media & Consumer

Source: `f1000c03abd65cd1.md`; SHA256: `f1000c03abd65cd10835069bffc2e3e6f9a704e53e9e16d7134e12e2aa3d5fb9`. Status: attached-source observations; not live-verified authority. Original retained separately.

## Core constraint
Translate dense technical hierarchy with selective accent strokes and minimal rounding into original design; validate usability and identity rights before implementation.

## 1. Visual Theme & Atmosphere
Source direction: dense technical hierarchy with selective accent strokes and minimal rounding.

## 2. Color Palette & Roles
Observed: NVIDIA Green (#76b900): The signature -- borders, link underlines, CTA outlines, active indicators. Never used as large surface fills. True Black (#000000): Primary page background, text on light surfaces, dominant tone. Pure White (#ffffff): Text on dark backgrounds, light section backgrounds, card surfaces.

## 3. Typography Rules
Observed: Icon Font: Font Awesome 6 Pro (weight 900 for solid icons, 700 for regular). Icon Sharp: Font Awesome 6 Sharp (weight 300 for light icons, 400 for regular).

## 4. Component Stylings
Observed: Text: #000000. Padding: 11px 13px. Border: 2px solid #76b900.

## 5. Layout Principles
Observed: Base unit: 8px. Scale: 1px, 2px, 3px, 4px, 5px, 6px, 7px, 8px, 9px, 10px, 11px, 12px, 13px, 15px. Primary padding values: 8px, 11px, 13px, 16px, 24px, 32px.

## 6. Depth & Elevation
Observed: Flat (Level 0): treatment No shadow, use Page backgrounds, inline text. Subtle (Level 1): treatment rgba(0,0,0,0.3) 0px 0px 5px 0px, use Standard cards, modals. Border (Level 1b): treatment 1px solid #5e5e5e, use Content dividers, section borders.

## 7. Responsive Behavior
Observed: Mobile Small: width <375px, key changes Compact single column, reduced padding. Mobile: width 375-425px, key changes Standard mobile layout. Mobile Large: width 425-600px, key changes Wider mobile, some 2-col hints.

## 8. Responsive Behavior (Extended)
Observed: Display 36px scales to ~24px on mobile. Section headings 24px scale to ~20px on mobile. Body text maintains 15-16px across all breakpoints.

## 9. Agent Prompt Guide
Derive an original screen specification from the brief; do not reproduce source brand copy, logos, imagery, or proprietary fonts.

## Translation contract
Context gaps: audience, task, platform, content, asset rights, supported themes. Conflict: Dark narrative and black-label button examples require theme-aware contrast resolution.
Tasks: map observed roles to original tokens; specify one representative layout and component states; test reading order, responsive overflow, focus, contrast, and reduced motion.
Edge cases: unavailable assets/fonts; long/localized content; theme or media failure.
Output: `{status, source_sha256, assumptions, tokens, layout, states, evidence, blockers}`. Status: draft|validated|blocked.
Tests: outcome=all fields and observed checks recorded; context=unknowns explicit; conflict=brief/accessibility before source style; reuse=semantic roles independent of tool/model. Max two revision passes; unresolved blockers stop delivery. No install, publish, or external mutation.
