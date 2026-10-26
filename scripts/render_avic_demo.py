"""Render the AVIC demo package into runtime/avic/demo/ (fictional brand, synthetic reference).

The reference is generated here (sky gradient, sun disc, ground band), so there is no
third-party image and no rights question. Run from the repository root:

    python scripts/render_avic_demo.py
"""

from __future__ import annotations

import json
import math
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.langgraph.agency.avic import png  # noqa: E402
from services.langgraph.agency.avic.run import run_local  # noqa: E402

OUT = ROOT / "runtime" / "avic" / "demo"


def synthetic_reference(w: int = 320, h: int = 240) -> bytes:
    buf = bytearray()
    for y in range(h):
        for x in range(w):
            t = y / h
            r, g, b = int(40 + 150 * t), int(70 + 110 * t), int(160 - 40 * t)
            d = math.hypot(x - 225, y - 80)
            if d < 36:
                r, g, b = 255, int(200 - d * 2), 90
            elif d < 52:
                k = (d - 36) / 16
                r, g, b = int(255 * (1 - k) + r * k), int(180 * (1 - k) + g * k), int(90 * (1 - k) + b * k)
            if y > 160:
                r, g, b = int(60 + 20 * math.sin(x / 9)), int(90 + 30 * (y - 160) / 80), 50
            buf += bytes((r, g, b, 255))
    return png.encode(png.Raster(w, h, bytes(buf)))


def main() -> int:
    shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True)
    ref = OUT / "reference-synthetic.png"
    ref.write_bytes(synthetic_reference())
    request = json.loads((ROOT / "sample_avic_request.json").read_text())
    code, summary = run_local(request, OUT, reference=ref, variants=3)
    for preview in (OUT / "variants").glob("*.png"):  # keep the repository small: variant SVGs are the source
        preview.unlink()
    print(json.dumps(summary, indent=2, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
