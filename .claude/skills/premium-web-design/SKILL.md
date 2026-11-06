---
name: premium-web-design
description: Design system and build workflow for landing pages, marketing sites and any new or restyled web UI (Next.js, Tailwind, Framer Motion). Covers the type scale, 8px grid, colour tokens, Framer Motion scroll reveals, staggered reveals and hover transitions, integrating 21st.dev blocks, section-by-section builds and the Lighthouse 90+ audit. Use when asked to build, restyle, animate or audit a web page, hero, navbar, pricing section or landing page, or to paste in a component from 21st.dev.
---

# Premium web design

Static pages can read as generic. Purposeful motion and a real design system make
a page feel considered. This skill sets the design system first, then adds motion,
then sources blocks, then proves performance. Skipping the design system is what
produces the generic "Tailwind default" look.

The same rules exist for the agency's prompt compiler as the guidance pack
`pg.web_experience.v1` (`services/langgraph/agency/guidance/packs/web_experience.yaml`).
Keep the two consistent when you change either one.

## 1. Know which token source applies

| You are building | Token source | How it reaches CSS |
|---|---|---|
| This repo's web app (`apps/web`) | `apps/web/tokens/amc.tokens.json` | `pnpm tokens:build` regenerates `apps/web/app/tokens.css`; Tailwind maps the semantic tokens in `apps/web/tailwind.config.ts` |
| A client brand's site (for example a Creative Foundry brand) | That brand's DTCG document (e.g. the mission's `tokens.json`) | `services/langgraph/agency/design_tokens.py` `compile_css`, the only DTCG compiler. Do not write a second one |

Never invent a value. If a token you need is missing, add it to the token source
and rebuild. Do not hard-code it in a component.

## 2. The design system

### Typography: type scale

Major third (1.25) from a 16px base. Use the role names, not raw sizes.

| Role | Tailwind class | Token | Size |
|---|---|---|---|
| caption | `text-caption` | `semantic.font.size.caption` | 0.75rem |
| label | `text-label` | `semantic.font.size.label` | 0.875rem |
| body | `text-body` | `semantic.font.size.body` | 1rem |
| lead | `text-lead` | `semantic.font.size.lead` | 1.25rem |
| h3 | `text-h3` | `semantic.font.size.h3` | 1.563rem |
| h2 | `text-h2` | `semantic.font.size.h2` | 1.953rem |
| h1 | `text-h1` | `semantic.font.size.h1` | 2.441rem |
| display | `text-display` | `semantic.font.size.display` | 3.052rem |
| display-lg | `text-display-lg` | `semantic.font.size.display-lg` | 3.815rem |

Each class carries its line height (heading 1.1, title 1.3, body 1.5). Use one
display size per viewport. Body text is never smaller than 16px.

### Spacing: 8px base grid

- Layout spacing uses multiples of 8px.
- Tailwind's numeric scale is 4px-based, so use even steps: `2` (8px), `4` (16px), `6` (24px), `8` (32px), `12` (48px), `16` (64px).
- Section rhythm has named steps: `py-block` (32px), `py-section` (64px), `py-section-lg` (96px).
- Odd 4px steps (`1`, `3`) are only for spacing inside dense controls.

### Colours: tokens only

Use the semantic colour classes: `bg-surface`, `bg-surface-raised`, `text-fg`,
`text-fg-strong`, `text-fg-muted`, `border-line`, `bg-accent`, `text-status-*` and
`ring-focus`. In `apps/web` the palette is neutral zinc with a single emerald
accent.

- No raw hex, `rgb()`, `hsl()` or arbitrary colour classes (`bg-[#...]`) in components.
- `scripts/verify_design_tokens.py` and `pnpm --filter @amc/web verify:ui` fail the build on them.
- `amc-allow-hex` is a reviewed exception, not a workaround.

### Rule: avoid generic AI aesthetics

Do not ship:
- indigo-to-purple gradient heroes, gradient blobs or default glassmorphism;
- grey text on white with uniform `rounded-xl` cards and identical shadows;
- the stock recipe (centred hero, three feature cards, logo row, pricing) with no brand-specific idea;
- emoji as icons, or Inter by default when the brand has not chosen it;
- placeholder social proof: sample testimonials, "Trusted by" logo rows, invented ratings or statistics. This also breaks the repo's zero-fabrication rule.

Do:
- pick one signature device (a shape, a typographic treatment or a motion behaviour) and repeat it;
- write real copy before styling;
- make the accent mean something, by reserving it for the primary action.

## 3. Motion: Framer Motion

Use Framer Motion for animations: scroll-triggered fades, staggered reveals and smooth
hover transitions. In `apps/web` use the shared primitives. They read durations,
easings, stagger and offset from the motion tokens, load lazily and respect
reduced motion:

```tsx
import { HoverLift, Reveal, Stagger, StaggerItem } from "@/components/motion/Motion";

<Reveal className="py-section">…section below the fold…</Reveal>

<Stagger className="grid gap-6 sm:grid-cols-3">
  {items.map((item) => (
    <StaggerItem key={item.id}>
      <HoverLift className="rounded-lg border border-line bg-surface p-6">…</HoverLift>
    </StaggerItem>
  ))}
</Stagger>
```

Values live in `apps/web/lib/design/motion.ts`, mirrored from the tokens.
`tests/motion-tokens.test.ts` fails if they drift. To change timing, edit the
tokens, then the mirror.

Rules:
- **Hero and LCP element.** Never fade in the hero headline, the hero image or anything above the fold. The hidden state is server-rendered, so it delays LCP and hides content until JavaScript runs.
- **Properties.** Animate `opacity` and `transform` only, never width, height, top or left. Reveal once.
- **Reduced motion.** It is handled by `MotionConfig reducedMotion="user"` inside the primitives. If you write raw `m.*` components, wrap them the same way.
- **Purpose.** Motion shows order and hierarchy, so what appears first is what matters first. At most one emphasis animation per viewport. No scroll-jacking, no default parallax, no looping decoration.
- **Bundle size.** Use `LazyMotion` with `domAnimation` and the `m` component, not the full `motion` component, to keep the bundle small.
- **Existing CSS motion.** CSS animations in existing components are not yet migrated. Use Framer Motion for new work, and migrate only when you are already changing that component.

## 4. 21st.dev blocks (heroes, navbars, pricing)

Do not reinvent standard blocks. The workflow:
1. Copy the component code from 21st.dev and paste it into the project.
2. Ask: *"Integrate this component, match our design tokens, and add Framer Motion animations."*

When integrating:
1. **Provenance.** Record the source URL, author and licence in a comment at the top of the file. Do not paste code whose licence you cannot find.
2. **Dependencies.** Check them. Many blocks assume shadcn/ui, `clsx`, `tailwind-merge` or Radix. Do not add a dependency for one block without asking. Prefer rewriting the few lines that need it.
3. **Tokens.** Replace every colour, font and spacing value with tokens and the classes in section 2. The gates will reject leftovers.
4. **Content.** Replace placeholder copy, avatars, testimonials, logos and numbers with real content, or delete them.
5. **Accessibility.** Fix landmarks, labels, focus order, focus rings and contrast.
6. **Motion.** Replace the block's own animation code with the primitives in section 3.

## 5. Build process

Vague prompts produce generic pages. Specify sections before building:

> Build a modern landing page for **[PRODUCT/SERVICE]**. Use Next.js (the repo's
> version, currently 16), Tailwind and Framer Motion. Pull sections from 21st.dev.
> Follow our design skill tokens. Mobile-first, responsive, and target a 90+
> Lighthouse score. Build it section by section.

Then, for each section, state its job, its content source and its motion. For example: "Hero: states
the offer, copy from the brief, no entrance animation. Services: six cards from
the offer list, staggered reveal. Pricing: from the price sheet, fade on scroll."

Build mobile-first, one section at a time. Render and check each section at
320px and at desktop width before starting the next.

## 6. Performance: prove 90+ in Lighthouse

**Optimise** before measuring:
- `next/image` with explicit sizes and modern formats, and `priority` only on the LCP image;
- fonts through `next/font` with `display: "swap"`;
- client components only where something is interactive.

**Measure** on a production build, never the dev server:

```bash
pnpm --filter @amc/web build && pnpm --filter @amc/web start --port 3000 &
CHROME_PATH=/opt/pw-browsers/chromium-1194/chrome-linux/chrome npx -y lighthouse@13.5.0 \
  http://127.0.0.1:3000/<page> --chrome-flags="--headless=new --no-sandbox" \
  --only-categories=performance,accessibility,best-practices,seo \
  --output=json --output=html --output-path=./lighthouse-report
```

The default run is mobile emulation, which is the one that counts. Report the four
scores with the URL, the date and "mobile, production build". Never state a score
you did not measure. If a category is below 90, fix the top opportunity in the
report and re-run.

## 7. Before you finish

```bash
pnpm tokens:build   # only if you changed tokens/amc.tokens.json
pnpm --filter @amc/web typecheck
pnpm --filter @amc/web test
pnpm --filter @amc/web verify:ui
python scripts/verify_design_tokens.py
```

Common mistakes:
- **No design system.** You get a generic Tailwind-style site.
- **Vague prompts.** Name the sections and the animation for each one.
- **No performance check.** Always finish with a Lighthouse audit and image optimisation.
