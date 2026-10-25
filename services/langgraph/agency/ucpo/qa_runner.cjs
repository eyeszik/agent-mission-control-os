// Browser QA for a static export, run inside the UCPO sandbox (no network namespace).
// Pages are served by Playwright route fulfilment from the export directory on a reserved
// origin; any request to another origin is aborted and recorded. Writes one JSON result file.
// Usage: node qa_runner.cjs <config.json>
"use strict";
const fs = require("fs");
const path = require("path");

const ORIGIN = "http://amc-preview.invalid";
const TYPES = { ".html": "text/html; charset=utf-8", ".js": "application/javascript", ".css": "text/css",
  ".svg": "image/svg+xml", ".txt": "text/plain; charset=utf-8", ".json": "application/json", ".ico": "image/x-icon",
  ".woff2": "font/woff2", ".png": "image/png" };

async function serve(ctx, root, aborted) {
  await ctx.route("**/*", async (route) => {
    const u = new URL(route.request().url());
    if (u.origin !== ORIGIN) { aborted.push(u.href); return route.abort(); }
    let p = decodeURIComponent(u.pathname);
    if (p.endsWith("/")) p += "index.html";
    let f = path.resolve(root, "." + p);
    if (f !== root && !f.startsWith(root + path.sep)) return route.fulfill({ status: 403, body: "forbidden" });
    if (!fs.existsSync(f) && fs.existsSync(f + ".html")) f += ".html";
    if (!fs.existsSync(f) || !fs.statSync(f).isFile()) return route.fulfill({ status: 404, body: "not found" });
    return route.fulfill({ status: 200, body: fs.readFileSync(f), contentType: TYPES[path.extname(f)] || "application/octet-stream" });
  });
}

function collect() {
  const norm = (t) => (t || "").replace(/\s+/g, " ").trim();
  const evidence = {};
  for (const el of document.querySelectorAll("[data-req]")) {
    const id = el.getAttribute("data-req");
    // textContent, not innerText: copy is compared as authored, before CSS text-transform. Hidden copy does not count.
    const visible = el.tagName === "HTML" || el.tagName === "MAIN" || el.checkVisibility();
    let text;
    if (el.tagName === "HTML") text = el.getAttribute("lang") || "";
    else if (el.tagName === "MAIN") text = document.title;
    else if (el.tagName === "IMG") text = el.getAttribute("alt") || "";
    else if (el.tagName === "A") text = norm(el.textContent) + " -> " + (el.getAttribute("href") || "");
    else text = [...el.childNodes].map((n) => norm(n.textContent)).filter(Boolean).join(" | ");
    (evidence[id] = evidence[id] || []).push(visible ? text : "__hidden__:" + text);
  }
  const bgOf = (el) => {
    for (let n = el; n; n = n.parentElement) {
      const c = getComputedStyle(n).backgroundColor;
      if (c && c !== "transparent" && !/rgba\(.*,\s*0\)$/.test(c)) return c;
    }
    return "rgb(255, 255, 255)";
  };
  const colours = new Set();
  for (const el of document.body.querySelectorAll("*")) {
    const s = getComputedStyle(el);
    if (s.display === "none" || s.visibility === "hidden") continue;
    const own = [...el.childNodes].some((n) => n.nodeType === 3 && n.textContent.trim());
    if (own) colours.add(["text", s.color, bgOf(el), parseFloat(s.fontSize), parseInt(s.fontWeight, 10)].join("|"));
    if (parseFloat(s.borderTopWidth) > 0 && s.borderTopStyle !== "none")
      colours.add(["graphic", s.borderTopColor, bgOf(el.parentElement || el), 0, 0].join("|"));
  }
  const headings = [...document.querySelectorAll("h1,h2,h3,h4,h5,h6")].map((h) => parseInt(h.tagName[1], 10));
  const landmarks = {
    banner: document.querySelectorAll("body > header, [role=banner]").length,
    navigation: document.querySelectorAll("nav, [role=navigation]").length,
    main: document.querySelectorAll("main, [role=main]").length,
    contentinfo: document.querySelectorAll("body > footer, [role=contentinfo]").length,
  };
  const unnamedNav = [...document.querySelectorAll("nav")].filter((n) => !n.getAttribute("aria-label")).length;
  return { evidence, colours: [...colours].sort(), headings, landmarks, unnamedNav, title: document.title,
    lang: document.documentElement.lang, text: norm(document.body.innerText) };
}

function overflow() {
  const d = document.documentElement;
  return { scrollWidth: d.scrollWidth, innerWidth: window.innerWidth, overflow: d.scrollWidth > window.innerWidth + 1 };
}

function motion() {
  const slow = [];
  for (const el of document.querySelectorAll("*")) {
    const s = getComputedStyle(el);
    const durs = (s.transitionDuration + "," + s.animationDuration).split(",").map((v) => parseFloat(v) || 0);
    if (durs.some((v) => v > 0.01)) slow.push(el.tagName.toLowerCase() + "." + el.className);
  }
  return { animations: document.getAnimations().length, slow: slow.slice(0, 10), slowCount: slow.length,
    scrollBehavior: getComputedStyle(document.documentElement).scrollBehavior };
}

async function main() {
  const cfg = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
  const root = path.resolve(cfg.out_dir);
  const { chromium } = require("playwright");
  const browser = await chromium.launch({ args: ["--no-sandbox"] });
  const axe = fs.readFileSync(cfg.axe_path, "utf8");
  const result = { browser: { name: "chromium", version: browser.version() }, routes: {}, aborted: [] };
  const shots = {};
  try {
    for (const route of cfg.routes) {
      const r = { status: null, console: [], viewports: {} };
      const aborted = [];
      const ctx = await browser.newContext({ viewport: { width: 1280, height: 900 } });
      await serve(ctx, root, aborted);
      const page = await ctx.newPage();
      page.on("console", (m) => { if (m.type() === "error") r.console.push(m.text().slice(0, 300)); });
      page.on("pageerror", (e) => r.console.push("pageerror: " + String(e).slice(0, 300)));
      const resp = await page.goto(ORIGIN + route, { waitUntil: "networkidle" });
      r.status = resp ? resp.status() : null;
      r.dom = await page.evaluate(collect);
      await page.addScriptTag({ content: axe });
      r.axe = await page.evaluate(async () => {
        const res = await window.axe.run(document, { runOnly: { type: "tag",
          values: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"] }, resultTypes: ["violations"] });
        return { version: window.axe.version, violations: res.violations.map((v) => ({ id: v.id, impact: v.impact,
          nodes: v.nodes.length, sample: (v.nodes[0] && v.nodes[0].target.join(" ")) || "" })) };
      });
      // Keyboard: the first stop must be the skip link, and every stop must show a visible indicator.
      const stops = [];
      for (let i = 0; i < 30; i++) {
        await page.keyboard.press("Tab");
        const d = await page.evaluate(() => {
          const el = document.activeElement;
          if (!el || el === document.body) return null;
          const s = getComputedStyle(el);
          const r = el.getBoundingClientRect();
          return { tag: el.tagName.toLowerCase(), cls: el.className || "", href: el.getAttribute("href") || "",
            outline: s.outlineStyle !== "none" && parseFloat(s.outlineWidth) >= 2, shadow: s.boxShadow !== "none",
            inView: r.bottom > 0 && r.right > 0 && r.top < window.innerHeight + 2000 };
        });
        if (!d) break;
        if (stops.length && d.href === stops[0].href && d.cls === stops[0].cls) break;
        stops.push(d);
      }
      r.keyboard = stops;
      for (const vp of cfg.viewports) {
        await page.setViewportSize({ width: vp, height: 900 });
        await page.waitForTimeout(50);
        r.viewports[String(vp)] = await page.evaluate(overflow);
        const file = path.join(cfg.evidence_dir, (route === "/" ? "index" : route.replace(/\//g, "")) + "@" + vp + ".png");
        await page.screenshot({ path: file, fullPage: true });
        shots[route + "@" + vp] = file;
      }
      await page.setViewportSize({ width: 1280, height: 900 });
      await page.evaluate(() => { document.documentElement.style.fontSize = "200%"; });
      await page.waitForTimeout(50);
      r.zoom_text_200 = await page.evaluate(overflow);
      await page.evaluate(() => { document.documentElement.style.fontSize = ""; });
      await page.setViewportSize({ width: 640, height: 450 });
      r.zoom_page_200 = await page.evaluate(overflow);
      await ctx.close();

      const rctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "reduce" });
      await serve(rctx, root, aborted);
      const rpage = await rctx.newPage();
      await rpage.goto(ORIGIN + route, { waitUntil: "networkidle" });
      r.reduced_motion = await rpage.evaluate(motion);
      await rctx.close();
      const mctx = await browser.newContext({ viewport: { width: 1280, height: 900 }, reducedMotion: "no-preference" });
      await serve(mctx, root, aborted);
      const mpage = await mctx.newPage();
      await mpage.goto(ORIGIN + route, { waitUntil: "networkidle" });
      r.default_motion = await mpage.evaluate(motion);
      await mctx.close();
      r.aborted = aborted;
      result.routes[route] = r;
    }
  } finally {
    await browser.close();
  }
  result.screenshots = shots;
  fs.writeFileSync(cfg.result_path, JSON.stringify(result));
}

main().catch((e) => { console.error("QA_RUNNER_ERROR " + (e && e.stack ? e.stack : e)); process.exit(1); });
