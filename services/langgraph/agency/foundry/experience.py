"""Living Experience Twin: ExperienceIR -> a working HTML section, evaluated by real interaction.

The section is HTML + CSS + vanilla JS that runs as-is in a browser. Styling is
split in three layers: ``tokens`` (DTCG output of the genome), ``structure``
(layout, focus, reduced motion, reflow; never colour-dependent) and ``skin``
(the visual grammar). The counterfactual skin engine swaps or removes only the
skin and re-runs the identical scenarios, so a visual treatment can never be
accepted if it breaks a task.

The page's backend is an in-page stub selected by ``window.__amcBackend``
(ok / error / denied / empty / long / slow). It makes no network request; the
browser harness aborts any that is attempted. Results are what the browser
observed, not what this module expects.
"""

from __future__ import annotations

import base64
import json
from html import escape
from pathlib import Path
from typing import Optional

from . import compose
from .contracts import ComponentContract, CreativeGenome, ExperienceIR, UserBrief
from .tokens import compile_tokens

STRUCTURE_CSS = """
*,*::before,*::after{box-sizing:border-box}
html{-webkit-text-size-adjust:100%}
body{margin:0;line-height:1.5;overflow-wrap:anywhere}
img,svg{max-width:100%;height:auto}
.skip{position:absolute;left:-999px;top:0;padding:.75rem 1rem;z-index:10}
.skip:focus{left:1rem}
:where(a,button,input,select,textarea):focus-visible{outline:3px solid currentColor;outline-offset:3px}
.site-header,main>section,footer{padding:1.5rem clamp(1rem,5vw,4rem)}
.site-header{display:flex;flex-wrap:wrap;gap:1rem;justify-content:space-between;align-items:center}
.site-header nav{display:flex;gap:1rem;flex-wrap:wrap}
.hero{display:grid;gap:1rem;max-width:60rem}
.hero-mark{width:clamp(4rem,12vw,7rem);animation:amc-rise .5s ease-out both}
@keyframes amc-rise{from{opacity:0;transform:translateY(1.5rem)}to{opacity:1;transform:none}}
h1{font-size:clamp(2rem,6vw,4rem);line-height:1.05;margin:0}
.cards{list-style:none;margin:0;padding:0;display:grid;gap:1rem;grid-template-columns:repeat(auto-fit,minmax(min(100%,16rem),1fr))}
.cards li{padding:1rem}
form{display:grid;gap:1rem;max-width:32rem}
.field{display:grid;gap:.35rem}
.field.check{grid-template-columns:auto 1fr;align-items:center;column-gap:.6rem}
.field.check .error{grid-column:1/-1}
input[type=email]{min-height:44px;padding:.5rem .75rem;font:inherit;width:100%}
input[type=checkbox]{width:1.4rem;height:1.4rem}
button,.button{min-height:44px;min-width:44px;padding:.6rem 1.2rem;font:inherit;cursor:pointer;display:inline-flex;align-items:center;justify-content:center;width:fit-content}
.error::before{content:"\\26A0\\FE0E  "}
[hidden]{display:none!important}
@media (prefers-reduced-motion: reduce){*,*::before,*::after{animation-duration:0s!important;animation-iteration-count:1!important;transition-duration:0s!important}.hero-mark{animation:none}}
"""


def skin_css(dark: bool = False) -> str:
    fg, bg = ("var(--amc-color-paper)", "var(--amc-color-ink)") if dark else ("var(--amc-color-ink)", "var(--amc-color-paper)")
    return f"""
body{{background:{bg};color:{fg};font-family:var(--amc-font-text)}}
h1,h2,.wordmark{{font-family:var(--amc-font-display);font-weight:var(--amc-weight-display)}}
.wordmark{{font-size:1.25rem;letter-spacing:.02em}}
a{{color:{fg};text-decoration-thickness:2px;text-underline-offset:3px}}
.skip{{background:{fg};color:{bg}}}
.site-header{{border-bottom:4px solid var(--amc-color-accent)}}
.hero .lede{{font-size:1.25rem;max-width:40rem}}
button,.button{{background:{fg};color:{bg};border:0;border-radius:var(--amc-radius-control);font-weight:600;text-decoration:none}}
#retry{{background:transparent;color:{fg};border:2px solid {fg}}}
.cards li{{border:2px solid var(--amc-color-accent);border-radius:var(--amc-radius-panel)}}
input[type=email]{{background:{bg};color:{fg};border:2px solid {fg};border-radius:var(--amc-radius-control)}}
input[type=checkbox]{{accent-color:var(--amc-color-accent)}}
.hint{{margin:0;opacity:.95}}
.error{{margin:0;font-weight:600}}
#status{{font-weight:600;min-height:1.5rem}}
footer{{border-top:1px solid {fg}}}
"""


def compile_experience(genome: CreativeGenome, brief: UserBrief, *, headline: str, subhead: str, cta: str) -> ExperienceIR:
    action = brief.desired_action or "Join the list"
    comps = (
        ComponentContract(component_id="skip_link", role="navigation", props=("href",), states=("hidden", "focused"),
                          keyboard="first Tab stop; Enter moves focus to main", validation="n/a", focus="visible when focused",
                          loading="n/a", error="n/a", responsive="fixed position", tokens=("color.ink", "color.paper")),
        ComponentContract(component_id="hero", role="region", props=("headline", "subhead", "cta"), states=("first_use", "returning"),
                          keyboard="CTA reachable by Tab", validation="n/a", focus="CTA ring", loading="n/a", error="n/a",
                          responsive="fluid type clamp(2rem,6vw,4rem)", tokens=("font.display", "weight.display", "motion.duration")),
        ComponentContract(component_id="offering_list", role="list", props=("items",), states=("populated", "empty", "long_content"),
                          keyboard="not interactive", validation="n/a", focus="n/a", loading="n/a", error="empty state text",
                          responsive="auto-fit grid, min(100%,16rem)", tokens=("color.accent", "radius.panel")),
        ComponentContract(component_id="signup_form", role="form", props=("email", "consent"),
                          states=("idle", "invalid", "loading", "success", "network_error", "permission_denied"),
                          keyboard="Tab through email, consent (Space), submit (Enter)",
                          validation="email format and consent required; errors in text, not colour alone",
                          focus="first invalid field receives focus", loading="button disabled + aria-busy + 'Sending…'",
                          error="role=status message; retry button for network errors", responsive="single column, max 32rem",
                          tokens=("radius.control", "target.min", "focus.ring")),
    )
    return ExperienceIR(
        jobs_to_be_done=(f"Understand what {genome.brand_name} offers", action),
        user_flow=("land", "scan offerings", "enter email", "consent", "submit", "confirmation"),
        information_architecture=("header: wordmark + primary nav", "hero", "offerings", "signup", "footer"),
        components=comps,
        state_matrix={c.component_id: c.states for c in comps},
        copy_text={"headline": headline, "subhead": subhead, "cta": cta, "action": action},
        genome_hash=genome.content_hash,
    )


def render_html(ir: ExperienceIR, genome: CreativeGenome, *, skin: Optional[str] = "canonical",
                skin_genome: Optional[CreativeGenome] = None, offerings: tuple[tuple[str, str], ...] = ()) -> str:
    source = skin_genome or genome
    _, tokens_css, _ = compile_tokens(source)
    dark = skin == "alternate_dark"
    skin_block = "" if skin == "unstyled" else skin_css(dark)
    mark_svg = compose.to_svg(compose.mark(source, size=160, on="ink" if dark else "paper"), source)
    mark_uri = "data:image/svg+xml;base64," + base64.b64encode(mark_svg.encode()).decode()
    c = ir.copy_text
    items = offerings or (("Everyday plates", "Stoneware made in small batches."),
                          ("Serving bowls", "Deep, glazed and dishwasher safe."),
                          ("Repairs", "We mend what we make."))
    script = """
(function(){
  var DEFAULT = __ITEMS__;
  window.__amcBackend = window.__amcBackend || 'ok';
  window.__amcSession = window.__amcSession || 'first';
  var list = document.getElementById('offering-list'), empty = document.getElementById('offerings-empty');
  function data(){ var m = window.__amcBackend; if (m === 'empty') return [];
    if (m === 'long') return DEFAULT.concat([['An unusually long offering title that keeps going to test wrapping behaviour across narrow viewports', 'Supercalifragilisticexpialidociousstonewarewithoutanybreakingopportunityatall and more words to wrap.']]);
    return DEFAULT; }
  window.renderOfferings = function(){ list.innerHTML = ''; var items = data();
    items.forEach(function(it){ var li = document.createElement('li'); var h = document.createElement('h3'); h.textContent = it[0];
      var p = document.createElement('p'); p.textContent = it[1]; li.appendChild(h); li.appendChild(p); list.appendChild(li); });
    empty.hidden = items.length > 0; list.hidden = items.length === 0; };
  window.renderGreeting = function(){ var g = document.getElementById('greeting');
    if (window.__amcSession === 'returning') { g.textContent = 'Welcome back. Your preferences are saved.'; g.hidden = false; }
    else { g.hidden = true; } };
  function backend(){ return new Promise(function(res, rej){ var m = window.__amcBackend;
    setTimeout(function(){ if (m === 'error') rej({kind: 'network'}); else if (m === 'denied') rej({kind: 'denied'}); else res({ok: true}); },
      m === 'slow' ? 800 : 120); }); }
  var form = document.getElementById('signup'), email = document.getElementById('email'), consent = document.getElementById('consent');
  var status = document.getElementById('status'), submit = document.getElementById('submit'), retry = document.getElementById('retry');
  function setError(input, id, msg){ var e = document.getElementById(id); e.textContent = msg ? 'Error: ' + msg : ''; e.hidden = !msg;
    if (msg) input.setAttribute('aria-invalid', 'true'); else input.removeAttribute('aria-invalid'); }
  form.addEventListener('submit', function(ev){ ev.preventDefault(); retry.hidden = true;
    var bad = null;
    if (!/^[^\\s@]+@[^\\s@]+\\.[^\\s@]+$/.test(email.value.trim())) { setError(email, 'email-error', 'Enter a valid email address, like name@example.com'); bad = bad || email; }
    else setError(email, 'email-error', '');
    if (!consent.checked) { setError(consent, 'consent-error', 'Tick the box to agree to be contacted'); bad = bad || consent; }
    else setError(consent, 'consent-error', '');
    if (bad) { status.textContent = 'Please fix the highlighted fields.'; bad.focus(); return; }
    submit.disabled = true; submit.setAttribute('aria-busy', 'true'); submit.textContent = 'Sending…'; status.textContent = 'Sending…';
    backend().then(function(){ status.textContent = "Thanks. You're on the list."; form.reset(); })
      .catch(function(err){ if (err.kind === 'network') { status.textContent = "We couldn't reach the server. Check your connection and try again."; retry.hidden = false; }
        else { status.textContent = "You're not allowed to join this list from here."; } })
      .then(function(){ submit.disabled = false; submit.removeAttribute('aria-busy'); submit.textContent = 'Join'; });
  });
  retry.addEventListener('click', function(){ form.requestSubmit(); });
  window.renderOfferings(); window.renderGreeting();
})();
""".replace("__ITEMS__", json.dumps([list(i) for i in items]))
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(genome.brand_name)}: {escape(c['headline'])}</title>
<meta name="generator" content="amc-foundry experience twin; genome {genome.content_hash[:16]}; skin {skin}">
<style id="tokens">{tokens_css}</style>
<style id="structure">{STRUCTURE_CSS}</style>
<style id="skin">{skin_block}</style>
</head><body>
<a class="skip" href="#main">Skip to content</a>
<header class="site-header"><span class="wordmark">{escape(genome.brand_name)}</span>
<nav aria-label="Primary"><a href="#offerings">Offerings</a> <a href="#join">Join</a></nav></header>
<main id="main" tabindex="-1">
<section class="hero" aria-labelledby="hero-title">
<img class="hero-mark" alt="" src="{mark_uri}" width="112" height="112">
<p id="greeting" class="greeting" hidden></p>
<h1 id="hero-title">{escape(c['headline'])}</h1>
<p class="lede">{escape(c['subhead'])}</p>
<a class="button" id="cta" href="#join">{escape(c['cta'])}</a>
</section>
<section id="offerings" aria-labelledby="off-title"><h2 id="off-title">Offerings</h2>
<ul class="cards" id="offering-list"></ul><p id="offerings-empty" hidden>No offerings yet. Check back soon.</p></section>
<section id="join" aria-labelledby="join-title"><h2 id="join-title">{escape(c['action'])}</h2>
<form id="signup" novalidate>
<div class="field"><label for="email">Email address</label>
<input id="email" name="email" type="email" autocomplete="email" aria-describedby="email-hint email-error" required>
<p id="email-hint" class="hint">We only use this to reply.</p><p id="email-error" class="error" hidden></p></div>
<div class="field check"><input id="consent" name="consent" type="checkbox" aria-describedby="consent-error">
<label for="consent">I agree to be contacted</label><p id="consent-error" class="error" hidden></p></div>
<button id="submit" type="submit">Join</button>
</form>
<div id="status" role="status" aria-live="polite"></div>
<button id="retry" type="button" hidden>Try again</button>
</section></main>
<footer><p>{escape(genome.brand_name)}. Fictional demonstration content.</p></footer>
<script>{script}</script>
</body></html>
"""


def _submit_valid(backend: str) -> list[dict]:
    return [{"action": "set", "name": "__amcBackend", "value": backend},
            {"action": "fill", "selector": "#email", "value": "reader@example.org"},
            {"action": "click", "selector": "#consent"}, {"action": "click", "selector": "#submit"},
            {"action": "wait", "value": 400}]


def scenarios(*, primary_font: str) -> list[dict]:
    """The scenario matrix from the brief. Every step is executed by the browser, not asserted here."""
    return [
        {"id": "first_use", "capture": True, "steps": [
            {"action": "expect_visible", "selector": "#hero-title"}, {"action": "expect_visible", "selector": "#greeting", "value": False},
            {"action": "expect_text", "selector": "#offering-list", "value": "Everyday"}]},
        {"id": "keyboard_only", "steps": [
            {"action": "tab", "times": 1}, {"action": "expect_focus", "selector": "a.skip"},
            {"action": "tab_until", "selector": "#email"}, {"action": "expect_focus", "selector": "#email"},
            {"action": "type", "value": "reader@example.org"}, {"action": "tab_until", "selector": "#consent"},
            {"action": "press", "value": "Space"}, {"action": "tab_until", "selector": "#submit"},
            {"action": "expect_focus", "selector": "#submit"}, {"action": "press", "value": "Enter"}, {"action": "wait", "value": 400},
            {"action": "expect_text", "selector": "#status", "value": "on the list"}]},
        {"id": "invalid_input", "steps": [
            {"action": "tab_until", "selector": "#email"}, {"action": "type", "value": "not-an-email"},
            {"action": "tab_until", "selector": "#submit"}, {"action": "press", "value": "Enter"}, {"action": "wait", "value": 100},
            {"action": "expect_text", "selector": "#email-error", "value": "valid email"},
            {"action": "expect_attr", "selector": "#email", "name": "aria-invalid", "value": "true"},
            {"action": "expect_focus", "selector": "#email"},
            {"action": "expect_text", "selector": "#consent-error", "value": "Tick the box"}]},
        {"id": "returning_user", "steps": [
            {"action": "set", "name": "__amcSession", "value": "returning"}, {"action": "call", "value": "renderGreeting"},
            {"action": "expect_text", "selector": "#greeting", "value": "Welcome back"}]},
        {"id": "network_interruption", "steps": _submit_valid("error") + [
            {"action": "expect_text", "selector": "#status", "value": "couldn't reach"},
            {"action": "expect_visible", "selector": "#retry"},
            {"action": "set", "name": "__amcBackend", "value": "ok"}, {"action": "click", "selector": "#retry"},
            {"action": "wait", "value": 400}, {"action": "expect_text", "selector": "#status", "value": "on the list"}]},
        {"id": "permission_denied", "steps": _submit_valid("denied") + [
            {"action": "expect_text", "selector": "#status", "value": "not allowed"}]},
        {"id": "empty_data", "steps": [
            {"action": "set", "name": "__amcBackend", "value": "empty"}, {"action": "call", "value": "renderOfferings"},
            {"action": "expect_visible", "selector": "#offerings-empty"},
            {"action": "expect_text", "selector": "#offerings-empty", "value": "No offerings yet"}]},
        {"id": "long_content", "viewport": {"width": 360, "height": 800}, "steps": [
            {"action": "set", "name": "__amcBackend", "value": "long"}, {"action": "call", "value": "renderOfferings"},
            {"action": "expect_no_overflow"}]},
        {"id": "small_viewport", "viewport": {"width": 320, "height": 640}, "capture": True, "steps": [
            {"action": "expect_no_overflow"}, {"action": "expect_visible", "selector": "#submit"}]},
        {"id": "large_text", "text_scale": 2, "viewport": {"width": 1280, "height": 900}, "steps": [
            {"action": "expect_no_overflow"}, {"action": "expect_visible", "selector": "#email"}]},
        {"id": "reduced_motion", "reduced_motion": True, "steps": [
            {"action": "expect_no_animation", "selector": ".hero-mark"}]},
        {"id": "font_fallback", "steps": [
            {"action": "expect_font_fallback", "selector": "#hero-title", "value": primary_font}]},
    ]


def evaluate(html: str, *, out_dir: Path, primary_font: str) -> dict:
    """Run every scenario in local Chromium and fold the page audits into one verdict."""
    from services.langgraph.agency.visual.browser import run_experience

    run = run_experience(html, scenarios(primary_font=primary_font), out_dir=out_dir)
    audit_findings = []
    for sc in run["scenarios"]:
        a = sc["audit"]
        if a["contrast_failures"]:
            audit_findings.append(f"CONTRAST:{sc['id']}:{len(a['contrast_failures'])}")
        if a["unlabeled_controls"]:
            audit_findings.append(f"UNLABELED:{sc['id']}:{a['unlabeled_controls']}")
    findings = list(run["findings"]) + audit_findings
    return {"status": "PASSED" if not findings and run["scenarios"] else "FAILED", "findings": findings,
            "scenarios": [{"id": s["id"], "passed": s["passed"], "steps": [{k: v for k, v in st.items() if k in
                           ("action", "selector", "ok", "detail")} for st in s["steps"]], "audit": s["audit"],
                           "page_errors": s["page_errors"], "capture": s["capture"]} for s in run["scenarios"]],
            "network_isolated": run["network_isolated"], "blocked_requests": run["result"].get("blocked_requests", []),
            "browser": run["result"].get("browser_version"), "wall_ms": run["wall_ms"]}


def counterfactual_skins(ir: ExperienceIR, genome: CreativeGenome, *, alternate: CreativeGenome, out_dir: Path) -> dict:
    """Same structure, three presentations; a skin is rejected if any task or audit regresses."""
    primary = genome.typography_rules["stacks"]["display"][0]
    results = {}
    for name, kw in (("canonical", {"skin": "canonical"}), ("unstyled", {"skin": "unstyled"}),
                     ("alternate_dark", {"skin": "alternate_dark", "skin_genome": alternate})):
        html = render_html(ir, genome, **kw)
        ev = evaluate(html, out_dir=out_dir / name, primary_font=primary)
        results[name] = {"status": ev["status"], "findings": ev["findings"],
                         "passed_scenarios": sum(1 for s in ev["scenarios"] if s["passed"]), "total": len(ev["scenarios"]),
                         "contrast_failures": sum(len(s["audit"]["contrast_failures"]) for s in ev["scenarios"])}
    base = results["canonical"]
    for name, r in results.items():
        r["regressions"] = [] if name == "canonical" else [
            m for m, worse in (("tasks", r["passed_scenarios"] < base["passed_scenarios"]),
                               ("contrast", r["contrast_failures"] > base["contrast_failures"])) if worse]
        r["accepted"] = r["status"] == "PASSED" and not r["regressions"]
    return results


__all__ = ["STRUCTURE_CSS", "compile_experience", "counterfactual_skins", "evaluate", "render_html", "scenarios", "skin_css"]
