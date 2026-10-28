"""Bounded stdlib PNG codec, so AVIC can measure pixels without Pillow or numpy.

Decodes 8-bit, non-interlaced greyscale, greyscale+alpha, RGB and RGBA PNGs (the
formats Chromium writes) into flat RGBA rows. Anything else raises ``PngError``;
it is never guessed. Decompression is bounded so a hostile file cannot expand
past the pixel budget.
"""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Optional

SIGNATURE = b"\x89PNG\r\n\x1a\n"
MAX_PIXELS = 24_000_000
_CHANNELS = {0: 1, 2: 3, 4: 2, 6: 4}


class PngError(ValueError):
    pass


@dataclass(frozen=True)
class Raster:
    width: int
    height: int
    rgba: bytes  # width * height * 4

    def pixel(self, x: int, y: int) -> tuple[int, int, int, int]:
        i = (y * self.width + x) * 4
        return tuple(self.rgba[i:i + 4])  # type: ignore[return-value]


def dimensions(data: bytes) -> tuple[int, int]:
    if data[:8] != SIGNATURE or data[12:16] != b"IHDR":
        raise PngError("not a PNG")
    return struct.unpack(">II", data[16:24])


def decode(data: bytes, *, max_pixels: int = MAX_PIXELS) -> Raster:
    if data[:8] != SIGNATURE:
        raise PngError("not a PNG")
    pos, idat, ihdr = 8, [], None
    while pos + 8 <= len(data):
        length, ctype = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + length]
        if len(body) != length:
            raise PngError("truncated chunk")
        if ctype == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif ctype == b"IDAT":
            idat.append(body)
        elif ctype == b"IEND":
            break
        pos += 12 + length
    if ihdr is None:
        raise PngError("missing IHDR")
    width, height, depth, ctype, _, _, interlace = ihdr
    if depth != 8 or ctype not in _CHANNELS or interlace != 0:
        raise PngError(f"unsupported PNG (depth={depth}, colour type={ctype}, interlace={interlace})")
    if width == 0 or height == 0 or width * height > max_pixels:
        raise PngError("PNG exceeds the pixel budget")
    ch = _CHANNELS[ctype]
    stride = width * ch
    expected = height * (stride + 1)
    d = zlib.decompressobj()
    raw = d.decompress(b"".join(idat), expected + 1)
    if len(raw) != expected or d.unconsumed_tail:
        raise PngError("image data size does not match the header")
    out = bytearray(height * width * 4)
    prev = bytearray(stride)
    for y in range(height):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(ch, stride):
                line[i] = (line[i] + line[i - ch]) & 255
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 255
        elif f == 3:
            for i in range(stride):
                left = line[i - ch] if i >= ch else 0
                line[i] = (line[i] + ((left + prev[i]) >> 1)) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - ch] if i >= ch else 0
                b = prev[i]
                c = prev[i - ch] if i >= ch else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        elif f != 0:
            raise PngError(f"bad filter {f}")
        o = y * width * 4
        for x in range(width):
            px = line[x * ch:(x + 1) * ch]
            if ch == 1:
                r = g = b = px[0]; a = 255
            elif ch == 2:
                r = g = b = px[0]; a = px[1]
            elif ch == 3:
                r, g, b = px; a = 255
            else:
                r, g, b, a = px
            out[o + x * 4:o + x * 4 + 4] = bytes((r, g, b, a))
        prev = line
    return Raster(width, height, bytes(out))


def encode(raster: Raster) -> bytes:
    def chunk(t: bytes, body: bytes) -> bytes:
        return struct.pack(">I", len(body)) + t + body + struct.pack(">I", zlib.crc32(t + body) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + raster.rgba[y * raster.width * 4:(y + 1) * raster.width * 4] for y in range(raster.height))
    ihdr = struct.pack(">IIBBBBB", raster.width, raster.height, 8, 6, 0, 0, 0)
    return SIGNATURE + chunk(b"IHDR", ihdr) + chunk(b"IDAT", zlib.compress(rows, 9)) + chunk(b"IEND", b"")


def max_channel_difference(a: bytes, b: bytes) -> Optional[int]:
    """Largest per-channel difference between two PNGs of the same size, or None if they cannot be compared."""
    try:
        ra, rb = decode(a), decode(b)
    except PngError:
        return None
    if (ra.width, ra.height) != (rb.width, rb.height):
        return None
    if ra.rgba == rb.rgba:
        return 0
    return max(abs(x - y) for x, y in zip(ra.rgba, rb.rgba))


def downsample(r: Raster, size: int) -> Raster:
    """Box-filter to at most ``size`` on the long side (deterministic, alpha-weighted onto white)."""
    scale = max(r.width, r.height) / size
    if scale <= 1:
        return r
    w, h = max(1, round(r.width / scale)), max(1, round(r.height / scale))
    out = bytearray(w * h * 4)
    for y in range(h):
        y0, y1 = int(y * r.height / h), max(int(y * r.height / h) + 1, int((y + 1) * r.height / h))
        for x in range(w):
            x0, x1 = int(x * r.width / w), max(int(x * r.width / w) + 1, int((x + 1) * r.width / w))
            acc = [0, 0, 0]
            n = 0
            for yy in range(y0, y1):
                base = yy * r.width * 4
                for xx in range(x0, x1):
                    i = base + xx * 4
                    a = r.rgba[i + 3]
                    for k in range(3):
                        acc[k] += (r.rgba[i + k] * a + 255 * (255 - a)) // 255
                    n += 1
            o = (y * w + x) * 4
            out[o:o + 4] = bytes((acc[0] // n, acc[1] // n, acc[2] // n, 255))
    return Raster(w, h, bytes(out))


__all__ = ["MAX_PIXELS", "PngError", "Raster", "decode", "dimensions", "downsample", "encode", "max_channel_difference"]
