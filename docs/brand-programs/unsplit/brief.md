# UNSPLIT — intake brief (machine + human)

Status: **DRAFT, unapproved.** Machine-readable twin: [`brief.json`](brief.json).
Filled prompt: [`brand-prompt.md`](brand-prompt.md).

## Template, filled

| Field | Value | Label |
| --- | --- | --- |
| Business/product | A zero-touch atelier turning one year of GPS traces into one continuous line, printed once as a numbered edition of one. | PROPOSED |
| Audience | Strava-native runners, 25–45, urban, run-club adjacent; gift buyers; club captains. | PROPOSED (informed by S1–S4) |
| Market and geography | Personalised route art at $39–$249 (S6, S7); POD at 23.6% CAGR (S5). Launch US/UK/DE/NL with regional print nodes. | SOURCED market, PROPOSED geography |
| Business objective | 500 prints / 90 days, ≥70% contribution margin, 15 club partners, 2,000 waitlist. Target, not forecast. | PROPOSED |
| Desired personality | Exacting, understated, quietly romantic about effort, dry. Instrument maker, not gym brand. | PROPOSED |
| Deliverables | Strategy + 3 directions; then platform, identity, tokens, genome, logo family, poster, variants, website section, prompts, provenance. | PROPOSED |
| Existing project/tenant | None. Create `tenant-unsplit` / `prj-unsplit` locally. | FACT |
| Existing sources and approved decisions | Web sources in `strategy.md`; **no approved brand decisions**. | FACT |
| Constraints | No publish/send/deploy/spend; local render only; Inter/JetBrains Mono stacks; WCAG 2.2 AA; no real customer data; print colour unverified. | FACT |

## Kernel plan (actual output)

Command:

```
python3 orchestrate_brand_pipeline.py plan \
  --input docs/brand-programs/unsplit/brief.json
```

Output on 2026-10-27:

```
Project        UNSPLIT — running year, one line
Target phase   strategy

Production plan
  positioning_statement    brand_strategist       (strategy)  [human-approval]
  brand_platform           brand_architect        (brand)  [human-approval]
  identity_guidelines      brand_architect        (brand)  [human-approval]
  design_token_set         design_lead            (design)  [human-approval]
      missing input: brand_core
      missing input: creative_concept
  campaign_package         growth_lead            (growth)  [human-approval]
      missing input: copy_variant
      missing input: creative_concept
  automation_spec          implementation_lead    (engineering)  [human-approval]
      missing input: design_system_spec
      missing input: product_spec

Lifecycle
  ok   intake -> discovery
  ok   discovery -> research
  ok   research -> strategy

Stopped at strategy. Blockers above must clear first.
```

The plan generates nothing. The three missing-input groups are the real
prerequisites for later artefacts, not permission to invent them:

1. `brand_core` and `creative_concept` are created **after** `CD-001`.
2. `copy_variant` follows the approved voice, not before it.
3. `product_spec` and `design_system_spec` are blocked on decisions about
   print specification, substrate, vendor and production format that no one has
   made yet.

## Capability truth at drafting time

Measured with `agency.foundry.capabilities.discover()` on 2026-10-27:

| Capability | Status | Blocker |
| --- | --- | --- |
| `vector.svg` | AVAILABLE | — |
| `web.design_tokens` | AVAILABLE | — |
| `raster.chromium` | MISSING | `@playwright/test` absent; no Chromium binary |
| `web.html_css` | MISSING | same browser blockers |
| `raster.pillow` | AVAILABLE after `pip install pillow` 13.0.0 | was missing at first probe |
| `raster.imagemagick` | MISSING | not installed |
| `spatial.blender` | MISSING | `BLOCKED_ENVIRONMENT:blender` |
| `spatial.threejs` | MISSING | `three` not installed |
| `motion.ffmpeg` | MISSING | `ffmpeg` / `ffprobe` not on PATH |
| `motion.freevideoforge` | MISSING | Pillow was missing; FFmpeg/ffprobe absent |
| Paper.js, SVG.js, Rough.js, p5, Pixi, R3F, Remotion, Motion Canvas | MISSING | not installed; not required by shipped routes |

Consequence: after approval, the foundry can produce **SVG + DTCG + genome**
locally. PNG poster rasters, the browser-verified website section, the Blender
product scene and MP4 motion are **blocked** and will be reported as blocked, not
faked. Installing `@playwright/test` + Chromium would unblock raster and web
verification; FFmpeg would unblock motion; Blender would unblock the scene. None
of those installs has been authorised.

## Workflow smoke test (2026-10-27)

The supported path was executed against the repository's **fictional** demo
brand, not UNSPLIT, to prove what the host can do before asking for a direction:

```
python3 scripts/render_foundry_demo.py --out /tmp/foundry-demo-smoke --quality draft
```

Result: genome, tokens (JSON + CSS), mark, lockup, dark lockup, icon family and
poster SVG were persisted to Project OS, read back, re-hashed and reported
`VERIFIED`. The capability gaps matched the table above exactly: app icon PNG,
poster PNG, variant PNGs, browser-verified website section, Blender scene and
MP4 motion were `MISSING` for the stated blockers. Nothing was published and no
approval was decided.

Dependencies installed locally to reach that point: `pydantic 2.14.1`,
`pillow 13.0.0`, `httpx 0.28.1`, `fastapi`. They are environment state, not a
repository change; no requirements file pins them.

## Open prerequisites before Gate 2

- Trademark/domain/company-name clearance for **UNSPLIT**.
- Two print-vendor quotes plus a physical proof (substrate, ICC profile, archival
  claim).
- A decision on whether the product uses real customer Strava data at all, and
  the data-processing terms that would require.
- A budget line, if any paid channel or provider is ever enabled.
