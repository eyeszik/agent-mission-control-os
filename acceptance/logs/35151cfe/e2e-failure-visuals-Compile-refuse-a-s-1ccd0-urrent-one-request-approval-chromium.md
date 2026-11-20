# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: visuals.spec.ts >> Compile, refuse a stale edit, apply a current one, request approval
- Location: e2e/visuals.spec.ts:76:1

# Error details

```
Error: expect(locator).toBeVisible() failed

Locator: getByRole('img', { name: /Rendered preview of halden-kiln-poster/ })
Expected: visible
Timeout: 60000ms
Error: element(s) not found

Call log:
  - Expect "toBeVisible" getByRole('img', { name: /Rendered preview of halden-kiln-poster/ }) with timeout 60000ms
  - waiting for getByRole('img', { name: /Rendered preview of halden-kiln-poster/ })

```

```yaml
- link "Skip to content":
  - /url: "#agency-main"
- complementary "Primary":
  - paragraph: Agency OS
  - paragraph: Mission Control
  - navigation "Sections":
    - list:
      - listitem:
        - button "Overview"
      - listitem:
        - button "Clients"
      - listitem:
        - button "Projects"
      - listitem:
        - button "Missions"
      - listitem:
        - button "Mission Council"
      - listitem:
        - button "Operating Framework"
      - listitem:
        - button "Website Production"
      - listitem:
        - button "Visual Compiler"
      - listitem:
        - button "Creative Studio"
      - listitem:
        - button "Approvals"
      - listitem:
        - button "Deliverables"
      - listitem:
        - button "Analytics"
      - listitem:
        - button "Integrations"
      - listitem:
        - button "Settings"
  - paragraph: "External actions: disabled. Sandbox only."
- banner:
  - text: Project
  - combobox "Project":
    - option "Agency E2E (fictional)" [selected]
  - button "Search ⌘K"
  - status: 0 running · 0 need checking
  - 'button "Attention queue: 4 items"': "4"
  - button "Use light theme"
  - text: local-e2e operator
- main:
  - heading "Visual Compiler" [level=1]
  - text: Asset
  - combobox "Asset":
    - option "halden-kiln-poster (scene v1)" [selected]
  - region "Asset halden-kiln-poster":
    - heading "Asset halden-kiln-poster" [level=2]
    - paragraph: The SVG is the source of truth; the PNG is a preview. Every stage is a Project OS artifact with its exact version.
    - paragraph: No preview
    - text: The renderer was unavailable when this asset was compiled.
    - term: Evaluation
    - definition: Not passed
    - term: Stages
    - definition: "Stale preview: approval and release are blocked until recompiled"
    - term: Profile
    - definition: post-surrealist-editorial · NATIVE_EDITABLE_VECTOR · 1200×1500
    - term: Brand
    - definition: foundry.psem.PALETTE (projection, not approved)
    - term: SVG
    - definition:
      - code: 677cee699377889e…
    - button "Recompile from scene"
    - table "Stage artifacts":
      - caption: Stage artifacts
      - rowgroup:
        - row "Stage Version Hash":
          - columnheader "Stage"
          - columnheader "Version"
          - columnheader "Hash"
      - rowgroup:
        - row "intent v1 2a58c59c0d9e3062…":
          - rowheader "intent"
          - cell "v1"
          - cell "2a58c59c0d9e3062…":
            - code: 2a58c59c0d9e3062…
        - row "references v1 4e2dbd3f43caafca…":
          - rowheader "references"
          - cell "v1"
          - cell "4e2dbd3f43caafca…":
            - code: 4e2dbd3f43caafca…
        - row "brand v1 a2fc78b11122f6fa…":
          - rowheader "brand"
          - cell "v1"
          - cell "a2fc78b11122f6fa…":
            - code: a2fc78b11122f6fa…
        - row "scene v1 bfd744d0c000e35b…":
          - rowheader "scene"
          - cell "v1"
          - cell "bfd744d0c000e35b…":
            - code: bfd744d0c000e35b…
        - row "svg v1 677cee699377889e…":
          - rowheader "svg"
          - cell "v1"
          - cell "677cee699377889e…":
            - code: 677cee699377889e…
        - row "evaluation v1 e964bbe9588b788b…":
          - rowheader "evaluation"
          - cell "v1"
          - cell "e964bbe9588b788b…":
            - code: e964bbe9588b788b…
        - row "provenance v1 84c2b06970311ec3…":
          - rowheader "provenance"
          - cell "v1"
          - cell "84c2b06970311ec3…":
            - code: 84c2b06970311ec3…
  - region "Independent evaluation":
    - heading "Independent evaluation" [level=2]
    - paragraph: 20 checks read from the stored SVG and PNG bytes · 1 not passing · renderer raster.chromium
    - list:
      - listitem: BLOCKED render no rendered preview (renderer unavailable or failed)
      - listitem: PASS svg_safety well-formed SVG without active content or external references
      - listitem: PASS allowlist_elements all elements allowlisted
      - listitem: PASS allowlist_attributes all attributes allowlisted
      - listitem: PASS text_placement ok
      - listitem: PASS unique_ids 16 unique ids
      - listitem: PASS reference_integrity all references local and resolved
      - listitem: PASS finite_coordinates all coordinates finite and bounded
      - listitem: "PASS resource_ceiling 26 elements, 4 path commands, depth<=24: True"
      - listitem: "PASS profile_integrity NATIVE_EDITABLE_VECTOR: 0 embedded raster element(s)"
      - listitem: PASS dimensions declared 1200x1500, expected 1200x1500
      - listitem: PASS exact_text.headline expected 'MADE SLOWLY', SVG has 'MADE SLOWLY'
      - listitem: PASS exact_text.annotation expected 'FIG. 07 / KILN OPENING 2027', SVG has 'FIG. 07 / KILN OPENING 2027'
      - listitem: PASS palette 5 colour(s) within dE76<=2.3 of the palette
      - listitem: "PASS accent_budget 1 accent colour(s) used: ['#ff4c2f']"
      - listitem: "PASS contrast.headline #f0eee9 on #171719 = 15.44:1 (floor 4.5)"
      - listitem: "PASS contrast.annotation #838185 on #171719 = 4.64:1 (floor 4.5)"
      - listitem: "PASS contrast.motif #ff4c2f on #171719 = 5.39:1 (floor 3.0)"
      - listitem: PASS text_fit.headline estimated right edge 821px of 1200px (glyph-advance estimate)
      - listitem: PASS text_fit.annotation estimated right edge 365px of 1200px (glyph-advance estimate)
  - region "Edit":
    - heading "Edit" [level=2]
    - paragraph: Each edit is re-rendered and re-evaluated; a failing edit keeps the stored version. Brief text and protected geometry cannot change.
    - text: Object
    - combobox "Object":
      - option "motif-ring-outer (motif, protected)" [selected]
      - option "motif-ring-inner (motif, protected)"
      - option "motif-axis (motif, protected)"
      - option "material-object (material_object)"
      - option "material-object-highlight (highlight)"
      - option "headline (headline, protected)"
      - option "annotation-rule (rule)"
      - option "annotation (annotation, protected)"
    - text: Operation
    - combobox "Operation":
      - option "recolor" [selected]
    - text: Palette colour
    - combobox "Palette colour":
      - 'option "amber #ffaa3d" [selected]'
      - 'option "charcoal #171719"'
      - 'option "fog #838185"'
      - 'option "graphite #323234"'
      - 'option "paper #f0eee9"'
      - 'option "signal_red #ff4c2f"'
    - paragraph: Only colours from the brand projection are allowed.
    - text: Paint
    - combobox "Paint":
      - option "fill" [selected]
      - option "stroke"
    - button "Apply edit"
  - region "Approval and local release":
    - heading "Approval and local release" [level=2]
    - paragraph: Approval binds the exact SVG bytes and is decided in the approval queue by someone other than the requester. Release writes a local record only; nothing is published.
    - term: Approval
    - definition: Not requested for this version
    - term: Last release
    - definition: none
    - term: External effects
    - definition: none
    - button "Request approval" [disabled]
    - button "Open approval queue" [disabled]
    - button "Release locally" [disabled]
    - note: Evaluation has not passed.
    - note: Release needs an approval of the current version.
  - region "Compile a visual":
    - heading "Compile a visual" [level=2]
    - paragraph: "Brief text is data: instructions, publish/send/spend requests and third-party marks are refused. Colours come only from the server's brand projection."
    - text: Style profile
    - combobox "Style profile":
      - option "Post-Surrealist Editorial" [selected]
      - option "Swiss Editorial Modernism"
      - option "Technical Minimalism"
      - option "Geometric Infographics"
    - text: Seed
    - textbox "Seed": "0"
    - text: AssetRequirement (JSON)
    - textbox "AssetRequirement (JSON)": "{\"asset_id\":\"halden-kiln-poster\",\"family\":\"IMAGE\",\"asset_type\":\"editorial_poster\",\"objective\":\"Announce the spring kiln opening of a small fictional ceramics studio\",\"audience\":\"ceramics collectors and studio-list subscribers\",\"channel\":\"print\",\"destination\":\"studio wall poster\",\"content_requirements\":[\"A geometric identity motif\",\"A ceramic material object with soft lighting\",\"A technical annotation\"],\"negative_constraints\":[\"no photographs\",\"no third-party marks\"],\"quality_constraints\":[\"headline legible at a distance\"],\"exact_text\":[\"MADE SLOWLY\",\"FIG. 07 / KILN OPENING 2027\"],\"production\":{\"width\":1200,\"height\":1500,\"format\":\"svg\"}}"
    - button "Compile"
    - status: "BLOCKED:"
  - region "Capabilities":
    - heading "Capabilities" [level=2]
    - paragraph: "Each verified claim names the tests behind it. Renderer: IMPLEMENTED_VERIFIED (at most 2 at once)."
    - list:
      - listitem: "IMPLEMENTED_VERIFIED ACE intent: classification, injection containment, effects never inferred"
      - listitem: "IMPLEMENTED_VERIFIED Output profiles: native editable / fidelity / illustrative"
      - listitem: BLOCKED HYBRID_SVG, RASTER_FINAL
      - listitem: IMPLEMENTED_VERIFIED SceneIR + deterministic SVG emitter
      - listitem: IMPLEMENTED_VERIFIED Allowlist SVG validator (elements, attributes, local refs, ids, finite coords, ceilings)
      - listitem: IMPLEMENTED_VERIFIED Editorial vertical slice (background, headline, motif, material object, lighting, annotation)
      - listitem: "IMPLEMENTED_VERIFIED Edits: inspect, recolor, change_text, set_geometry, validate"
      - listitem: "IMPLEMENTED_VERIFIED Edit concurrency: stale base and racing writers conflict instead of overwriting"
      - listitem: "IMPLEMENTED_VERIFIED Crash recovery: stale derived stages detected, blocked from release, re-derived from the scene"
      - listitem: IMPLEMENTED_VERIFIED Independent evaluation (exact text, palette, accent budget, WCAG contrast, text fit estimate, nonblank, headline ink)
      - listitem: "IMPLEMENTED_VERIFIED Margin bands: content in the outer half-margin measured on rendered pixels"
      - listitem: IMPLEMENTED_VERIFIED Project OS persistence, lineage, approval, local release, approval non-inheritance, tamper detection, cache divergence
      - listitem: IMPLEMENTED_VERIFIED H3 causal repair (contrast, palette, accent budget, text overflow, exact text)
      - listitem: PROPOSED H3 automatic repair of blank renders and margin overflow
      - listitem: PARTIAL H1 coarse-to-fine region reconstruction + linear-gradient fitting + Pareto
      - listitem: PROPOSED H1 DiffVG / LIVE / Bezier contour fitting / Jacobian constraint projection
      - listitem: IMPLEMENTED_VERIFIED H2 governed brand mutation (approval required, protected invariants, rollback ref)
      - listitem: IMPLEMENTED_VERIFIED H4 reproducible variant branches, Pareto selection, no approval inheritance
      - listitem: "IMPLEMENTED_VERIFIED Style profiles: Post-Surrealist Editorial, Swiss Editorial Modernism, Technical Minimalism, Geometric Infographics"
      - listitem: IMPLEMENTED_VERIFIED H5 material parameters with provenance; vector shading for 10 families; bounded vector texture
      - listitem: BLOCKED Physically based material rendering / inverse rendering
      - listitem: PROPOSED Semantic reference analysis (subjects, styles)
      - listitem: PROVIDER_GAP Video / motion
      - listitem: "IMPLEMENTED_VERIFIED `/avic` API: tenant-scoped, operator-gated writes, idempotent, stale edits are 409, inert SVG serving"
      - listitem: "IMPLEMENTED_VERIFIED Visual Compiler section in `/agency` (compile, inspect, edit, recover, request approval, release)"
      - listitem: IMPLEMENTED_VERIFIED Bounded render concurrency
- alert
```

# Test source

```ts
  30  |   if (phone) await page.getByRole('button', { name: 'Open navigation' }).click();
  31  |   await page.getByRole('button', { name: 'Visual Compiler' }).first().click();
  32  | }
  33  | 
  34  | test.beforeAll(async ({ request }) => {
  35  |   const res = await request.post(`${API}/projects`, {
  36  |     headers: { 'Idempotency-Key': `avic-e2e-${PROJECT}` },
  37  |     data: { display_name: 'AVIC E2E (fictional)', project_id: PROJECT, slug: `avic-e2e-${PROJECT}` },
  38  |   });
  39  |   expect([201, 409]).toContain(res.status());
  40  | });
  41  | 
  42  | test('Compile intake explains disabled actions and passes axe', async ({ page }) => {
  43  |   await openVisuals(page);
  44  |   await expect(page.getByRole('heading', { name: 'Compile a visual' })).toBeVisible({ timeout: 15_000 });
  45  |   await expect(page.getByRole('button', { name: 'Compile', exact: true })).toBeDisabled();
  46  |   await expect(page.getByText(/Paste an AssetRequirement JSON/)).toBeVisible();
  47  |   await expect(page.getByRole('heading', { name: 'Capabilities' })).toBeVisible();
  48  |   await expectNoAxeViolations(page, 'empty intake');
  49  | });
  50  | 
  51  | test('Compile explains pending and failed capability checks', async ({ page }) => {
  52  |   // Hold the response explicitly; machine speed cannot hide the loading state.
  53  |   let release: () => void = () => {};
  54  |   const pending = new Promise<void>((resolve) => { release = resolve; });
  55  |   await page.route('**/avic/capabilities', async (route) => {
  56  |     await pending;
  57  |     await route.fulfill({ status: 503, contentType: 'application/json', body: '{"detail":"Test-only capability outage"}' });
  58  |   });
  59  |   try {
  60  |     await openVisuals(page);
  61  |     await page.getByLabel('AssetRequirement (JSON)').fill(JSON.stringify(SAMPLE.requirement));
  62  |     const compile = page.getByRole('button', { name: 'Compile', exact: true });
  63  |     const reason = page.locator('#avic-compile-blocked');
  64  |     await expect(compile).toBeDisabled();
  65  |     await expect(compile).toHaveAttribute('aria-describedby', 'avic-compile-blocked');
  66  |     await expect(reason).toHaveCount(1);
  67  |     await expect(reason).toHaveText('Checking the API host for a renderer…');
  68  |     release();
  69  |     await expect(reason).toContainText("Could not read the API host's capabilities:");
  70  |     await expect(compile).toBeDisabled();
  71  |   } finally {
  72  |     release();
  73  |   }
  74  | });
  75  | 
  76  | test('Compile, refuse a stale edit, apply a current one, request approval', async ({ page, request }) => {
  77  |   // Four real Chromium renders plus a two-step stale-edit sequence. Each phase
  78  |   // runs inside test.step and every wait is bounded well below the test budget:
  79  |   // a phase that stalls then names itself in the report instead of consuming
  80  |   // the whole timeout and leaving "which step?" to be guessed from a duration.
  81  |   test.setTimeout(420_000);
  82  |   const errors: string[] = [];
  83  |   page.on('pageerror', (e) => errors.push(String(e)));
  84  | 
  85  |   await test.step('open the visual compiler', async () => {
  86  |     await openVisuals(page);
  87  |     await page.getByLabel('AssetRequirement (JSON)').fill(JSON.stringify(SAMPLE.requirement));
  88  |   });
  89  | 
  90  |   const unavailable = page.getByText(/Renderer unavailable on the API host/);
  91  |   const compile = page.getByRole('button', { name: 'Compile', exact: true });
  92  |   await test.step('compile, or state honestly that the renderer is unavailable', async () => {
  93  |     // Visibility precedes capability resolution. Wait for an actionable result,
  94  |     // while keeping unexpected disabled states diagnostic and bounded.
  95  |     await expect.poll(async () => (await compile.isEnabled()) || (await unavailable.isVisible()),
  96  |       { timeout: 30_000, message: 'Compile must become ready or explain renderer unavailability' }).toBe(true);
  97  |     if (await unavailable.isVisible()) {
  98  |       // A host without the renderer must say so rather than pretend; that is a
  99  |       // success for this branch, not an early exit that hides a failure.
  100 |       await expect(compile).toBeDisabled();
  101 |       test.skip(true, 'renderer unavailable on this host: the honest-refusal branch is asserted');
  102 |       return;
  103 |     }
  104 |     // A disabled Compile is a statement about the host, and the note next to it
  105 |     // is that statement. Waiting for the click to time out hides the sentence
  106 |     // the page was already showing; read it and fail with it.
  107 |     if (!(await compile.isEnabled())) {
  108 |       // Collect every channel the panel uses to say why, so the failure line
  109 |       // carries the state rather than pointing at it: the described-by target,
  110 |       // any note on screen, the runner's own status line, and the intake values
  111 |       // the reason is derived from.
  112 |       const describedBy = await compile.getAttribute('aria-describedby');
  113 |       const note = describedBy
  114 |         ? await page.locator(`#${describedBy}`).textContent().catch(() => null)
  115 |         : await page.getByTestId('avic-compile-blocked').textContent().catch(() => null);
  116 |       const notes = (await page.getByRole('note').allTextContents().catch(() => [])).join(' / ');
  117 |       const status = (await page.getByRole('status').allTextContents().catch(() => [])).slice(0, 3).join(' / ');
  118 |       const requirement = await page.getByLabel('AssetRequirement (JSON)').inputValue();
  119 |       throw new Error(
  120 |         `Compile is disabled. describedBy=${describedBy ?? 'none'}; note=${note ?? 'none'}; ` +
  121 |         `notes on page=${notes || 'none'}; status=${status || 'none'}; ` +
  122 |         `requirement filled=${requirement.length > 0}`,
  123 |       );
  124 |     }
  125 |     await compile.click();
  126 |     await expect(page.getByRole('heading', { name: `Asset ${ASSET}` })).toBeVisible({ timeout: 120_000 });
  127 |   });
  128 | 
  129 |   await test.step('the compiled asset renders and evaluates', async () => {
> 130 |     await expect(page.getByRole('img', { name: new RegExp(`Rendered preview of ${ASSET}`) })).toBeVisible({ timeout: 60_000 });
      |                                                                                               ^ Error: expect(locator).toBeVisible() failed
  131 |     await expect(page.getByRole('heading', { name: 'Independent evaluation' })).toBeVisible();
  132 |     await expect(page.getByRole('button', { name: 'Recompile from scene' })).toBeDisabled();
  133 |     await expectNoAxeViolations(page, 'compiled asset');
  134 |   });
  135 | 
  136 |   await test.step('a stale edit is refused, then a current one applies', async () => {
  137 |     // Someone else changes the asset after this page loaded it.
  138 |     const base = `${API}/avic/projects/${PROJECT}/assets/${ASSET}`;
  139 |     const view = await (await request.get(base)).json();
  140 |     const other = await request.post(`${base}/edits`, {
  141 |       headers: { 'Idempotency-Key': `avic-e2e-other-${Date.now()}` },
  142 |       data: { op: 'recolor', args: { object_id: 'motif-ring-inner', palette_key: 'fog', field: 'stroke' }, base_svg_sha256: view.svg_sha256 },
  143 |     });
  144 |     expect(other.status()).toBe(200);
  145 | 
  146 |     await page.getByLabel('Object').selectOption('motif-ring-inner');
  147 |     await page.getByLabel('Palette colour').selectOption('paper');
  148 |     await page.getByLabel('Paint').selectOption('stroke');
  149 |     await page.getByRole('button', { name: 'Apply edit' }).click();
  150 |     await expect(page.getByText(/changed after you opened it/)).toBeVisible({ timeout: 60_000 });
  151 | 
  152 |     await page.getByRole('button', { name: 'Apply edit' }).click();
  153 |     await expect(page.getByText(/Applied: 1 change/)).toBeVisible({ timeout: 120_000 });
  154 |   });
  155 | 
  156 |   await test.step('approval is requested and release stays blocked', async () => {
  157 |     await page.getByRole('button', { name: 'Request approval' }).click();
  158 |     await expect(page.getByText(/Approval requested/)).toBeVisible({ timeout: 60_000 });
  159 |     await expect(page.getByRole('button', { name: 'Release locally' })).toBeDisabled();
  160 |     await expectNoAxeViolations(page, 'after edit and approval request');
  161 |     expect(errors).toEqual([]);
  162 |   });
  163 | });
  164 | 
  165 | test('Holds its layout at phone width', async ({ page }) => {
  166 |   await page.setViewportSize({ width: 375, height: 800 });
  167 |   await openVisuals(page, { phone: true });
  168 |   await expect(page.getByRole('heading', { name: 'Compile a visual' })).toBeVisible({ timeout: 15_000 });
  169 |   const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
  170 |   expect(overflow).toBeLessThanOrEqual(1);
  171 | });
  172 | 
```