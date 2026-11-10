"""Place the TPU hand (Onshape FULLHAND_V5) in TRIMI and save it as a GLB in the
.blend's world frame, for tools/export_hardware_glb.py --tpu.

The hand keeps its STEP shape (no joint is bent). It is turned palm down and
moved as one rigid body, about where the hologram hand sits:
- its back lies on the palm holder's upper face (between the holder's two faces);
- the latch knobs on the back of its fingertips come as close as they can to the
  keyhole slots in TRIMI's finger cots. Index and middle have two knobs each;
  ring and pinky one each, sharing the ring/pinky cot; the thumb one.

TRIMI's fingers stay straight and only turn at MCP ab/ad. Its thumb IP is
held at a 10 degree bend (THUMB_IP), and B1, B2 and MCP are searched for the pose
whose cot slot meets the thumb's knob. That pose goes in <out>.fit.json for the
export's TPU hand stage.

Usage (from trimi-website/; tpu_hand.glb from tools/step_to_glb.py):
  blender -b path/to/TriMI_lookdev_v37.blend --python tools/fit_tpu_hand.py -- \
    --tpu tpu_hand.glb --out tpu_fitted.glb
"""

import argparse
import json
import math
import os
import sys

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from numpy.lib.stride_tricks import sliding_window_view

REST_FRAME = 100
SKIN = "1mcp"  # the whole-hand TPU body (it shares its name with the thumb's MCP insert)
# finger: (proximal insert, middle insert, cot)
FINGERS = {
    "index": ("2mcp", "2pip", "Part 1.021"),
    "middle": ("3mcp", "3pip", "Part 1"),
    "ring": ("4mcp", "4pip", "Fingercot_Ring"),
    "pinky": ("Part 12", "5pip", "Fingercot_Ring"),
}
THUMB = ("1cmc", "1mcp", "Part 9")
THUMB_COT = "thumb_fingercot"
SKIN_TRIS, INSERT_TRIS = 60000, 8000
# TRIMI's palm holder: an upper face over the back of the hand and, on the pinky side, a half
# lower face under the palm. The hand goes between them, its back against the upper face.
HOLDER = "palm_holder_v2.001"
# TRIMI's back-of-hand cover, which the soft TPU may be pressed into: the holder's upper face and
# the part behind it over the wrist
COVER = (HOLDER, "palm_holder_v4")
STRAIGHT_FINGERS = True  # TRIMI's MCP and PIP stay straight; only MCP ab/ad turns to meet the TPU hand
THUMB_IP = math.radians(-10)  # TRIMI's thumb IP, bent 10 degrees (0 is straight); B1, B2 and MCP are fitted


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--tpu", required=True)
    p.add_argument("--out", required=True)
    return p.parse_args(argv)


def log(*a):
    print("[fit-tpu]", *a, flush=True)


def world_verts(o):
    m = o.matrix_world
    return np.array([tuple(m @ v.co) for v in o.data.vertices])


def kabsch(src, dst, w=None):
    w = np.ones(len(src)) if w is None else np.asarray(w, float)
    w = w / w.sum()
    cs, cd = w @ src, w @ dst
    H = ((src - cs) * w[:, None]).T @ (dst - cd)
    U, _, Vt = np.linalg.svd(H)
    D = np.diag([1, 1, np.sign(np.linalg.det(Vt.T @ U.T))])
    R = Vt.T @ D @ U.T
    return R, cd - R @ cs


def rot_between(a, b):
    """Smallest rotation taking direction a to direction b."""
    return np.array(Vector(a).rotation_difference(Vector(b)).to_matrix())


def components(mask):
    seen = np.zeros_like(mask)
    out = []
    for i, j in zip(*np.nonzero(mask)):
        if seen[i, j]:
            continue
        st, cm = [(i, j)], []
        seen[i, j] = True
        while st:
            x, y = st.pop()
            cm.append((x, y))
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                nx, ny = x + dx, y + dy
                if 0 <= nx < mask.shape[0] and 0 <= ny < mask.shape[1] and mask[nx, ny] and not seen[nx, ny]:
                    seen[nx, ny] = True
                    st.append((nx, ny))
        out.append(np.array(cm))
    return out


def back_knobs(skin, step=0.0004):
    """Latch knobs: bumps standing >1.5 mm proud of the back of the hand, raycast from the back
    (+z after the flip). Each knob shows as two nearby patches (its mushroom head), merged here."""
    V = world_verts(skin)
    bvh = BVHTree.FromPolygons([Vector(v) for v in V], [list(q.vertices) for q in skin.data.polygons])
    lo, hi = V.min(0), V.max(0)
    us, vs = np.arange(lo[0], hi[0], step), np.arange(lo[1], hi[1], step)
    H = np.full((len(us), len(vs)), np.nan)
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            hit = bvh.ray_cast(Vector((u, v, hi[2] + 0.02)), Vector((0, 0, -1)), 1.0)
            if hit[0] is not None:
                H[i, j] = hit[0][2]
    valid = ~np.isnan(H)
    med = np.nanmedian(sliding_window_view(np.pad(np.where(valid, H, np.nan), 7, constant_values=np.nan), (15, 15)), axis=(2, 3))
    pts = []
    for cm in components(valid & (H - med > 0.0015)):
        if 6 <= len(cm) <= 300:
            pts.append(np.array([us[cm[:, 0]].mean(), vs[cm[:, 1]].mean(), np.nanmax(H[cm[:, 0], cm[:, 1]])]))
    merged, used = [], set()
    for i, a in enumerate(pts):
        if i in used:
            continue
        group = [k for k, b in enumerate(pts) if k not in used and np.linalg.norm((b - a)[:2]) < 0.0065]
        used |= set(group)
        merged.append(np.mean([pts[k] for k in group], axis=0))
    return merged


def back_grid(skin, y_from, step=0.002):
    """The back of the hand (+z after the flip) behind y_from, sampled on a regular grid."""
    V = world_verts(skin)
    bvh = BVHTree.FromPolygons([Vector(v) for v in V], [list(q.vertices) for q in skin.data.polygons])
    lo, hi = V.min(0), V.max(0)
    pts = []
    for x in np.arange(lo[0], hi[0], step):
        for y in np.arange(y_from, hi[1], step):
            hit = bvh.ray_cast(Vector((x, y, hi[2] + 0.02)), Vector((0, 0, -1)), 1.0)
            if hit[0] is not None and hit[1].z > 0.3:
                pts.append(tuple(hit[0]))
    return np.array(pts)


def keyholes(o, step=0.0003, reach=16):
    """Keyhole slots in a cot's back: through-holes seen along -local y, the largest two (world)."""
    me = o.data
    V = np.array([tuple(v.co) for v in me.vertices])
    bvh = BVHTree.FromPolygons([v.co for v in me.vertices], [list(q.vertices) for q in me.polygons])
    lo, hi = V.min(0), V.max(0)
    us, vs = np.arange(lo[0], hi[0], step), np.arange(lo[2], hi[2], step)
    H = np.full((len(us), len(vs)), np.nan)
    for i, u in enumerate(us):
        for j, v in enumerate(vs):
            hit = bvh.ray_cast(Vector((u, hi[1] + 0.01, v)), Vector((0, -1, 0)), 1.0)
            if hit[0] is not None:
                H[i, j] = hit[0][1]
    valid = ~np.isnan(H)
    ref = sliding_window_view(np.pad(np.where(valid, H, -1e9), 3, constant_values=-1e9), (7, 7)).max(axis=(2, 3))
    deep = valid & (ref - H > 0.002)
    solid = valid & ~deep
    enc = np.zeros(H.shape, int)
    for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        hitdir = np.zeros(H.shape, bool)
        for k in range(1, reach + 1):
            sh = np.roll(solid, (-di * k, -dj * k), axis=(0, 1))
            if di > 0: sh[-k:, :] = False
            if di < 0: sh[:k, :] = False
            if dj > 0: sh[:, -k:] = False
            if dj < 0: sh[:, :k] = False
            hitdir |= sh
        enc += hitdir
    comps = sorted([cm for cm in components((deep | ~valid) & (enc >= 3)) if 60 <= len(cm) <= 600], key=len, reverse=True)[:2]
    out = []
    for cm in comps:
        i0, i1 = max(0, cm[:, 0].min() - 4), cm[:, 0].max() + 5
        j0, j1 = max(0, cm[:, 1].min() - 4), cm[:, 1].max() + 5
        rim = np.nanmedian(np.where(solid, H, np.nan)[i0:i1, j0:j1])
        out.append(np.array(o.matrix_world @ Vector((us[cm[:, 0]].mean(), rim, vs[cm[:, 1]].mean()))))
    return out


def holder_split(V, F, step=0.003):
    """Height between the palm holder's two faces. Vertical rays on a grid cross both faces where
    they overlap; the split lies between the lower face's highest underside and the upper face's
    lowest underside along those rays."""
    bvh = BVHTree.FromPolygons(V, F)
    A = np.array([tuple(v) for v in V])
    lo, hi = A.min(0), A.max(0)
    up = Vector((0, 0, 1))
    lower, upper = [], []
    for x in np.arange(lo[0], hi[0], step):
        for y in np.arange(lo[1], hi[1], step):
            o, downs = Vector((x, y, lo[2] - 0.01)), []
            for _ in range(16):
                hit = bvh.ray_cast(o, up, 1.0)
                if hit[0] is None:
                    break
                if hit[1] @ up < -0.2:
                    downs.append(hit[0].z)
                o = hit[0] + up * 1e-5
            # an underside more than 15 mm below the topmost one belongs to the lower face
            if len(downs) > 1 and downs[-1] - downs[0] > 0.015:
                lower += [z for z in downs if z < downs[-1] - 0.015]
                upper.append(downs[-1])
    return (max(lower) + min(upper)) / 2, max(lower), min(upper)


def main():
    args = parse_args()
    scene = bpy.data.scenes["TriMI_Studio"]
    scene.frame_set(REST_FRAME)
    O = bpy.data.objects

    # ---- the TPU hand, palm down (180 degrees about the finger axis, y)
    before = set(O)
    bpy.ops.import_scene.gltf(filepath=args.tpu)
    parts = {}
    for o in [o for o in O if o not in before]:
        if o.type == "MESH":
            parts["skin" if o.name.startswith(SKIN + ".") else o.name.split(".")[0]] = o
    flip = Matrix.Rotation(math.pi, 4, "Y")
    for o in parts.values():
        o.matrix_world = flip @ o.matrix_world
    bpy.context.view_layer.update()
    skin = parts["skin"]
    knobs_all = back_knobs(skin)  # on the full-resolution skin: the knobs are small
    for key, o in parts.items():
        n = sum(len(p.vertices) - 2 for p in o.data.polygons)
        target = SKIN_TRIS if key == "skin" else INSERT_TRIS
        if n > target:
            mod = o.modifiers.new("dec", "DECIMATE")
            mod.ratio = target / n
            mod.use_collapse_triangulate = True
            dg = bpy.context.evaluated_depsgraph_get()
            o.data = bpy.data.meshes.new_from_object(o.evaluated_get(dg), depsgraph=dg)
            o.modifiers.remove(mod)
    bpy.context.view_layer.update()

    # ---- fingertips (for assigning knobs) from the inserts
    box = {k: (world_verts(o).min(0), world_verts(o).max(0)) for k, o in parts.items()}
    S = world_verts(skin)
    tips = {}
    for f, (_, ins_m, _) in FINGERS.items():
        lo_m, hi_m = box[ins_m]
        dip = np.array([(lo_m[0] + hi_m[0]) / 2, lo_m[1] - 0.002, (lo_m[2] + hi_m[2]) / 2])
        band = (np.abs(S[:, 0] - dip[0]) < 0.009) & (S[:, 1] < dip[1] + 0.004)
        tips[f] = (dip, S[band][np.argmin(S[band][:, 1])])
    c_lo, c_hi = box[THUMB[0]]
    d_lo, d_hi = box[THUMB[2]]
    cc, dc = (c_lo + c_hi) / 2, (d_lo + d_hi) / 2
    ax = (dc - cc) / np.linalg.norm(dc - cc)
    proj = (S - dc) @ ax
    near = np.linalg.norm((S - dc) - np.outer(proj, ax), axis=1) < 0.012
    tips["thumb"] = (dc, S[near & (proj > 0)][np.argmax(proj[near & (proj > 0)])])
    knobs = {f: [] for f in tips}
    for k in knobs_all:
        best, bd = None, 0.02
        for f, (a, b) in tips.items():
            ab = b - a
            u = np.clip((k - a) @ ab / (ab @ ab), -0.4, 0.6)
            d = np.linalg.norm(k - (a + u * ab))
            if d < bd:
                best, bd = f, d
        if best:
            knobs[best].append(k)
    cots = {f: FINGERS[f][2] for f in FINGERS}
    cots["thumb"] = THUMB_COT
    slots = {c: keyholes(O[c]) for c in set(cots.values())}
    for f in knobs:
        log(f"{f}: {len(knobs[f])} knob(s), cot {cots[f]} {len(slots[cots[f]])} slot(s)")

    # ---- TRIMI's back-of-hand parts: everything but the fingers, the thumb and the cover
    up = np.array([0.0, 0.0, 1.0])
    roots = {"new_index_assem_v2 <1>", "middle_assembly_v2 <1>", "ring_finger_assem_v2 <1>"}

    def moving_part(o):
        p = o
        while p:
            if p.name in roots or p.name.startswith("GLOVE_"):
                return True
            p = p.parent
        return any(c.type == "CHILD_OF" and c.target and c.target.name.startswith("GLOVE_") for c in o.constraints)

    prod = [o for o in bpy.data.collections["TriMI_Product"].all_objects if o.type == "MESH" and not o.hide_render]
    back = [o for o in prod if not moving_part(o) and not o.name.startswith(("thumb_fingercot", "TactileSensor", "cover_new"))]
    # The palm holder's lower face (under the palm) is left out: the hand's back passes it and
    # stops at the upper face. The lower face is kept apart to check the palm's clearance over it.
    bv, bp, owners = [], [], []
    dg = bpy.context.evaluated_depsgraph_get()
    for o in back:
        oe = o.evaluated_get(dg)
        me = oe.to_mesh()
        vw = [oe.matrix_world @ v.co for v in me.vertices]
        polys = [list(q.vertices) for q in me.polygons]
        if o.name == HOLDER:
            z_split, z_lo, z_hi = holder_split(vw, polys)
            cz = np.array([sum(vw[i].z for i in q) / len(q) for q in polys])
            holder_v = vw
            lower_f = [q for q, z in zip(polys, cz) if z < z_split]
            polys = [q for q, z in zip(polys, cz) if z >= z_split]
            log(f"palm holder: lower face undersides up to {z_lo * 1000:.1f} mm, upper face from {z_hi * 1000:.1f} mm; "
                f"{len(lower_f)} of {len(cz)} faces below {z_split * 1000:.1f} mm are the lower face")
        off = len(bv)
        bv += vw
        bp += [[off + i for i in q] for q in polys]
        owners += [o.name] * len(polys)
        oe.to_mesh_clear()
    bvh_back = BVHTree.FromPolygons(bv, bp)
    bvh_lower = BVHTree.FromPolygons(holder_v, lower_f)

    def plane(P):
        c = P.mean(0)
        _, E = np.linalg.eigh(np.cov((P - c).T))
        n = E[:, 0] / np.linalg.norm(E[:, 0])
        return c, (n if n @ up > 0 else -n)

    # The TPU hand's back (palm side of the knuckles, faces looking up) and its plane
    n3 = skin.matrix_world.to_3x3()
    normals = np.array([tuple(n3 @ v.normal) for v in skin.data.vertices])
    palm_sel = (S[:, 1] > -0.07) & (normals @ up > 0.5)
    tpu_c, tpu_n = plane(S[palm_sel])

    # ---- TRIMI's finger modules. MCP ab/ad turns a whole module and its GLOVE chain about its
    # ab/ad servo horn; MCP/PIP flexion moves the GLOVE empties (forward only, never bending back).
    def horn(name):
        V = world_verts(O[name])
        c = (V.min(0) + V.max(0)) / 2
        _, E = np.linalg.eigh(np.cov((V - V.mean(0)).T))
        a = E[:, 0] / np.linalg.norm(E[:, 0])
        return c, (a if a @ up > 0 else -a)

    ia = O["IDX_ABAD"]
    modules = {
        "index": ("Revolve1[1].001", ["new_index_assem_v2 <1>", "GLOVE_index_MCP"], ("GLOVE_index_MCP", "GLOVE_index_PIP"), "Part 1.021", ["index"]),
        "middle": ("Revolve1[1]", ["middle_assembly_v2 <1>", "GLOVE_middle_MCP"], ("GLOVE_middle_MCP", "GLOVE_middle_PIP"), "Part 1", ["middle"]),
        "ring": ("Revolve1[1].002", ["ring_finger_assem_v2 <1>", "GLOVE_ring_MCP"], ("GLOVE_ring_MCP", "GLOVE_ring_PIP"), "Fingercot_Ring", ["ring", "pinky"]),
    }

    def turn(axis, pivot, ang):
        A = np.array(Matrix.Rotation(ang, 4, Vector(axis)))
        A[:3, 3] = pivot - A[:3, :3] @ pivot
        return A

    mods = {}
    for m, (horn_name, nodes, gnames, cotname, fingers) in modules.items():
        pivot, axis = horn(horn_name)
        if m == "index":
            pivot = np.array(ia.matrix_world.translation)
        cot = O[cotname]
        inv = np.array(cot.matrix_world.inverted())
        gs = [O[n] for n in gnames]
        for g in gs:
            if g.animation_data:
                g.animation_data.action = None
        mods[m] = {"pivot": pivot, "axis": axis, "nodes": nodes, "gnames": gnames, "gs": gs, "cot": cot,
                   "rest": [g.rotation_euler[0] for g in gs], "fingers": fingers, "W0": np.array(cot.matrix_world),
                   "local": [inv[:3, :3] @ s + inv[:3, 3] for s in slots[cotname]]}

    def latch(R, t, thetas=np.linspace(-0.45, 0.45, 181)):
        """Each module's knob-to-slot distance and offset (knob minus slot) with TRIMI's fingers
        straight, at the module's best ab/ad (a turn about its servo horn)."""
        out = {}
        c, s = np.cos(thetas)[:, None, None], np.sin(thetas)[:, None, None]
        for m, md in mods.items():
            ks = np.array([R @ k + t for f in md["fingers"] for k in knobs[f]])
            W0, u, pv = md["W0"], md["axis"] / np.linalg.norm(md["axis"]), md["pivot"]
            d = np.array([W0[:3, :3] @ q + W0[:3, 3] for q in md["local"]]) - pv
            sw = pv + d[None] * c + np.cross(u, d)[None] * s + (np.outer(d @ u, u))[None] * (1 - c)  # (theta, slot, 3)
            if len(ks) == 2 and sw.shape[1] == 2:
                pairs = [sw, sw[:, ::-1]]
            else:
                pairs = [sw[:, [j]] for j in range(sw.shape[1])]
            best = None
            for pr in pairs:
                dist = np.linalg.norm(ks[None, :len(pr[0])] - pr, axis=2).mean(1)
                i = int(np.argmin(dist))
                if best is None or dist[i] < best[0]:
                    best = (float(dist[i]), float(thetas[i]), (ks[:len(pr[0])] - pr[i]).mean(0))
            out[m] = best
        return out

    # TRIMI's thumb workspace, sampled once over B1, B2 and MCP with the IP at THUMB_IP (where
    # its cot's slots are and which way the cot points), so the placement weighs the thumb's latch
    # with the fingers'
    th_cot = O[THUMB_COT]
    th_inv = np.array(th_cot.matrix_world.inverted())
    th_local = [th_inv[:3, :3] @ s + th_inv[:3, 3] for s in slots[THUMB_COT]]
    th_gloves = [O[n] for n in ("GLOVE_thumb_B1", "GLOVE_thumb_B2", "GLOVE_thumb_MCP", "GLOVE_thumb_IP")]
    for g in th_gloves:
        if g.animation_data:
            g.animation_data.action = None
    th_rest = [g.rotation_euler[0] for g in th_gloves]
    th_vals, th_slots, th_axis = [], [], []
    for b1 in th_rest[0] + np.linspace(-0.9, 0.9, 13):
        for b2 in th_rest[1] + np.linspace(-0.9, 0.9, 13):
            for mcp in th_rest[2] + np.linspace(-0.9, 0.9, 13):
                for g, v in zip(th_gloves, (b1, b2, mcp, THUMB_IP)):
                    g.rotation_euler[0] = v
                bpy.context.view_layer.update()
                mw = np.array(th_cot.matrix_world)
                th_vals.append((b1, b2, mcp, THUMB_IP))
                th_slots.append([mw[:3, :3] @ s + mw[:3, 3] for s in th_local])
                th_axis.append(-mw[:3, 2] / np.linalg.norm(mw[:3, 2]))
    for g, v in zip(th_gloves, th_rest):
        g.rotation_euler[0] = v
    bpy.context.view_layer.update()
    th_vals, th_slots, th_axis = np.array(th_vals), np.array(th_slots), np.array(th_axis)
    k_th0 = knobs["thumb"][0] if knobs["thumb"] else tips["thumb"][1]
    a_th0 = tips["thumb"][1] - tips["thumb"][0]

    def thumb_cost(vals, k, a):
        for g, v in zip(th_gloves, vals):
            g.rotation_euler[0] = v
        bpy.context.view_layer.update()
        mw = np.array(th_cot.matrix_world)
        d = min(np.linalg.norm(k - (mw[:3, :3] @ s + mw[:3, 3])) for s in th_local)
        axis = -mw[:3, 2] / np.linalg.norm(mw[:3, 2])
        ang = math.degrees(math.acos(np.clip(axis @ a, -1, 1)))
        return d + 0.0002 * ang, d, ang

    def thumb_search(R_, t_, starts=6):
        """TRIMI's thumb pose for the TPU thumb: B1, B2 and MCP (the IP held at THUMB_IP), so its
        cot slot meets the thumb's knob and its cot axis follows the TPU thumb's tip. Coordinate
        descent from the best few sampled poses; returns (joint values, (cost, distance, axis angle))."""
        k = R_ @ k_th0 + t_
        a = R_ @ a_th0
        a /= np.linalg.norm(a)
        d = np.linalg.norm(th_slots - k, axis=2).min(1)
        ang = np.degrees(np.arccos(np.clip(th_axis @ a, -1, 1)))
        best = None
        for i in np.argsort(d + 0.0002 * ang)[:starts]:
            vals = [float(v) for v in th_vals[i]]
            cur = thumb_cost(vals, k, a)
            for step in (0.08, 0.04, 0.02, 0.01):
                improved = True
                while improved:
                    improved = False
                    for j in range(3):  # B1, B2, MCP; the IP stays at THUMB_IP
                        for sgn in (1, -1):
                            trial = list(vals)
                            trial[j] += sgn * step
                            if abs(trial[j] - th_rest[j]) > 1.6:
                                continue
                            c = thumb_cost(trial, k, a)
                            if c[0] < cur[0] - 1e-7:
                                vals, cur, improved = trial, c, True
            if best is None or cur[0] < best[1][0]:
                best = (vals, cur)
        return best

    # ---- the TPU hand in TRIMI, about where the hologram hand sits: its back against TRIMI's
    # back-of-hand cover and its fingertips in the cots, TRIMI's fingers straight.
    # It starts level, its middle finger along TRIMI's and the middle fingertip latched. Then:
    # - it rolls about its middle finger and moves up or down, so all the fingertips come into
    #   their cots (TRIMI's cots fall away toward the pinky, like a hand's; the TPU hand is flat);
    # - it tilts about the fingertips, wrist up, until its back lies on the holder's upper face
    #   along the middle finger (as much of that strip pressed in as still clear of it). The cover
    #   curves down at its ends further than the TPU back does, so the soft TPU is squeezed
    #   there; no other part may be entered.
    R0 = rot_between(tpu_n, up)
    a_d = -np.array(O[cots["middle"]].matrix_world.to_3x3().col[2])
    a_d -= (a_d @ up) * up
    a_d /= np.linalg.norm(a_d)
    a_t = R0 @ (tips["middle"][1] - tips["middle"][0])
    a_t -= (a_t @ up) * up
    R0 = rot_between(a_t, a_d) @ R0
    tip = np.mean(slots[cots["middle"]], axis=0)
    t0 = tip - np.mean([R0 @ k for k in knobs["middle"]], axis=0)
    a_lat = np.cross(up, a_d)  # turning about it by +angle lifts the wrist

    # the back of the hand on a regular 2 mm grid (the decimated skin's vertices are sparse where
    # it is flat), and its strip along the middle finger, both in the TPU hand's own frame
    back_pts = back_grid(skin, -0.07)
    f_dir = tips["middle"][1] - tips["middle"][0]
    f_dir -= (f_dir @ tpu_n) * tpu_n
    lat_tpu = np.cross(tpu_n, f_dir / np.linalg.norm(f_dir))
    band = np.abs((back_pts - np.mean(knobs["middle"], axis=0)) @ lat_tpu) < 0.005
    cover_names = [n for n in COVER if n in O]
    log(f"back of the hand: {len(back_pts)} grid points, {int(band.sum())} along the middle finger; cover parts {cover_names}")

    def pose(roll, pitch, dz):
        """Rolled about the middle finger (+ lifts the index side), tilted about the lateral axis
        through the middle fingertip (+ lifts the wrist), then moved dz up."""
        Q = np.array(Matrix.Rotation(pitch, 3, Vector(a_lat)) @ Matrix.Rotation(roll, 3, Vector(a_d)))
        return Q @ R0, Q @ (t0 - tip) + tip + up * dz

    def back_gaps(R_, t_):
        """Each back point's gap up to TRIMI (negative inside it; nan with nothing above) and the
        part above it."""
        g = np.full(len(back_pts), np.nan)
        own = np.full(len(back_pts), "", dtype=object)
        for i, p in enumerate(back_pts @ R_.T + t_):
            hit = bvh_back.ray_cast(Vector(p - up * 0.03), Vector(up), 0.3)
            if hit[0] is not None and hit[1] @ Vector(up) < -0.2:
                g[i] = (np.array(hit[0]) - p) @ up
                own[i] = owners[hit[2]]
        return g, own

    def touching(R_, t_):
        """Below zero once the middle finger's strip lies on the holder's upper face (its median
        gap closed) or another part is entered."""
        g, own = back_gaps(R_, t_)
        line, other = g[band & (own == HOLDER)], g[(own != "") & ~np.isin(own, cover_names)]
        return min(np.median(line) if line.size else 1.0, other.min() if other.size else 1.0)

    def height_for(roll, pitch, dz):
        """The height at which the finger latches are best for this roll and tilt."""
        def cost(z):
            return sum(x[0] for x in latch(*pose(roll, pitch, z)).values())
        cur = cost(dz)
        for step in (0.002, 0.001, 0.0005, 0.00025):
            improved = True
            while improved:
                improved = False
                for sgn in (1, -1):
                    z = dz + sgn * step
                    if abs(z) <= 0.012:
                        c_ = cost(z)
                        if c_ < cur - 1e-7:
                            dz, cur, improved = z, c_, True
        return dz

    def tilt_to_cover(roll, dz):
        if touching(*pose(roll, 0.0, dz)) <= 0:
            return 0.0
        lo_a, hi_a = 0.0, math.radians(0.5)
        while touching(*pose(roll, hi_a, dz)) > 0 and hi_a < math.radians(20):
            lo_a, hi_a = hi_a, hi_a + math.radians(0.5)
        for _ in range(12):
            mid_a = (lo_a + hi_a) / 2
            lo_a, hi_a = (mid_a, hi_a) if touching(*pose(roll, mid_a, dz)) > 0 else (lo_a, mid_a)
        return lo_a

    def settle(roll):
        """Height and tilt for a roll (the finger latches' best height and the tilt that lays the
        back on the cover, iterated), then TRIMI's thumb for that hand pose."""
        pitch = dz = 0.0
        for _ in range(3):
            dz = height_for(roll, pitch, dz)
            pitch = tilt_to_cover(roll, dz)
        Rr, tr = pose(roll, pitch, dz)
        lat = latch(Rr, tr)
        th = thumb_search(Rr, tr)
        errs = [x[0] for x in lat.values()] + [th[1][1]]
        rms = math.sqrt(sum(e * e for e in errs) / len(errs))
        log(f"  roll {math.degrees(roll):+.1f} deg: height {dz * 1000:+.1f} mm, tilt {math.degrees(pitch):.1f} deg; latches "
            f"{ {m: round(x[0] * 1000, 1) for m, x in lat.items()} }, thumb {th[1][1] * 1000:.1f} mm; rms {rms * 1000:.1f} mm")
        return rms, pitch, dz, th

    # the roll whose four latches, thumb included, are best together (least rms, so no one
    # fingertip is left far from its cot; coarse, then finer)
    tried = {deg: settle(math.radians(deg)) for deg in (0, 4, 8, 12, 16)}
    best_deg = min(tried, key=lambda k: tried[k][0])
    for deg in (best_deg - 2, best_deg + 2, best_deg - 1, best_deg + 1):
        if deg not in tried:
            tried[deg] = settle(math.radians(deg))
    best_deg = min(tried, key=lambda k: tried[k][0])
    _, pitch, dz, thumb_fit = tried[best_deg]
    roll = math.radians(best_deg)
    R, t = pose(roll, pitch, dz)
    g, own = back_gaps(R, t)
    cov = np.isin(own, cover_names)
    line = g[band & cov]
    P = back_pts @ R.T + t
    near = own[(own != "") & (g < 0.005)]
    by = sorted({n: int(np.sum(near == n)) for n in set(near)}.items(), key=lambda x: -x[1])[:3]
    hit = own != ""
    log(f"hand rolled {math.degrees(roll):+.1f} deg about its middle finger (+ = index side up), moved {dz * 1000:+.1f} mm, "
        f"tilted {math.degrees(pitch):.1f} deg wrist up about the fingertips. Along the middle finger its back is "
        f"{np.median(line) * 1000:.1f} mm (median) / {line.max() * 1000:.1f} mm (most) from the cover; "
        f"{np.mean(g[hit] < 0.002) * 100:.0f}% of the back under TRIMI within 2 mm, {np.mean(g[hit] < 0.005) * 100:.0f}% within 5 mm {by}; "
        f"the cover presses up to {-g[cov].min() * 1000:.1f} mm into the TPU; nearest other part "
        f"{g[hit & ~cov].min() * 1000 if np.any(hit & ~cov) else float('nan'):.1f} mm")
    sq = cov & (g < -0.003)
    if sq.any():
        log(f"  squeezed more than 3 mm: {int(sq.sum())} back points, x {P[sq, 0].min() * 1000:.0f}..{P[sq, 0].max() * 1000:.0f} mm, "
            f"y {P[sq, 1].min() * 1000:.0f}..{P[sq, 1].max() * 1000:.0f} mm, by {sorted(set(own[sq]))}")
    # the palm over the holder's lower face
    clear = []
    for p in S[(S[:, 1] > -0.07) & (normals @ up < -0.5)] @ R.T + t:
        hit = bvh_lower.ray_cast(Vector(p + up * 0.05), Vector(-up), 0.2)
        if hit[0] is not None:
            clear.append((p - np.array(hit[0])) @ up)
    if clear:
        log(f"palm over the holder's lower face: {min(clear) * 1000:.1f} mm clear at the nearest, {np.median(clear) * 1000:.1f} mm median")
    for m, (d, th, off) in latch(R, t).items():
        log(f"  {m} latch with straight fingers: {d * 1000:.1f} mm at ab/ad {math.degrees(th):+.1f} deg, "
            f"knob minus slot {np.round(off * 1000, 1).tolist()} mm")

    report = {}

    def fit_module(md, R, t, steps=(0.12, 0.06, 0.03, 0.015, 0.008, 0.004)):
        ks = [R @ k + t for f in md["fingers"] for k in knobs[f]]
        f0 = md["fingers"][0]
        a_tpu = R @ (tips[f0][1] - tips[f0][0])
        a_tpu /= np.linalg.norm(a_tpu)
        gs, rest, local, cot = md["gs"], md["rest"], md["local"], md["cot"]
        for g, r in zip(gs, rest):
            g.rotation_euler[0] = r
        bpy.context.view_layer.update()
        W0 = np.array(cot.matrix_world)
        sw0 = [W0[:3, :3] @ s + W0[:3, 3] for s in local]
        if len(ks) == 2 and len(sw0) == 2:
            same = np.linalg.norm(ks[0] - sw0[0]) + np.linalg.norm(ks[1] - sw0[1])
            swap = np.linalg.norm(ks[0] - sw0[1]) + np.linalg.norm(ks[1] - sw0[0])
            order = [0, 1] if same <= swap else [1, 0]
        else:
            order = [int(np.argmin([np.linalg.norm(ks[0] - s) for s in sw0]))]

        def cost(v):
            th, dm, dp = v
            gs[0].rotation_euler[0] = rest[0] + dm
            gs[1].rotation_euler[0] = rest[1] + dp
            bpy.context.view_layer.update()
            W = turn(md["axis"], md["pivot"], th) @ np.array(cot.matrix_world)
            d = np.mean([np.linalg.norm(k - (W[:3, :3] @ local[j] + W[:3, 3])) for k, j in zip(ks, order)])
            ca = -W[:3, 2] / np.linalg.norm(W[:3, 2])
            ang = math.degrees(math.acos(np.clip(ca @ a_tpu, -1, 1)))
            return d + 0.0003 * ang + 0.002 * (dm + dp), d, ang

        v, cur = [0.0, 0.0, 0.0], cost([0.0, 0.0, 0.0])
        start = cur[1]
        for step in steps:
            improved = True
            while improved:
                improved = False
                # TRIMI's finger joints stay straight: only MCP ab/ad turns (within +-26 deg)
                for i in range(1 if STRAIGHT_FINGERS else 3):
                    for sgn in (1, -1):
                        trial = list(v)
                        trial[i] += sgn * step
                        if abs(trial[0]) > 0.45 or not (0 <= trial[1] <= 0.9) or not (0 <= trial[2] <= 0.9):
                            continue
                        c = cost(trial)
                        if c[0] < cur[0] - 1e-7:
                            v, cur, improved = trial, c, True
        cost(v)
        return v, cur, start

    gloves_out, abad_out = {}, {}
    for m, md in mods.items():
        v, cur, start = fit_module(md, R, t)
        report[m] = round(float(cur[1]) * 1000, 1)
        log(f"{m}: ab/ad {math.degrees(v[0]):+.1f} deg, MCP {math.degrees(v[1]):+.1f} deg, PIP {math.degrees(v[2]):+.1f} deg; "
            f"knob to slot {start * 1000:.1f} -> {cur[1] * 1000:.1f} mm, cot axis {cur[2]:.0f} deg")
        gloves_out[md["gnames"][0]] = round(float(md["rest"][0] + v[1]), 4)
        gloves_out[md["gnames"][1]] = round(float(md["rest"][1] + v[2]), 4)
        abad_out[m] = {"angle": round(float(v[0]), 4), "pivot": [round(float(x), 6) for x in md["pivot"]],
                       "axis": [round(float(x), 6) for x in md["axis"]], "nodes": md["nodes"]}
        # leave this module in its fitted pose for the thumb search
        md["gs"][0].rotation_euler[0] = md["rest"][0] + v[1]
        md["gs"][1].rotation_euler[0] = md["rest"][1] + v[2]
    bpy.context.view_layer.update()

    # ---- TRIMI's thumb, in the pose found for the TPU thumb during the placement
    vals, cur = thumb_fit
    for g, v in zip(th_gloves, vals):
        g.rotation_euler[0] = v
    bpy.context.view_layer.update()
    report["thumb"] = round(float(cur[1]) * 1000, 1)
    for g, v in zip(th_gloves, vals):
        gloves_out[g.name] = round(float(v), 4)
    log("TRIMI thumb", {g.name: round(float(v), 3) for g, v in zip(th_gloves, vals)}, "rest", [round(r, 3) for r in th_rest],
        f"knob to slot {cur[1] * 1000:.1f} mm, axis {cur[2]:.0f} deg")
    log("knob to slot (mm):", report)

    M = Matrix(np.vstack([np.column_stack([R, t]), [0, 0, 0, 1]]).tolist())
    keep = []
    for key, o in parts.items():
        o.matrix_world = M @ o.matrix_world
        o.name = "TPU_skin" if key == "skin" else "TPU_" + key.replace(" ", "_")
        o.parent = None
        keep.append(o)
    for o in list(bpy.data.objects):
        if o not in keep:
            bpy.data.objects.remove(o, do_unlink=True)
    for other in [sc for sc in bpy.data.scenes if sc != scene]:
        bpy.data.scenes.remove(other)
    bpy.ops.export_scene.gltf(filepath=args.out, export_format="GLB", use_selection=False, export_materials="NONE",
                              export_animations=False, export_apply=True)
    with open(os.path.splitext(args.out)[0] + ".fit.json", "w") as fh:
        json.dump({"knobToSlotMm": report, "devicePose": {"gloves": gloves_out, "abad": abad_out}}, fh, indent=1)
    log("wrote", args.out)

main()
