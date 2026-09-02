from __future__ import annotations

from textwrap import dedent


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;")
    )


def render_logo_svg(*, brand_name: str, primary: str, secondary: str, surface: str, tagline: str | None = None) -> str:
    initials = "".join(part[:1].upper() for part in brand_name.split()[:2]) or "B"
    safe_name = _escape(brand_name)
    safe_tagline = _escape(tagline or "geometric mark · canonical render")
    return dedent(
        f"""\
        <svg xmlns="http://www.w3.org/2000/svg" width="1200" height="1200" viewBox="0 0 1200 1200" role="img" aria-label="{safe_name} logo mark">
          <rect width="1200" height="1200" rx="240" fill="{surface}"/>
          <circle cx="600" cy="600" r="360" fill="{secondary}" opacity="0.15"/>
          <path d="M300 840 L600 240 L900 840 Z" fill="{primary}"/>
          <circle cx="600" cy="610" r="110" fill="{surface}"/>
          <text x="600" y="645" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="140" font-weight="700" fill="{primary}">{_escape(initials)}</text>
          <text x="600" y="1030" text-anchor="middle" font-family="Inter, Arial, sans-serif" font-size="44" letter-spacing="6" fill="{primary}">{safe_tagline}</text>
        </svg>
        """
    )


def render_background_pattern_svg(*, brand_name: str, primary: str, secondary: str, surface: str) -> str:
    safe_name = _escape(brand_name)
    return dedent(
        f"""\
        <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-label="{safe_name} background pattern">
          <rect width="1600" height="900" fill="{surface}"/>
          <g fill="none" stroke="{primary}" stroke-width="6" opacity="0.18">
            <path d="M0 180 C200 60 400 60 600 180 S1000 300 1200 180 S1400 60 1600 180"/>
            <path d="M0 450 C200 330 400 330 600 450 S1000 570 1200 450 S1400 330 1600 450"/>
            <path d="M0 720 C200 600 400 600 600 720 S1000 840 1200 720 S1400 600 1600 720"/>
          </g>
          <g fill="{secondary}" opacity="0.12">
            <circle cx="220" cy="180" r="56"/>
            <circle cx="780" cy="450" r="72"/>
            <circle cx="1320" cy="720" r="64"/>
            <circle cx="1180" cy="180" r="40"/>
            <circle cx="420" cy="720" r="48"/>
          </g>
        </svg>
        """
    )


def render_hero_svg(
    *,
    brand_name: str,
    headline: str,
    audience: str,
    primary: str,
    secondary: str,
    surface: str,
    accent: str,
) -> str:
    safe_name = _escape(brand_name)
    safe_headline = _escape(headline)
    safe_audience = _escape(audience)
    return dedent(
        f"""\
        <svg xmlns="http://www.w3.org/2000/svg" width="1600" height="900" viewBox="0 0 1600 900" role="img" aria-label="{safe_name} hero illustration">
          <defs>
            <linearGradient id="hero-bg" x1="0" y1="0" x2="1" y2="1">
              <stop offset="0%" stop-color="{surface}"/>
              <stop offset="100%" stop-color="{accent}"/>
            </linearGradient>
          </defs>
          <rect width="1600" height="900" fill="url(#hero-bg)"/>
          <rect x="108" y="108" width="640" height="684" rx="42" fill="{primary}" opacity="0.08"/>
          <rect x="820" y="108" width="672" height="320" rx="42" fill="{secondary}" opacity="0.18"/>
          <rect x="820" y="468" width="320" height="324" rx="42" fill="{primary}" opacity="0.16"/>
          <rect x="1172" y="468" width="320" height="324" rx="42" fill="{secondary}" opacity="0.10"/>
          <text x="144" y="268" font-family="Inter, Arial, sans-serif" font-size="88" font-weight="700" fill="{primary}">{safe_headline}</text>
          <text x="144" y="350" font-family="Inter, Arial, sans-serif" font-size="32" fill="{primary}" opacity="0.82">Built for {safe_audience}</text>
          <text x="144" y="760" font-family="Inter, Arial, sans-serif" font-size="28" fill="{primary}" opacity="0.62">{safe_name} · canonical brand render</text>
        </svg>
        """
    )
