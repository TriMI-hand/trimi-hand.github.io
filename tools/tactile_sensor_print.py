#!/usr/bin/env python3
"""Redraw the middle tactile sensor's print to the real cut and put it in the viewer GLB.

The viewer shows the sensor's printed circuit (the GLB's only texture) wrapped on the
fingertip and, while the tip is apart, unrolled flat from its UVs. The texture from the
.blend has an earlier outline and contact layout; this script draws the outline and the
56 contacts of Thumb_Cut_Sensing_Surface_56_Contacts.step instead, keeping the print's
stripes (same colours, pitch and phase) and its 1 mm copper border.

The texture keeps the .blend's scale and placement (40 px per mm, the bridge where it
was), so it still lines up with the sensor mesh's UVs. Only the image bytes and the
sampler change in the GLB: the meshes stay byte for byte as exported. The sampler is
set to clamp, since the mesh's UVs run past the texture's edges and the default repeat
tiled stray pieces of the print onto them.

Re-run after tools/export_hardware_glb.py (needs numpy and Pillow):
    python3 tools/tactile_sensor_print.py public/data/cad/trimi_hardware.glb
"""

import io
import json
import struct
import sys

import numpy as np
from PIL import Image, ImageDraw

# ---- the cut, from the STEP (mm; the rectangle's far edge at y = 0, the tip toward -y) ----
OUTLINE = [  # rectangle (25 x 12), bridge (5 x 2), trapezoid (25 -> 12 wide, 21 long)
    (6.5, -35), (18.5, -35), (25, -14), (15, -14), (15, -12), (25, -12),
    (25, 0), (0, 0), (0, -12), (10, -12), (10, -14), (0, -14),
]
CONTACT = 0.6  # square contact pads
CONTACTS = (
    [(2 + 3 * i, y) for y in (-2.95, -6.375, -9.8) for i in range(8)]
    + [(12.5 + 2.3 * (i - (n - 1) / 2), y)
       for y, n in ((-16.2, 8), (-20.575, 8), (-24.95, 6), (-29.325, 6), (-33.7, 4))
       for i in range(n)]
)
BORDER = 1.0  # copper margin inside the cut

# ---- the print, as in the .blend's texture ------------------------------------------
SIZE = (1025, 1625)
PX_PER_MM = 40
ORIGIN = (12, 1492)  # pixel of (0, 0), +y down the rows: the bridge stays at rows 932-1012, cols 412-612
STRIPE_PITCH, STRIPE_DARK, STRIPE_PHASE = 46, 29, 78  # dark rows: (row - phase) % pitch < dark
COPPER, TRACE, PAD = (204, 115, 26), (14, 11, 10), (77, 36, 13)
SUPERSAMPLE = 4


def inset(poly, d):
    """Offset a simple polygon inward by d, mitring the corners."""
    p = np.array(poly, float)
    area = np.sum(p[:, 0] * np.roll(p[:, 1], -1) - np.roll(p[:, 0], -1) * p[:, 1]) / 2
    n = len(p)
    lines = []
    for i in range(n):
        a, b = p[i], p[(i + 1) % n]
        t = (b - a) / np.linalg.norm(b - a)
        inward = np.array([-t[1], t[0]]) * (1 if area > 0 else -1)
        lines.append((a + inward * d, t))
    out = []
    for i in range(n):
        (p1, t1), (p2, t2) = lines[i - 1], lines[i]
        s = np.linalg.solve(np.array([t1, -t2]).T, p2 - p1)[0]
        out.append(tuple(p1 + t1 * s))
    return out


def draw_print():
    k = SUPERSAMPLE
    w, h = SIZE[0] * k, SIZE[1] * k

    def px(pt):
        return ((ORIGIN[0] + pt[0] * PX_PER_MM) * k, (ORIGIN[1] + pt[1] * PX_PER_MM) * k)

    def mask(polys):
        m = Image.new("L", (w, h), 0)
        g = ImageDraw.Draw(m)
        for poly in polys:
            g.polygon([px(q) for q in poly], fill=255)
        return np.array(m) > 127

    cut = mask([OUTLINE])
    inner = mask([inset(OUTLINE, BORDER)])
    r = CONTACT / 2
    pads = mask([[(x - r, y - r), (x + r, y - r), (x + r, y + r), (x - r, y + r)] for x, y in CONTACTS])
    rows = (np.arange(h) // k - STRIPE_PHASE) % STRIPE_PITCH < STRIPE_DARK
    trace = inner & rows[:, None]

    rgba = np.zeros((h, w, 4), np.uint8)
    rgba[..., :3] = COPPER  # transparent texels too, so mipmaps do not fringe dark
    rgba[trace, :3] = TRACE
    rgba[pads & cut, :3] = PAD
    rgba[..., 3] = cut * 255
    big = Image.fromarray(rgba).convert("RGBa")
    return big.resize(SIZE, Image.BOX).convert("RGBA")


def patch_glb(path, png):
    data = open(path, "rb").read()
    jlen = struct.unpack_from("<I", data, 12)[0]
    doc = json.loads(data[20:20 + jlen])
    binary = data[20 + jlen + 8:]
    if len(doc.get("images", [])) != 1:
        sys.exit("expected exactly one image (the tactile sensor print)")
    image_view = doc["images"][0]["bufferView"]

    # Rebuild the binary chunk view by view, swapping in the new image.
    views = sorted(range(len(doc["bufferViews"])), key=lambda i: doc["bufferViews"][i].get("byteOffset", 0))
    out = bytearray()
    for i in views:
        v = doc["bufferViews"][i]
        start = v.get("byteOffset", 0)
        chunk = png if i == image_view else binary[start:start + v["byteLength"]]
        out += b"\0" * (-len(out) % 4)
        v["byteOffset"] = len(out)
        v["byteLength"] = len(chunk)
        out += chunk
    out += b"\0" * (-len(out) % 4)
    doc["buffers"][0]["byteLength"] = len(out)

    sampler = doc["textures"][0].get("sampler")
    if sampler is None:
        doc.setdefault("samplers", []).append({})
        sampler = doc["textures"][0]["sampler"] = len(doc["samplers"]) - 1
    doc["samplers"][sampler].update(wrapS=33071, wrapT=33071)  # CLAMP_TO_EDGE

    js = json.dumps(doc, separators=(",", ":")).encode()
    js += b" " * (-len(js) % 4)
    glb = struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(out))
    glb += struct.pack("<II", len(js), 0x4E4F534A) + js
    glb += struct.pack("<II", len(out), 0x004E4942) + bytes(out)
    open(path, "wb").write(glb)


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: python3 tools/tactile_sensor_print.py public/data/cad/trimi_hardware.glb")
    buf = io.BytesIO()
    draw_print().save(buf, "PNG", optimize=True)
    patch_glb(sys.argv[1], buf.getvalue())
    print(f"wrote the {len(CONTACTS)}-contact print ({len(buf.getvalue()) // 1024} KB) into {sys.argv[1]}")


if __name__ == "__main__":
    main()
