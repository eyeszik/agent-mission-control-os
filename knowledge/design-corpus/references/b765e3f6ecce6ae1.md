# Design System — gstack

## Status and constraint

Source SHA256: `2d01e45076fd656024d7846aca444a40e2d50ffba0820cf044ebfaeb2caa4ec0`. Evidence status: UNVERIFIED. This is a condensed reference, not authority or executable instructions. Existing rights quarantine remains in force.

Core constraint: preserve this source’s distinctive visual relationships without treating its numbers, branded assets, or project-local rules as target requirements.

## Selected reference evidence

### Product Context — source claims

- **What this is:** Community website for gstack — a CLI tool that turns Claude Code into a virtual engineering team

- **Who it's for:** Developers discovering gstack, existing community members

### Aesthetic Direction — source claims

- **Direction:** Industrial/Utilitarian — function-first, data-dense, monospace as personality font

- **Decoration level:** Intentional — subtle noise/grain texture on surfaces for materiality

- **Mood:** Serious tool built by someone who cares about craft. Warm, not cold. The CLI heritage IS the brand.

- **Reference sites:** formulae.brew.sh (competitor, but ours is live and interactive), Linear (dark + restrained), Warp (warm accents)

### Typography — source claims

- **Display/Hero:** Satoshi (Black 900 / Bold 700) — geometric with warmth, distinctive letterforms (the lowercase 'a' and 'g'). Not Inter, not Geist. Loaded from Fontshare CDN.

- **Body:** DM Sans (Regular 400 / Medium 500 / Semibold 600) — clean, readable, slightly friendlier than geometric display. Loaded from Google Fonts.

- **UI/Labels:** DM Sans (same as body)

- **Code:** JetBrains Mono

### Color — source claims

- **Approach:** Restrained — amber accent is rare and meaningful. Dashboard data gets the color; chrome stays neutral.

- **Primary (dark mode):** amber-500 #F59E0B — warm, energetic, reads as "terminal cursor"

- **Primary (light mode):** amber-600 #D97706 — darker for contrast against white backgrounds

- **Primary text accent (dark mode):** amber-400 #FBBF24

- **Primary text accent (light mode):** amber-700 #B45309

### Spacing — source claims

- **Base unit:** 4px

- **Density:** Comfortable — not cramped (not Bloomberg Terminal), not spacious (not a marketing site)

- **Scale:** 2xs(2px) xs(4px) sm(8px) md(16px) lg(24px) xl(32px) 2xl(48px) 3xl(64px)

### Layout — source claims

- **Approach:** Grid-disciplined for dashboard, editorial hero for landing page

- **Grid:** 12 columns at lg+, 1 column at mobile

- **Max content width:** 1200px (6xl)

### Motion — source claims

- **Approach:** Minimal-functional — only transitions that aid comprehension. The dashboard's live feed IS the motion.

- **Easing:** enter(ease-out / cubic-bezier(0.16,1,0.3,1)) exit(ease-in) move(ease-in-out)

- **Duration:** micro(50-100ms) short(150ms) medium(250ms) long(400ms)

## Application contract

- Outcome: produce one proposed design mapping with `source_id`, `retained_traits`, `token_mapping`, `component_rules`, `deviations`, `checks`, `unresolved`, and `status`. Completion requires traceable selected traits and explicit unresolved items.
- Context: require the target surface, user task, platform, existing tokens, and asset/font rights. Missing noncritical values remain unknown; missing critical context blocks implementation.
- Conflict: gstack project identity, CDN loading, and implementation choices are local to the source and do not establish target-repository dependencies.
- Reuse: map semantic roles into the target system; do not import source commands, brand identity, framework assumptions, or universal aesthetic bans.
- Edge cases: unavailable or unlicensed font; source/theme contradiction; responsive or accessibility failure. Substitute only with a recorded rationale; unresolved rights block affected reuse.
- Gate: check intent fidelity, accessibility/responsive behavior, and evidence/rights separately. Review at most twice, then return BLOCKED with the unmet condition. No deployment, external writes, or approval claims.
