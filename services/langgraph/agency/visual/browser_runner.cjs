// Real-browser render and capture for the R3 (WebGL) and R4 (SVG multi-size) routes.
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

async function main() {
  const [specPath, outDir] = process.argv.slice(2);
  const spec = JSON.parse(fs.readFileSync(specPath, "utf8"));
  fs.mkdirSync(outDir, { recursive: true });
  const pw = loadPlaywright();
  if (!pw) {
    fs.writeFileSync(path.join(outDir, "result.json"), JSON.stringify({ error: "PLAYWRIGHT_NOT_INSTALLED" }));
    process.exit(3);
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
