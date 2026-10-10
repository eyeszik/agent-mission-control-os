"""CreativeGenome -> CompositionIR -> SVG. Seeded, pure and renderer-independent until ``to_svg``.

Every colour in a CompositionIR is a palette *role*; literal colours appear only
when ``to_svg`` resolves roles against the genome's palette, so one composition
re-skins under a different genome without touching geometry. Text never sits on
primitives: primitives are confined to the art zone and text to the type zone,
and a dark-ground grammar flips text to paper-on-ink.
"""

from __future__ import annotations

import math
import random
from typing import Iterable, Optional
from xml.sax.saxutils import escape

from .contracts import CompositionIR, CreativeGenome, Primitive, TextBlock
from .genome import FONT_STACKS

DARK_GROUND = {"retro_computing", "synthetic_futurism", "cinematic_typography"}


def _rng(genome: CreativeGenome, salt: str, variant_seed: int = 0) -> random.Random:
    return random.Random(f"{genome.deterministic_seed}:{variant_seed}:{salt}")


def _allot(weights: dict[str, float], total: int) -> dict[str, int]:
    raw = {g: w * total for g, w in weights.items()}
    out = {g: int(math.floor(v)) for g, v in raw.items()}
    for g in sorted(raw, key=lambda k: (raw[k] - out[k], k), reverse=True)[: total - sum(out.values())]:
        out[g] += 1
    return {g: n for g, n in out.items() if n > 0}


def _primitives_for(grammar: str, n: int, rng: random.Random, box: tuple[float, float, float, float],
                    cols: int, angle: float) -> list[Primitive]:
    x0, y0, w, h = box
    col = w / max(1, cols)
    out: list[Primitive] = []

    def P(**kw) -> None:
        out.append(Primitive(grammar=grammar, **kw))

    for i in range(n):
        u, v = rng.random(), rng.random()
        if grammar == "swiss_editorial":
            if i % 3 == 0:
                c = rng.randrange(cols // 2)
                P(kind="rect", x=x0 + c * col, y=y0 + v * h * 0.5, w=col * rng.choice((3, 4, 5)), h=h * (0.18 + u * 0.25), fill="accent")
            elif i % 3 == 1:
                P(kind="line", x=x0, y=y0 + v * h, w=w, h=0, fill="ink", stroke="ink", stroke_width=2)
            else:
                P(kind="bar", x=x0 + rng.randrange(cols) * col, y=y0 + u * h * 0.6, w=col * 0.5, h=h * 0.35, fill="ink")
        elif grammar == "bauhaus_geometry":
            kind = ("circle", "triangle", "rect")[i % 3]
            size = min(w, h) * (0.22 + u * 0.3)
            P(kind=kind, x=x0 + u * (w - size), y=y0 + v * (h - size), w=size, h=size, r=size / 2,
              fill=("accent", "accent_2", "ink")[i % 3], rotation=0 if kind != "triangle" else rng.choice((0, 90, 180)))
        elif grammar == "constructivist":
            if i % 2 == 0:
                P(kind="bar", x=x0 + u * w * 0.5, y=y0 + v * h, w=w * (0.5 + u * 0.5), h=h * 0.06, rotation=angle, fill="accent")
            else:
                s = min(w, h) * (0.25 + u * 0.2)
                P(kind="triangle", x=x0 + u * (w - s), y=y0 + v * (h - s), w=s, h=s, rotation=angle, fill="ink")
        elif grammar == "art_deco":
            if i == 0:
                P(kind="fan", x=x0 + w / 2, y=y0 + h * 0.95, r=min(w / 2, h * 0.85), fill="accent", stroke="accent", stroke_width=3)
            else:
                inset = 10 + i * 14
                P(kind="rect", x=x0 + inset, y=y0 + inset, w=w - 2 * inset, h=h - 2 * inset, fill="none", stroke="accent_2",
                  stroke_width=2)
        elif grammar == "modern_minimalism":
            if i == 0:
                s = min(w, h) * 0.18
                P(kind="circle", x=x0 + w * 0.62, y=y0 + h * 0.2, w=s, h=s, r=s / 2, fill="accent")
            else:
                P(kind="line", x=x0, y=y0 + h * (0.6 + 0.1 * i), w=w * 0.3, h=0, fill="ink", stroke="ink", stroke_width=1.5)
        elif grammar == "retro_computing":
            px = 16 + 8 * (i % 2)
            cx, cy = x0 + u * (w - px * 8), y0 + v * (h - px * 6)
            for k in range(rng.randrange(8, 20)):
                P(kind="pixel_block", x=cx + rng.randrange(8) * px, y=cy + rng.randrange(6) * px, w=px, h=px,
                  fill=rng.choice(("accent", "accent_2", "paper")))
        elif grammar == "tactile_paper":
            cw, ch = w * (0.4 + u * 0.3), h * (0.3 + v * 0.3)
            x, y = x0 + u * (w - cw), y0 + v * (h - ch)
            P(kind="card", x=x + 10, y=y + 12, w=cw, h=ch, fill="ink", opacity=0.12, corner=2)
            P(kind="card", x=x, y=y, w=cw, h=ch, fill=("muted", "accent", "accent_2")[i % 3], corner=2, rotation=(u - 0.5) * 6)
        elif grammar == "dimensional_glass":
            cw, ch = w * (0.35 + u * 0.3), h * (0.25 + v * 0.3)
            P(kind="card", x=x0 + u * (w - cw), y=y0 + v * (h - ch), w=cw, h=ch, fill=("accent", "accent_2")[i % 2],
              opacity=0.35, corner=28)
        elif grammar == "synthetic_futurism":
            r = min(w, h) * 0.5 * min(1.0, 0.3 + 0.18 * i)  # stays inside the art zone, never over type
            P(kind="ring", x=x0 + w * 0.5, y=y0 + h * 0.5, r=r, fill="none", stroke=("accent", "paper", "accent_2")[i % 3],
              stroke_width=1.5 + (i % 2))
        elif grammar == "cinematic_typography":
            P(kind="bar", x=x0 - 400, y=y0 + (0 if i % 2 == 0 else h * 0.92), w=w + 800, h=h * 0.08, fill="accent" if i else "ink")
        elif grammar == "experimental_collage":
            cw, ch = w * (0.25 + u * 0.4), h * (0.15 + v * 0.3)
            if i % 3 == 2:
                P(kind="dots", x=x0 + u * (w - cw), y=y0 + v * (h - ch), w=cw, h=ch, r=4, fill="ink")
            else:
                P(kind="rect", x=x0 + u * (w - cw), y=y0 + v * (h - ch), w=cw, h=ch, rotation=(u - 0.5) * 30,
                  fill=("accent", "accent_2", "muted")[i % 3])
        elif grammar == "spatial_interface":
            cw, ch = w * (0.45 + u * 0.2), h * (0.22 + v * 0.15)
            x, y = x0 + u * (w - cw), y0 + i * h * 0.18
            P(kind="card", x=x + 6, y=y + 14, w=cw, h=ch, fill="ink", opacity=0.10, corner=20)
            P(kind="card", x=x, y=y, w=cw, h=ch, fill="paper", stroke="muted", stroke_width=1.5, corner=20)
            P(kind="circle", x=x + 24, y=y + 24, w=28, h=28, r=14, fill="accent")
    return out


def _wrap(text: str, size: float, max_width: float) -> list[str]:
    per_line = max(8, int(max_width / (size * 0.56)))
    lines, line = [], ""
    for word in text.split():
        if line and len(line) + 1 + len(word) > per_line:
            lines.append(line)
            line = word
        else:
            line = f"{line} {word}".strip()
    return (lines + [line])[:4] if line else lines[:4]


def poster(genome: CreativeGenome, *, headline: str, subhead: str = "", cta: str = "", meta: str = "",
           width: int = 1200, height: int = 1600, variant_seed: int = 0,
           overrides: Optional[dict] = None) -> CompositionIR:
    o = dict(overrides or {})
    weights = o.get("grammar_weights") or genome.grammar_weights
    dominant = max(sorted(weights), key=lambda k: weights[k])
    margin = width * float(o.get("margin", genome.layout_rules["margin"]))
    density = float(o.get("density", genome.composition_rules["density"]))
    cols = int(o.get("columns", genome.layout_rules["columns"]))
    angle = float(o.get("angle", genome.geometry_rules["angle"]))
    scale = float(o.get("headline_scale", genome.composition_rules["headline_scale"]))
    art = (margin, margin, width - 2 * margin, height * 0.58 - margin)
    rng = _rng(genome, "poster", variant_seed)
    prims: list[Primitive] = []
    for g, n in sorted(_allot(weights, 3 + round(density * 10)).items()):
        prims += _primitives_for(g, n, random.Random(f"{rng.random()}:{g}"), art, cols, angle)
    dark = dominant in DARK_GROUND
    text_fill, bg = ("paper", "ink") if dark else ("ink", "paper")
    size = width * scale
    centered = dominant in {"art_deco", "cinematic_typography"}
    x = width / 2 if centered else margin
    anchor = "middle" if centered else "start"
    y = height * 0.66
    blocks: list[TextBlock] = []
    weight = int(o.get("display_weight", genome.typography_rules.get("display_weight", 700)))
    for line in _wrap(headline, size, width - 2 * margin):
        blocks.append(TextBlock(role="headline", text=line, x=x, y=y, size=round(size, 2), weight=weight, anchor=anchor,
                                fill=text_fill, tracking=genome.typography_rules.get("tracking", 0)))
        y += size * 1.05
    if subhead:
        y += size * 0.25
        for line in _wrap(subhead, size * 0.32, width - 2 * margin):
            blocks.append(TextBlock(role="subhead", text=line, x=x, y=y, size=round(size * 0.32, 2), weight=400,
                                    family="text", anchor=anchor, fill=text_fill))
            y += size * 0.42
    foot = height - margin
    blocks.append(TextBlock(role="wordmark", text=genome.brand_name, x=margin, y=foot, size=round(width * 0.03, 2),
                            weight=700, anchor="start", fill=text_fill, tracking=0.04))
    if cta:
        blocks.append(TextBlock(role="cta", text=cta, x=width - margin, y=foot, size=round(width * 0.022, 2), weight=600,
                                family="text", anchor="end", fill="accent" if not dark else "paper"))
    if meta:
        blocks.append(TextBlock(role="meta", text=meta, x=margin, y=margin * 0.62, size=round(width * 0.014, 2),
                                weight=500, family="mono", anchor="start", fill=text_fill))
    return CompositionIR(kind="poster", width=width, height=height, background=bg, primitives=tuple(prims), text=tuple(blocks),
                         genome_hash=genome.content_hash, grammar_weights=dict(weights), seed=variant_seed,
                         title=f"{genome.brand_name} poster")


def mark(genome: CreativeGenome, *, size: int = 256, on: str = "paper") -> CompositionIR:
    m = genome.geometry_rules["mark"]
    s = size
    P = lambda **kw: Primitive(grammar="mark", **kw)  # noqa: E731
    shapes = {
        "circle_bar": [P(kind="circle", x=s * .14, y=s * .14, w=s * .72, h=s * .72, r=s * .36, fill="accent"),
                       P(kind="rect", x=s * .44, y=s * .08, w=s * .12, h=s * .84, fill="ink")],
        "stacked_bars": [P(kind="rect", x=s * .16, y=s * (.18 + .22 * i), w=s * (.68 - .14 * i), h=s * .14, fill=f)
                         for i, f in enumerate(("ink", "accent", "accent_2"))],
        "split_circle": [P(kind="arc", x=s * .5, y=s * .5, r=s * .38, rotation=0, fill="accent"),
                         P(kind="arc", x=s * .5, y=s * .5, r=s * .38, rotation=180, fill="ink")],
        "triangle_notch": [P(kind="triangle", x=s * .14, y=s * .16, w=s * .72, h=s * .68, fill="accent"),
                           P(kind="circle", x=s * .41, y=s * .5, w=s * .18, h=s * .18, r=s * .09, fill=on)],
        "ring_dot": [P(kind="ring", x=s * .5, y=s * .5, r=s * .34, fill="none", stroke="ink", stroke_width=s * .09),
                     P(kind="circle", x=s * .6, y=s * .22, w=s * .18, h=s * .18, r=s * .09, fill="accent")],
        "quarter_arcs": [P(kind="arc", x=s * (.3 + .4 * (i % 2)), y=s * (.3 + .4 * (i // 2)), r=s * .2, rotation=90 * i,
                           fill=("accent", "ink", "ink", "accent_2")[i]) for i in range(4)],
    }[m]
    return CompositionIR(kind="mark", width=s, height=s, background=on, primitives=tuple(shapes), genome_hash=genome.content_hash,
                         grammar_weights=dict(genome.grammar_weights), seed=0, title=f"{genome.brand_name} mark")


def lockup(genome: CreativeGenome, *, width: int = 1200, height: int = 360, on: str = "paper") -> CompositionIR:
    m = mark(genome, size=height - 80, on=on)
    shifted = tuple(p.model_copy(update={"x": p.x + 40, "y": p.y + 40}) for p in m.primitives)
    text_fill = "paper" if on == "ink" else "ink"
    word = TextBlock(role="wordmark", text=genome.brand_name, x=height + 20, y=height * 0.62, size=height * 0.32,
                     weight=int(genome.typography_rules.get("display_weight", 700)), fill=text_fill,
                     tracking=genome.typography_rules.get("tracking", 0))
    return CompositionIR(kind="lockup", width=width, height=height, background=on, primitives=shifted, text=(word,),
                         genome_hash=genome.content_hash, grammar_weights=dict(genome.grammar_weights), seed=0,
                         title=f"{genome.brand_name} lockup")


ICON_PATHS = {  # 24-unit pictograms; geometry is original and drawn with the genome's stroke and corner rules
    "home": "M4 11 L12 4 L20 11 M6 10 V20 H18 V10",
    "search": "M10.5 4 A6.5 6.5 0 1 1 10.49 4 Z M15.5 15.5 L20 20",
    "bag": "M5 8 H19 L18 20 H6 Z M9 8 V6 A3 3 0 0 1 15 6 V8",
    "user": "M12 4 A4 4 0 1 1 11.99 4 Z M4.5 20 C5.5 15.5 18.5 15.5 19.5 20",
    "arrow": "M5 12 H19 M13 6 L19 12 L13 18",
    "check": "M5 12.5 L10 17 L19 7",
}


def icon_svg(genome: CreativeGenome, name: str, *, size: int = 48, role: str = "ink") -> str:
    p = genome.palette.roles()
    sw = max(1.5, float(genome.geometry_rules["stroke"]) * 24 / 48 * 1.6)
    join = "round" if float(genome.geometry_rules["corner_radius"]) > 8 else "miter"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" role="img" '
            f'aria-label="{escape(name)} icon"><title>{escape(name)}</title><path d="{ICON_PATHS[name]}" fill="none" '
            f'stroke="{p[role]}" stroke-width="{sw:.2f}" stroke-linecap="round" stroke-linejoin="{join}"/></svg>\n')


def _shape(p: Primitive, pal: dict[str, str]) -> str:
    fill = "none" if p.fill == "none" else pal[p.fill]
    stroke = f' stroke="{pal[p.stroke]}" stroke-width="{p.stroke_width:.2f}"' if p.stroke else ""
    op = f' opacity="{p.opacity:.2f}"' if p.opacity < 1 else ""
    cx, cy = p.x + p.w / 2, p.y + p.h / 2
    rot = f' transform="rotate({p.rotation:.2f} {cx:.2f} {cy:.2f})"' if p.rotation and p.kind not in {"arc", "fan"} else ""
    if p.kind in {"rect", "bar", "card", "pixel_block"}:
        return f'<rect x="{p.x:.2f}" y="{p.y:.2f}" width="{p.w:.2f}" height="{p.h:.2f}" rx="{p.corner:.2f}" fill="{fill}"{stroke}{op}{rot}/>'
    if p.kind == "circle":
        return f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{p.r:.2f}" fill="{fill}"{stroke}{op}/>'
    if p.kind == "ring":
        return f'<circle cx="{p.x:.2f}" cy="{p.y:.2f}" r="{p.r:.2f}" fill="none"{stroke}{op}/>'
    if p.kind == "triangle":
        pts = f"{p.x:.2f},{p.y + p.h:.2f} {cx:.2f},{p.y:.2f} {p.x + p.w:.2f},{p.y + p.h:.2f}"
        return f'<polygon points="{pts}" fill="{fill}"{stroke}{op}{rot}/>'
    if p.kind == "line":
        return f'<line x1="{p.x:.2f}" y1="{p.y:.2f}" x2="{p.x + p.w:.2f}" y2="{p.y + p.h:.2f}" stroke="{pal[p.stroke or p.fill]}" stroke-width="{max(1, p.stroke_width):.2f}"{op}/>'
    if p.kind == "arc":  # half disc rotated around its centre
        a = math.radians(p.rotation)
        x1, y1 = p.x + p.r * math.cos(a), p.y + p.r * math.sin(a)
        x2, y2 = p.x - p.r * math.cos(a), p.y - p.r * math.sin(a)
        return f'<path d="M{x1:.2f} {y1:.2f} A{p.r:.2f} {p.r:.2f} 0 0 1 {x2:.2f} {y2:.2f} Z" fill="{fill}"{op}/>'
    if p.kind == "fan":
        rays = []
        for k in range(9):
            a = math.pi + math.pi * k / 8
            rays.append(f'<line x1="{p.x:.2f}" y1="{p.y:.2f}" x2="{p.x + p.r * math.cos(a):.2f}" y2="{p.y + p.r * math.sin(a):.2f}" stroke="{fill}" stroke-width="{p.stroke_width:.2f}"/>')
        arcs = "".join(f'<path d="M{p.x - p.r * f:.2f} {p.y:.2f} A{p.r * f:.2f} {p.r * f:.2f} 0 0 1 {p.x + p.r * f:.2f} {p.y:.2f}" fill="none" stroke="{fill}" stroke-width="{p.stroke_width:.2f}"/>' for f in (0.45, 0.7, 1.0))
        return f'<g{op}>{"".join(rays)}{arcs}</g>'
    if p.kind == "dots":
        dots = []
        for i in range(int(p.w // 22)):
            for j in range(int(p.h // 22)):
                dots.append(f'<circle cx="{p.x + i * 22 + 11:.2f}" cy="{p.y + j * 22 + 11:.2f}" r="{p.r:.2f}"/>')
        return f'<g fill="{fill}"{op}>{"".join(dots)}</g>'
    raise ValueError(f"unknown primitive {p.kind}")


def _family(genome: CreativeGenome, family: str) -> str:
    stacks = (genome.typography_rules.get("stacks") or FONT_STACKS)[family]
    return ", ".join(f"'{f}'" if " " in f else f for f in stacks)


def to_svg(ir: CompositionIR, genome: CreativeGenome, *, palette: Optional[dict[str, str]] = None) -> str:
    pal = palette or genome.palette.roles()
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{ir.width}" height="{ir.height}" '
             f'viewBox="0 0 {ir.width} {ir.height}" role="img" aria-label="{escape(ir.title)}">',
             f"<title>{escape(ir.title)}</title>",
             f'<desc>Generated by amc-foundry from genome {ir.genome_hash[:16]}, seed {ir.seed}.</desc>',
             f'<rect width="{ir.width}" height="{ir.height}" fill="{pal[ir.background]}"/>']
    parts += [_shape(p, pal) for p in ir.primitives]
    for t in ir.text:
        rot = f' transform="rotate({t.rotation:.2f} {t.x:.2f} {t.y:.2f})"' if t.rotation else ""
        track = f' letter-spacing="{t.tracking * t.size:.2f}"' if t.tracking else ""
        parts.append(f'<text x="{t.x:.2f}" y="{t.y:.2f}" font-family="{escape(_family(genome, t.family), {chr(39): "&apos;"})}" '
                     f'font-size="{t.size:.2f}" font-weight="{t.weight}" fill="{pal[t.fill]}" text-anchor="{t.anchor}"{track}{rot}>'
                     f"{escape(t.text)}</text>")
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def roles_used(ir: CompositionIR) -> set[str]:
    used = {ir.background} | {p.fill for p in ir.primitives if p.fill != "none"} | {p.stroke for p in ir.primitives if p.stroke}
    return used | {t.fill for t in ir.text}


def shape_signature(ir: CompositionIR) -> dict[str, int]:
    sig: dict[str, int] = {}
    for p in ir.primitives:
        sig[f"{p.kind}:{p.fill}"] = sig.get(f"{p.kind}:{p.fill}", 0) + 1
    return sig


def iter_text(ir: CompositionIR) -> Iterable[str]:
    return (t.text for t in ir.text)


__all__ = ["DARK_GROUND", "ICON_PATHS", "icon_svg", "iter_text", "lockup", "mark", "poster", "roles_used", "shape_signature",
           "to_svg"]
