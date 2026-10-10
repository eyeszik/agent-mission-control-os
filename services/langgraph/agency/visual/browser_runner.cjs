// Real-browser render and capture: R3 WebGL, R4 SVG multi-size, exact-size SVG rasterization,
// motion frame sequences and scripted interaction scenarios for generated interfaces.
//
// Usage: node browser_runner.cjs <spec.json> <out_dir>
// Launches the locally installed Chromium headless, aborts every non-data:
// request, and records what the browser actually did: shader compile/link
// logs, pixel statistics read back from the GPU context, context loss and
// restore events, and PNG captures. It never fetches remote content.
"use strict";

const fs = require("fs");
const path = require("path");

function loadPlaywright() {
  const candidates = [process.env.AMC_PLAYWRIGHT_CORE, "playwright-core", "@playwright/test"].filter(Boolean);
  const searchPaths = [process.cwd(), path.resolve(__dirname, "../../../../apps/web")];
  for (const name of candidates) {
    try {
      const resolved = require.resolve(name, { paths: searchPaths });
      const mod = require(resolved);
      return mod.chromium ? mod : null;
    } catch (_err) {
      // try the next candidate
    }
  }
  try {
    const testPkg = require.resolve("@playwright/test/package.json", { paths: searchPaths });
    return require(require.resolve("playwright-core", { paths: [path.dirname(testPkg)] }));
  } catch (_err) {
    return null;
  }
}

const WEBGL_PAGE = (spec) => `<!doctype html><html><body style="margin:0;background:#000">
<canvas id="c" width="${spec.width}" height="${spec.height}"></canvas>
<script>
window.__result = (async () => {
  const canvas = document.getElementById("c");
  const out = { api: "webgl", events: [] };
  canvas.addEventListener("webglcontextlost", (e) => { e.preventDefault(); out.events.push("lost"); });
  canvas.addEventListener("webglcontextrestored", () => { out.events.push("restored"); });
  const gl = canvas.getContext("webgl", { preserveDrawingBuffer: true, antialias: false });
  if (!gl) { out.error = "NO_WEBGL_CONTEXT"; return out; }
  out.renderer = gl.getParameter(gl.RENDERER);
  out.version = gl.getParameter(gl.VERSION);
  function compile(type, src) {
    const s = gl.createShader(type); gl.shaderSource(s, src); gl.compileShader(s);
    return { shader: s, ok: !!gl.getShaderParameter(s, gl.COMPILE_STATUS), log: gl.getShaderInfoLog(s) || "" };
  }
  const vs = compile(gl.VERTEX_SHADER, ${JSON.stringify(spec.vertex)});
  const fs = compile(gl.FRAGMENT_SHADER, ${JSON.stringify(spec.fragment)});
  out.compile = { vertex: { ok: vs.ok, log: vs.log }, fragment: { ok: fs.ok, log: fs.log } };
  if (!vs.ok || !fs.ok) return out;
  const prog = gl.createProgram(); gl.attachShader(prog, vs.shader); gl.attachShader(prog, fs.shader); gl.linkProgram(prog);
  out.link = { ok: !!gl.getProgramParameter(prog, gl.LINK_STATUS), log: gl.getProgramInfoLog(prog) || "" };
  if (!out.link.ok) return out;
  gl.useProgram(prog);
  const buf = gl.createBuffer(); gl.bindBuffer(gl.ARRAY_BUFFER, buf);
  gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, -1,1, 1,-1, 1,1]), gl.STATIC_DRAW);
  const loc = gl.getAttribLocation(prog, "position"); gl.enableVertexAttribArray(loc);
  gl.vertexAttribPointer(loc, 2, gl.FLOAT, false, 0, 0);
  const res = gl.getUniformLocation(prog, "resolution"); if (res) gl.uniform2f(res, canvas.width, canvas.height);
  for (const [name, rgb] of Object.entries(${JSON.stringify(spec.uniforms || {})})) {
    const u = gl.getUniformLocation(prog, name); if (u) gl.uniform3f(u, rgb[0], rgb[1], rgb[2]);
  }
  gl.viewport(0, 0, canvas.width, canvas.height); gl.drawArrays(gl.TRIANGLES, 0, 6);
  const px = new Uint8Array(canvas.width * canvas.height * 4);
  gl.readPixels(0, 0, canvas.width, canvas.height, gl.RGBA, gl.UNSIGNED_BYTE, px);
  let sum = 0, sum2 = 0, n = 0; const uniq = new Set();
  for (let i = 0; i < px.length; i += 4 * 7) {
    const l = 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2];
    sum += l; sum2 += l * l; n++; uniq.add((px[i] << 16) | (px[i + 1] << 8) | px[i + 2]);
  }
  const mean = sum / n;
  out.pixels = { mean, stddev: Math.sqrt(Math.max(0, sum2 / n - mean * mean)), unique_colors: uniq.size, error: gl.getError() };
  out.capture = canvas.toDataURL("image/png");
  const lose = gl.getExtension("WEBGL_lose_context");
  if (!lose) { out.context_loss = "EXTENSION_UNAVAILABLE"; return out; }
  lose.loseContext();
  await new Promise((r) => setTimeout(r, 50));
  out.lost_flag = gl.isContextLost();
  lose.restoreContext();
  await new Promise((r) => setTimeout(r, 150));
  out.restored_flag = !gl.isContextLost();
  return out;
})();
</script></body></html>`;

const SVG_PAGE = (svg, size) => `<!doctype html><html><body style="margin:0;background:#fff">
<img id="i" width="${size}" height="${size}" style="display:block;object-fit:contain" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">
<script>window.__result = new Promise((resolve) => {
  const img = document.getElementById("i");
  const done = () => resolve({ complete: img.complete, natural: [img.naturalWidth, img.naturalHeight] });
  if (img.complete) done(); else { img.onload = done; img.onerror = () => resolve({ complete: false, error: "DECODE_FAILED" }); }
});</script></body></html>`;

const RASTER_PAGE = (svg, width, height) => `<!doctype html><html><body style="margin:0;background:transparent">
<img id="i" width="${width}" height="${height}" style="display:block" src="data:image/svg+xml;base64,${Buffer.from(svg).toString("base64")}">
<script>window.__result = new Promise((resolve) => {
  const img = document.getElementById("i");
  const done = () => resolve({ complete: img.complete && img.naturalWidth > 0, natural: [img.naturalWidth, img.naturalHeight] });
  if (img.complete) done(); else { img.onload = done; img.onerror = () => resolve({ complete: false, error: "DECODE_FAILED" }); }
});</script></body></html>`;

// In-page audit of the rendered document: labels, focus visibility, contrast, reflow.
async function auditPage(page) {
  return page.evaluate(() => {
    const lum = (rgb) => {
      const c = rgb.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4); });
      return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const parse = (s) => { const m = s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(",").map(Number); return { rgb: p.slice(0, 3), a: p.length > 3 ? p[3] : 1 }; };
    const bgOf = (el) => { for (let e = el; e; e = e.parentElement) { const c = parse(getComputedStyle(e).backgroundColor); if (c && c.a > 0.99) return c.rgb; } return [255, 255, 255]; };
    const contrast = [];
    for (const el of document.querySelectorAll("body *")) {
      const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
      const cs = getComputedStyle(el);
      if (!own || cs.visibility === "hidden" || cs.display === "none") continue;
      const fg = parse(cs.color); if (!fg) continue;
      const a = lum(fg.rgb), b = lum(bgOf(el));
      const ratio = (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
      const size = parseFloat(cs.fontSize), weight = parseInt(cs.fontWeight, 10) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      contrast.push({ text: el.textContent.trim().slice(0, 40), ratio: Math.round(ratio * 100) / 100, required: large ? 3 : 4.5 });
    }
    const unlabeled = [...document.querySelectorAll("input, select, textarea")].filter((el) => {
      if (el.type === "hidden") return false;
      return !(el.labels && el.labels.length) && !el.getAttribute("aria-label") && !el.getAttribute("aria-labelledby");
    }).map((el) => el.name || el.id || el.type);
    return {
      contrast_failures: contrast.filter((c) => c.ratio < c.required),
      contrast_checked: contrast.length,
      unlabeled_controls: unlabeled,
      horizontal_overflow: document.documentElement.scrollWidth > window.innerWidth + 1,
      landmarks: [...document.querySelectorAll("main, header, footer, nav, section[aria-labelledby], form")].length,
    };
  });
}

async function runStep(page, step) {
  const el = step.selector ? page.locator(step.selector) : null;
  switch (step.action) {
    case "tab": for (let i = 0; i < (step.times || 1); i++) await page.keyboard.press(step.shift ? "Shift+Tab" : "Tab"); return { ok: true };
    case "press": await page.keyboard.press(step.value); return { ok: true };
    case "type": await page.keyboard.type(step.value); return { ok: true };
    case "fill": await el.fill(step.value); return { ok: true };
    case "click": await el.click(); return { ok: true };
    case "backend": await page.evaluate((mode) => { window.__amcBackend = mode; }, step.value); return { ok: true };
    case "wait": await page.waitForTimeout(step.value || 50); return { ok: true };
    case "set": await page.evaluate(([k, v]) => { window[k] = v; }, [step.name, step.value]); return { ok: true };
    case "call": {
      const exists = await page.evaluate((fn) => typeof window[fn] === "function", step.value);
      if (!exists) return { ok: false, detail: `NO_FUNCTION:${step.value}` };
      await page.evaluate((fn) => window[fn](), step.value); return { ok: true };
    }
    case "tab_until": {
      for (let i = 0; i < (step.max || 25); i++) {
        await page.keyboard.press("Tab");
        if (await page.evaluate((sel) => document.activeElement && document.activeElement.matches(sel), step.selector)) {
          return { ok: true, detail: `reached after ${i + 1} Tab presses` };
        }
      }
      return { ok: false, detail: "not reachable by keyboard" };
    }
    case "expect_no_overflow": {
      const o = await page.evaluate(() => [document.documentElement.scrollWidth, window.innerWidth]);
      return { ok: o[0] <= o[1] + 1, detail: `scrollWidth=${o[0]} viewport=${o[1]}` };
    }
    case "expect_font_fallback": {
      const r = await el.evaluate((node, primary) => {
        const rect = node.getBoundingClientRect();
        // A font is available only if it changes measured width against both generic fallbacks
        // (document.fonts.check() returns true for fonts it has nothing to load, so it cannot tell).
        const ctx = document.createElement("canvas").getContext("2d");
        const sample = "mmmmmmmmmmlli1WQ@#";
        const width = (font) => { ctx.font = font; return ctx.measureText(sample).width; };
        const available = ["monospace", "serif"].some((g) => width(`32px "${primary}", ${g}`) !== width(`32px ${g}`));
        return { primary_available: available, width: rect.width, family: getComputedStyle(node).fontFamily };
      }, step.value);
      return { ok: r.width > 0, detail: `primary_available=${r.primary_available} width=${Math.round(r.width)} family=${r.family}` };
    }
    case "expect_focus": {
      const ok = await el.evaluate((node) => node === document.activeElement);
      const ring = await page.evaluate(() => { const a = document.activeElement; if (!a) return "none"; const cs = getComputedStyle(a); return cs.outlineStyle !== "none" && parseFloat(cs.outlineWidth) > 0 ? "outline" : (cs.boxShadow !== "none" ? "shadow" : "none"); });
      return { ok: ok && ring !== "none", detail: `focused=${ok} indicator=${ring}` };
    }
    case "expect_text": { const t = (await el.innerText()).trim(); return { ok: t.includes(step.value), detail: t.slice(0, 120) }; }
    case "expect_attr": { const v = await el.getAttribute(step.name); return { ok: v === step.value, detail: `${step.name}=${v}` }; }
    case "expect_visible": { const v = await el.isVisible(); return { ok: v === (step.value !== false), detail: `visible=${v}` }; }
    case "expect_no_animation": {
      const d = await el.evaluate((node) => { const cs = getComputedStyle(node); return [cs.animationName, cs.animationDuration, cs.transitionDuration].join("|"); });
      const [name, ad, td] = d.split("|");
      const zero = (v) => v.split(",").every((x) => parseFloat(x) === 0);
      const still = (name === "none" || zero(ad)) && zero(td);
      return { ok: still, detail: d };
    }
    default: return { ok: false, detail: `UNKNOWN_ACTION:${step.action}` };
  }
}

async function main() {
  const [specPath, outDir] = process.argv.slice(2);
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  fs.mkdirSync(outDir, { recursive: true });
  const pw = loadPlaywright();
  if (!pw) {
    fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify({ error: "PLAYWRIGHT_NOT_INSTALLED" }));
    process.exit(3);
  }
  if (spec.mode === "probe") {
    const executable = spec.executable_path || pw.chromium.executablePath();
    fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify({ mode: "probe", executable, exists: fs.existsSync(executable) }));
    return;
  }
  const browser = await pw.chromium.launch({
    headless: true,
    executablePath: spec.executable_path || undefined,
    args: ["--no-sandbox", "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"],
  });
  const result = { mode: spec.mode, blocked_requests: [], browser_version: browser.version() };
  try {
    const context = await browser.newContext({ deviceScaleFactor: 1 });
    await context.route("**/*", (route) => {
      const url = route.request().url();
      if (url.startsWith("data:") || url === "about:blank") return route.continue();
      result.blocked_requests.push(url);
      return route.abort();
    });
    const page = await context.newPage();
    if (spec.mode === "webgl") {
      await page.setViewportSize({ width: spec.width, height: spec.height });
      await page.setContent(WEBGL_PAGE(spec));
      const r = await page.evaluate(() => window.__result);
      if (r.capture) {
        fs.writeFileSync(path.join(outDir, "webgl.png"), Buffer.from(r.capture.split(",")[1], "base64"));
        r.capture = "webgl.png";
      }
      result.webgl = r;
    } else if (spec.mode === "svg") {
      result.sizes = [];
      for (const size of spec.sizes) {
        await page.setViewportSize({ width: size, height: size });
        await page.setContent(SVG_PAGE(spec.svg, size));
        const r = await page.evaluate(() => window.__result);
        const file = `svg-${size}.png`;
        await page.locator("#i").screenshot({ path: path.join(outDir, file) });
        result.sizes.push({ size, ...r, capture: file });
      }
    } else if (spec.mode === "raster") {
      await page.setViewportSize({ width: spec.width, height: spec.height });
      await page.setContent(RASTER_PAGE(spec.svg, spec.width, spec.height));
      result.raster = await page.evaluate(() => window.__result);
      await page.screenshot({ path: path.join(outDir, "raster.png"), clip: { x: 0, y: 0, width: spec.width, height: spec.height }, omitBackground: true });
      result.raster.capture = "raster.png";
    } else if (spec.mode === "frames") {
      await page.setViewportSize({ width: spec.width, height: spec.height });
      result.frames = [];
      for (let i = 0; i < spec.frames.length; i++) {
        await page.setContent(RASTER_PAGE(spec.frames[i], spec.width, spec.height));
        const r = await page.evaluate(() => window.__result);
        const file = `frame_${String(i + 1).padStart(4, "0")}.png`;
        await page.screenshot({ path: path.join(outDir, file), clip: { x: 0, y: 0, width: spec.width, height: spec.height } });
        result.frames.push({ file, complete: r.complete });
      }
    } else if (spec.mode === "experience") {
      result.scenarios = [];
      for (const scenario of spec.scenarios) {
        const ctx = await browser.newContext({ viewport: scenario.viewport || { width: 1280, height: 900 },
                                               reducedMotion: scenario.reduced_motion ? "reduce" : "no-preference" });
        await ctx.route("**/*", (route) => {
          const url = route.request().url();
          if (url.startsWith("data:") || url === "about:blank") return route.continue();
          result.blocked_requests.push(url);
          return route.abort();
        });
        const sp = await ctx.newPage();
        const errors = [];
        sp.on("pageerror", (e) => errors.push(String(e)));
        await sp.setContent(spec.html);
        if (scenario.text_scale) await sp.addStyleTag({ content: `html{font-size:${scenario.text_scale * 100}%}` });
        const steps = [];
        for (const step of scenario.steps) {
          try { steps.push({ ...step, ...(await runStep(sp, step)) }); }
          catch (e) { steps.push({ ...step, ok: false, detail: String(e).slice(0, 200) }); }
        }
        const audit = await auditPage(sp);
        if (scenario.capture) await sp.screenshot({ path: path.join(outDir, `${scenario.id}.png`), fullPage: true });
        result.scenarios.push({ id: scenario.id, steps, audit, page_errors: errors, capture: scenario.capture ? `${scenario.id}.png` : null,
                                passed: steps.every((s) => s.ok) && errors.length === 0 });
        await ctx.close();
      }
    } else {
      result.error = `UNKNOWN_MODE:${spec.mode}`;
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify(result, null, 2));
}

main().catch((err) => {
  process.stderr.write(String(err && err.stack ? err.stack : err));
  process.exit(1);
});
