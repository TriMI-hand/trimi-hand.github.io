"""Export the TRIMI hardware viewer assets from TriMI_lookdev_v37.blend.

Writes two files:
  trimi_hardware.glb   the assembly, the Quest controller and wrist camera, the
                       hologram hand, the semi finger cot, and one animation per
                       viewer stage
  trimi_hardware.json  joint axes and the part lists the viewer needs
                       (Blender world coordinates)

The animations are baked from the rig in the .blend, so every part moves
exactly as it does there:
  components  CTRL_Explode "shell": the shell and the boards lift (the fingers stay assembled)
  tip         CTRL_Explode "tip": the middle fingertip comes apart; the tactile sensor
              floats between the cap and the pad, and the semi finger cot opens the same way
  finger      GLOVE_middle_MCP / PIP flex and extend (a loop), with the hologram hand
              (its thumb relaxed alongside the palm)
  thumb       the film's Kapandji opposition sequence (frames 4172-4396, a loop)

The finger parts follow the GLOVE_* empties through CHILD_OF constraints and
drivers (gears, steel balls); the script samples their evaluated world
transforms, then replaces constraints and drivers with plain keyframes.

The semi finger cot (no tactile sensor) comes from its Onshape STEP, converted
to GLB first (pip install cascadio):
  python tools/step_to_glb.py V7_1.5mm_Fingercot_Silicon_Index_Middle.step fingercot.glb
Its part-studio frame is the middle cap's ("Part 1") local frame.

Usage (from trimi-website/):
  blender -b path/to/TriMI_lookdev_v37.blend --python tools/export_hardware_glb.py -- \
    --out public/data/cad/trimi_hardware.glb --cot path/to/fingercot.glb
"""

import argparse
import json
import math
import os
import sys

import bpy
from mathutils import Matrix, Quaternion, Vector

SCENE = "TriMI_Studio"
PRODUCT = "TriMI_Product"
REST_FRAME = 100

# Parts that are hidden in the rest frame but shown at a later film frame,
# where they are also in their mounted position.
QUEST_FRAME = 1300
QUEST_PARTS = (
    "quest_controller__quest_controller",
    "quest_controller__quest_controller_covewr",
    "Quest_Menu_Button",
    "Quest_Symbol_B",
    "Quest_Symbol_MetaLogo",
    "quest top",
)
CAMERA_FRAME = 1600
CAMERA_PARTS = (
    "camera_arm",
    "Part 9.136",
    "Part 10.084",
    "Part 1.010",
    "Part 2.002",
    "Part 7.010",
    "Part 8.017",
    "Part 5__Part 5",
    "Part 6__Part 6",
    "Surface 1__Surface 1",
)
HOLOGRAM = ("HAND_Rig", "HOLO_Real")
GLOVES = (
    "GLOVE_index_MCP", "GLOVE_index_PIP", "GLOVE_middle_MCP", "GLOVE_middle_PIP",
    "GLOVE_ring_MCP", "GLOVE_ring_PIP", "GLOVE_thumb_B1", "GLOVE_thumb_B2",
    "GLOVE_thumb_MCP", "GLOVE_thumb_IP", "IDX_ABAD",
)
# Film frame of the side close-up; parts hidden there are faded out in the viewer's finger stage.
FINGER_SHOT_FRAME = 700
# Kapandji thumb-opposition sequence in the film (all joints at rest at both ends).
THUMB_RANGE = (4172, 4396)
THUMB_STEP = 2
FINGER_LOOP_FRAMES = 108  # 3.6 s at 30 fps
FINGER_STEP = 2
MCP_FLEX, PIP_FLEX = 0.95, 1.25  # radians, as in the film's flex shots

# Middle fingertip: PLA cap, tactile sensor (a child of the cap), Dragon Skin pad.
CAP, PAD, SENSOR = "Part 1", "Part 5", "TactileSensor_middle"
SENSOR_FLOAT = 0.5  # in the tip explode the sensor stops halfway between cap and pad
TIP_SPREAD = 1.5  # the tip explode's cap and pad travel, relative to the film
# Semi finger cot bodies (STEP names) -> exported name, which tip part's motion it follows, material.
COT_PARTS = {
    "Part 7": ("Cot_Shell", CAP, "PLA white"),          # rigid PLA shell with the mount
    "Part 1": ("Cot_Nail", CAP, "PLA white"),           # rigid PLA finger nail at the tip
    "Part 8": ("Cot_Silicone", PAD, "DragonSkin 10 (pressed)"),  # silicone pad on the fingerprint side
}
NAIL_SPREAD = 1.25  # in the tip explode the nail travels a little further than the shell, so it reads apart
TIP_DETAIL_TRIS = 8000  # fingertip parts are seen close up in the fingertip stage
TPU_SKIN_TRIS, TPU_INSERT_TRIS = 24000, 1500  # the TPU hand in the modular stage
TPU_COLOR, TPU_INSERT_COLOR = (0.36, 0.25, 0.18, 1.0), (0.12, 0.12, 0.13, 1.0)  # the viewer restyles them by name


def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--cot", help="semi finger cot GLB (converted from its STEP)")
    p.add_argument("--tpu", help="TPU hand GLB fitted into TRIMI by tools/fit_tpu_hand.py")
    p.add_argument("--budget", type=int, default=520000, help="target triangle count")
    p.add_argument("--min-tris", type=int, default=300, help="meshes are never decimated below this")
    p.add_argument("--smooth-angle", type=float, default=35.0)
    return p.parse_args(argv)


def log(*a):
    print("[hardware-glb]", *a, flush=True)


def tri_count(mesh):
    return sum(len(p.vertices) - 2 for p in mesh.polygons)


def fcurves(idblock, slot_only=True):
    ad = getattr(idblock, "animation_data", None)
    if not ad or not ad.action:
        return []
    slot = getattr(ad, "action_slot", None)
    res = []
    for L in ad.action.layers:
        for st in L.strips:
            for cb in st.channelbags:
                if slot_only and slot is not None and cb.slot != slot:
                    continue
                res += list(cb.fcurves)
    return res


def action_fcurve(action, path, index):
    for L in action.layers:
        for st in L.strips:
            for cb in st.channelbags:
                for fc in cb.fcurves:
                    if fc.data_path == path and fc.array_index == index:
                        return fc
    return None


def linear_keys(idblock):
    for fc in fcurves(idblock, slot_only=False):
        for k in fc.keyframe_points:
            k.interpolation = "LINEAR"


def b(v):
    return [round(float(x), 6) for x in v]


def relaxed_thumb(rig, alpha=30.0, tilt=-0.15, straight=0.75):
    """Hologram thumb pose: mostly straightened, lying near the palm plane at
    `alpha` degrees from the fingers (the rig's rest pose sticks out and bends)."""
    B = rig.data.bones

    def direction(bn):
        return (B[bn].tail_local - B[bn].head_local).normalized()

    def local(bn, delta):
        # A rotation in armature space, as the bone's own pose rotation.
        q = B[bn].matrix_local.to_3x3().to_quaternion()
        return q.inverted() @ delta @ q

    fingers = direction("middle_prox")
    radial = (B["index_prox"].head_local - B["pinky_prox"].head_local).normalized()
    dorsal = fingers.cross(radial).normalized()
    radial = dorsal.cross(fingers).normalized()
    d_meta, d_prox, d_dist = direction("thumb_meta"), direction("thumb_prox"), direction("thumb_dist")
    s1 = Quaternion().slerp(d_prox.rotation_difference(d_meta), straight)
    s2 = Quaternion().slerp(d_dist.rotation_difference(s1.inverted() @ d_meta), straight)
    chain = (s1 @ s2 @ d_dist * 0.4 + s1 @ d_prox * 0.35 + d_meta * 0.25).normalized()
    a = math.radians(alpha)
    target = (math.cos(a) * fingers + math.sin(a) * radial + tilt * dorsal).normalized()
    swing = chain.rotation_difference(target)
    return {"thumb_b1": local("thumb_b1", swing), "thumb_prox": local("thumb_prox", s1), "thumb_dist": local("thumb_dist", s2)}


# ---------------------------------------------------------------- materials
def _socket_value(sock, fallback):
    if not sock.is_linked:
        return sock.default_value
    node = sock.links[0].from_node
    if node.type == "GROUP" and sock.name in node.inputs:
        return _socket_value(node.inputs[sock.name], fallback)
    if node.type == "MAP_RANGE":
        return (node.inputs["To Min"].default_value + node.inputs["To Max"].default_value) / 2
    return fallback


def simplify_material(mat):
    """Replace a Cycles look-dev material with plain PBR factors (no textures)."""
    if not mat.node_tree:
        return
    nt = mat.node_tree
    p = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
    color, metal, rough, trans = (0.5, 0.5, 0.5, 1.0), 0.0, 0.5, 0.0
    if p:
        color = tuple(_socket_value(p.inputs["Base Color"], (0.35, 0.33, 0.25, 1.0)))
        metal = float(_socket_value(p.inputs["Metallic"], 0.0))
        rough = float(_socket_value(p.inputs["Roughness"], 0.5))
        trans = float(_socket_value(p.inputs["Transmission Weight"], 0.0))
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
    nt.links.new(bsdf.outputs[0], out.inputs["Surface"])
    bsdf.inputs["Metallic"].default_value = metal
    bsdf.inputs["Roughness"].default_value = min(1.0, max(0.05, rough))
    alpha = 1.0
    if trans > 0.5:
        # Clear plastics and lenses become see-through; silicone fingertips stay opaque and milky.
        if "DragonSkin" in mat.name:
            color, rough = (0.6, 0.61, 0.58, 1.0), 0.4
            bsdf.inputs["Roughness"].default_value = rough
        else:
            alpha = 0.28
    bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
    bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        mat.surface_render_method = "BLENDED"


# ---------------------------------------------------------------- sampling
class Sampler:
    """Records the local transform of every exported object (relative to its
    exported parent) and the pose of the hologram rig at each sample."""

    def __init__(self, ordered, rig):
        self.ordered = ordered
        self.rig = rig

    def snapshot(self):
        dg = bpy.context.evaluated_depsgraph_get()
        world = {o.name: o.evaluated_get(dg).matrix_world.copy() for o in self.ordered}
        local = {}
        for o in self.ordered:
            m = world[o.name]
            if o.parent:
                m = world[o.parent.name].inverted_safe() @ m
            local[o.name] = m.decompose()
        bones = {}
        if self.rig:
            for pb in self.rig.pose.bones:
                bones[pb.name] = (pb.location.copy(), pb.rotation_quaternion.copy())
        return local, bones


def moving(samples, rest, key):
    loc0, rot0 = rest
    for s in samples:
        l, r = s[0], s[1]
        if (l - loc0).length > 1e-6 or r.rotation_difference(rot0).angle > 1e-5:
            return True
    return False


def main():
    args = parse_args()
    scene = bpy.data.scenes[SCENE]
    if bpy.context.window:
        bpy.context.window.scene = scene
    O = bpy.data.objects

    # ---- what to export ---------------------------------------------------
    scene.frame_set(REST_FRAME)
    meshes = [o for o in bpy.data.collections[PRODUCT].all_objects if o.type == "MESH" and not o.hide_render]
    extra_meshes = [O[n] for n in QUEST_PARTS + CAMERA_PARTS if n in O]
    rig, holo = O[HOLOGRAM[0]], O[HOLOGRAM[1]]
    export = set(meshes) | set(extra_meshes) | {rig, holo} | {O[n] for n in GLOVES}
    for o in list(export):
        p = o.parent
        while p:
            export.add(p)
            p = p.parent

    def depth(o):
        d = 0
        while o.parent:
            o, d = o.parent, d + 1
        return d

    ordered = sorted(export, key=depth)
    names = {o.name for o in ordered}
    log(f"{len(meshes)} product meshes, {len(extra_meshes)} device meshes, {len(ordered)} nodes")

    # ---- facts that need the film animation, before it is frozen ----------
    scene.frame_set(FINGER_SHOT_FRAME)
    finger_hidden = sorted(o.name for o in meshes if o.hide_render)
    device_world = {}
    for frame, parts in ((QUEST_FRAME, QUEST_PARTS), (CAMERA_FRAME, CAMERA_PARTS)):
        scene.frame_set(frame)
        for n in parts:
            if n in O:
                device_world[n] = O[n].matrix_world.copy()
                if O[n].hide_render:
                    log(f"warning: {n} is hidden at frame {frame}")
    # The tactile sensor's printed-circuit texture (its look-dev material is simplified later).
    sensor_image = next((n.image for s in O[SENSOR].material_slots if s.material and s.material.node_tree
                         for n in s.material.node_tree.nodes if n.type == "TEX_IMAGE" and n.image), None)
    # Hologram bone axes: bone angle equals the GLOVE angle in the film (checked at frame 740).
    hand_act = bpy.data.actions["HAND_RigAction"]
    bone_axes = {}
    for bone, glove, frame in (("middle_prox", "GLOVE_middle_MCP", 740), ("middle_mid", "GLOVE_middle_PIP", 740)):
        q = Quaternion([action_fcurve(hand_act, f'pose.bones["{bone}"].rotation_quaternion', i).evaluate(frame) for i in range(4)])
        axis, angle = q.to_axis_angle()
        g = action_fcurve(O[glove].animation_data.action, "rotation_euler", 0).evaluate(frame)
        log(f"bone {bone}: angle {angle:.4f} vs glove {g:.4f}, axis {tuple(round(x, 4) for x in axis)}")
        bone_axes[bone] = axis.copy()
    # Film GLOVE values for the thumb sequence.
    thumb_frames = list(range(THUMB_RANGE[0], THUMB_RANGE[1] + 1, THUMB_STEP))
    glove_film = {}
    for n in GLOVES:
        o = O[n]
        if not (o.animation_data and o.animation_data.action):
            continue
        fc = next((fc for fc in fcurves(o) if fc.data_path == "rotation_euler" and fc.array_index == (2 if n == "IDX_ABAD" else 0)), None)
        if fc:
            glove_film[n] = [fc.evaluate(f) for f in thumb_frames]
    log("thumb sequence ends:", {n: (round(v[0], 4), round(v[-1], 4)) for n, v in glove_film.items()})

    # ---- freeze the film at the rest frame --------------------------------
    scene.frame_set(REST_FRAME)
    for o in list(export) + [O["CTRL_Explode"]]:
        if o.animation_data and o.animation_data.action:
            o.animation_data.action = None
    for n, m in device_world.items():
        O[n].matrix_world = m
    rig.data.pose_position = "POSE"
    for pb in rig.pose.bones:
        pb.rotation_mode = "QUATERNION"
    ctrl = O["CTRL_Explode"]
    for c in ("shell", "explode", "detail", "mid", "tip", "palm", "idx"):
        ctrl[c] = 0.0
    glove_rest = {n: O[n].rotation_euler.copy() for n in GLOVES}
    bpy.context.view_layer.update()

    # ---- semi finger cot: its part-studio frame is the middle cap's local frame
    cot = {}
    if args.cot:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=args.cot)
        cap = O[CAP]
        home = cap.users_collection[0]
        new = [o for o in bpy.data.objects if o not in before]
        worlds = {o.name: o.matrix_world.copy() for o in new}
        for o in new:
            role = COT_PARTS.get(o.name.split(".")[0]) if o.type == "MESH" else None
            if role is None:
                continue
            name, follows, mat_name = role
            world = cap.matrix_world @ worlds[o.name]
            for c in list(o.users_collection):
                c.objects.unlink(o)
            home.objects.link(o)
            o.parent = cap.parent
            o.name = o.data.name = name
            o.data.materials.clear()
            o.data.materials.append(bpy.data.materials[mat_name])
            o.matrix_world = world
            cot[name] = follows
            ordered.append(o)
            names.add(name)
        for o in new:
            if o.name not in cot:
                bpy.data.objects.remove(o, do_unlink=True)
        ordered.sort(key=depth)
        bpy.context.view_layer.update()
        log("semi finger cot:", cot)

    # ---- TPU hand: already fitted into TRIMI (world frame of the rest pose)
    tpu = []
    if args.tpu:
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=args.tpu)
        home = O[CAP].users_collection[0]
        mats = {}
        for name, color in (("TPU", TPU_COLOR), ("TPU insert", TPU_INSERT_COLOR)):
            m = bpy.data.materials.new(name)
            try:
                m.use_nodes = True
            except AttributeError:
                pass
            bsdf = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bsdf.inputs["Base Color"].default_value = color
            bsdf.inputs["Roughness"].default_value = 0.62
            mats[name] = m
        for o in [o for o in bpy.data.objects if o not in before]:
            if o.type != "MESH" or not o.name.startswith("TPU_"):
                bpy.data.objects.remove(o, do_unlink=True)
                continue
            world = o.matrix_world.copy()
            for c in list(o.users_collection):
                c.objects.unlink(o)
            home.objects.link(o)
            o.parent = None
            o.matrix_world = world
            o.data.materials.clear()
            o.data.materials.append(mats["TPU" if o.name.startswith("TPU_skin") else "TPU insert"])
            tpu.append(o.name)
            ordered.append(o)
            names.add(o.name)
        ordered.sort(key=depth)
        bpy.context.view_layer.update()
        log(f"TPU hand: {len(tpu)} parts")

    sampler = Sampler(ordered, rig)
    rest_local, rest_bones = sampler.snapshot()

    def key_ctrl(timeline, last):
        ctrl.animation_data_clear()
        for c, a, z in timeline:
            ctrl[c] = 0.0
            ctrl.keyframe_insert(f'["{c}"]', frame=1)
            ctrl.keyframe_insert(f'["{c}"]', frame=a)
            ctrl[c] = 1.0
            ctrl.keyframe_insert(f'["{c}"]', frame=z)
            ctrl.keyframe_insert(f'["{c}"]', frame=last)
        linear_keys(ctrl)

    def restore():
        ctrl.animation_data_clear()
        for c in ("shell", "explode", "detail", "mid", "tip", "palm", "idx"):
            ctrl[c] = 0.0
        for n in GLOVES:
            O[n].animation_data_clear()
            O[n].rotation_euler = glove_rest[n]
        rig.animation_data_clear()
        for pb in rig.pose.bones:
            pb.location = rest_bones[pb.name][0]
            pb.rotation_quaternion = rest_bones[pb.name][1]
        scene.frame_set(1)

    segments = {}

    def sample(name, frames):
        res = []
        for f in frames:
            scene.frame_set(f)
            res.append(sampler.snapshot())
        segments[name] = res
        log(f"segment {name}: {len(res)} samples")
        restore()

    # components: the shell and the boards lift (0-30). CTRL_Explode "explode" only takes
    # the fingers apart, so it is left out: the fingers stay assembled in this stage.
    key_ctrl((("shell", 1, 31),), 31)
    sample("components", range(1, 32))

    # tip: the middle fingertip comes apart
    key_ctrl((("tip", 1, 31),), 31)
    sample("tip", range(1, 32))

    # finger: middle MCP and PIP flex and extend, hologram follows. Its thumb is not used
    # here, so it lies straight alongside the palm instead of the rig's bent rest pose.
    gm, gp = O["GLOVE_middle_MCP"], O["GLOVE_middle_PIP"]
    loop = list(range(0, FINGER_LOOP_FRAMES + 1, FINGER_STEP))
    thumb_pose = relaxed_thumb(rig)
    for i, f in enumerate(loop):
        for bone, q in thumb_pose.items():
            pb = rig.pose.bones[bone]
            pb.rotation_quaternion = q
            pb.keyframe_insert("rotation_quaternion", frame=i + 1)
        t = f / FINGER_LOOP_FRAMES
        s = 0.5 - 0.5 * math.cos(2 * math.pi * t)
        s = s * s * (3 - 2 * s)  # ease, so the finger rests briefly at each end
        for o, amp in ((gm, MCP_FLEX), (gp, PIP_FLEX)):
            o.rotation_euler[0] = glove_rest[o.name][0] + amp * s
            o.keyframe_insert("rotation_euler", index=0, frame=i + 1)
        for bone, amp in (("middle_prox", MCP_FLEX), ("middle_mid", PIP_FLEX)):
            pb = rig.pose.bones[bone]
            pb.rotation_quaternion = Quaternion(bone_axes[bone], amp * s)
            pb.keyframe_insert("rotation_quaternion", frame=i + 1)
    for o in (gm, gp, rig):
        linear_keys(o)
    sample("finger", range(1, len(loop) + 1))

    # thumb: the film's Kapandji sequence
    for n, vals in glove_film.items():
        o = O[n]
        idx = 2 if n == "IDX_ABAD" else 0
        for i, v in enumerate(vals):
            o.rotation_euler[idx] = v
            o.keyframe_insert("rotation_euler", index=idx, frame=i + 1)
        linear_keys(o)
    sample("thumb", range(1, len(thumb_frames) + 1))

    # tpu: TRIMI takes the TPU hand: the fingers turn at MCP ab/ad and flex at MCP/PIP, the thumb
    # moves (its IP straightens). The pose comes from tools/fit_tpu_hand.py, next to the fitted
    # GLB; the ab/ad turns (about each module's ab/ad servo horn) are applied after sampling.
    tpu_pose = {"gloves": {}, "abad": {}}
    fit_json = os.path.splitext(args.tpu)[0] + ".fit.json" if args.tpu else None
    if fit_json and os.path.exists(fit_json):
        with open(fit_json) as fh:
            fit = json.load(fh)
        tpu_pose = fit.get("devicePose") or {"gloves": fit.get("thumbPose", {}), "abad": {}}
    for n, v in tpu_pose["gloves"].items():
        o = O[n]
        o.rotation_euler[0] = glove_rest[n][0]
        o.keyframe_insert("rotation_euler", index=0, frame=1)
        o.rotation_euler[0] = v
        o.keyframe_insert("rotation_euler", index=0, frame=31)
        linear_keys(o)
    if tpu_pose["gloves"] or tpu_pose["abad"]:
        sample("tpu", range(1, 32))
        log("TPU hand: TRIMI pose", tpu_pose["gloves"], {m: round(math.degrees(a["angle"]), 1) for m, a in tpu_pose["abad"].items()})

    # ---- parts that move with others. The semi finger cot follows the cap (shell, tip) or
    # the pad (silicone) in every segment; in the tip explode the sensor floats off the cap.
    def trs(t):
        return Matrix.LocRotScale(t[0], t[1], t[2])

    for seg, samples in segments.items():
        for si, (local, _bones) in enumerate(samples):
            if seg == "tpu":
                # MCP ab/ad: each finger module, with its GLOVE chain, turns about its servo horn
                u = si / max(1, len(samples) - 1)
                for ab in tpu_pose["abad"].values():
                    pivot = Vector(ab["pivot"])
                    turn = Matrix.Translation(pivot) @ Matrix.Rotation(ab["angle"] * u, 4, Vector(ab["axis"])) @ Matrix.Translation(-pivot)
                    for node in ab["nodes"]:
                        if node not in local:
                            continue
                        par = O[node].parent
                        wp = par.matrix_world.copy() if par else Matrix.Identity(4)
                        local[node] = (wp.inverted() @ turn @ wp @ trs(local[node])).decompose()
            if seg == "tip":
                # Wider apart than in the film, so the floating sensor is not hidden by cap and pad.
                for part in (CAP, PAD):
                    loc, rot, sca = local[part]
                    local[part] = (rest_local[part][0] + (loc - rest_local[part][0]) * TIP_SPREAD, rot, sca)
            moved = {part: trs(local[part]) @ trs(rest_local[part]).inverted() for part in (CAP, PAD)}
            for name, follows in cot.items():
                m = moved[follows]
                if seg == "tip" and name == "Cot_Nail":
                    m = Matrix.Translation(m.to_translation() * NAIL_SPREAD)  # the cap only translates here
                local[name] = (m @ trs(rest_local[name])).decompose()
            if seg == "tip":
                gap = (local[PAD][0] - rest_local[PAD][0]) - (local[CAP][0] - rest_local[CAP][0])
                loc, rot, sca = local[SENSOR]
                local[SENSOR] = (loc + trs(local[CAP]).to_3x3().inverted() @ (gap * SENSOR_FLOAT), rot, sca)

    # ---- replace constraints and drivers with keyframes, one NLA track per segment
    nodes_moving = {}
    for o in ordered:
        if o.animation_data:
            for d in list(o.animation_data.drivers):
                o.animation_data.drivers.remove(d)
            o.animation_data_clear()
        for c in list(o.constraints):
            o.constraints.remove(c)
        o.delta_location = (0, 0, 0)
        o.delta_rotation_euler = (0, 0, 0)
        o.delta_rotation_quaternion = (1, 0, 0, 0)
        o.delta_scale = (1, 1, 1)
        o.rotation_mode = "QUATERNION"
        o.matrix_parent_inverse = Matrix.Identity(4)
        loc0, rot0, sca0 = rest_local[o.name]
        o.location, o.rotation_quaternion, o.scale = loc0, rot0, sca0
    rig.animation_data_clear()
    for pb in rig.pose.bones:
        pb.location, pb.rotation_quaternion = rest_bones[pb.name]

    for seg, samples in segments.items():
        n_moving = 0
        for o in ordered:
            series = [s[0][o.name] for s in samples]
            if not moving(series, rest_local[o.name][:2], o.name):
                continue
            n_moving += 1
            nodes_moving.setdefault(seg, []).append(o.name)
            ad = o.animation_data_create()
            act = bpy.data.actions.new(f"{seg}__{o.name}")
            ad.action = act
            for i, (l, r, sc) in enumerate(series):
                o.location, o.rotation_quaternion = l, r
                o.keyframe_insert("location", frame=i + 1)
                o.keyframe_insert("rotation_quaternion", frame=i + 1)
            linear_keys(o)
            slot = ad.action_slot
            ad.action = None
            track = ad.nla_tracks.new()
            track.name = seg
            strip = track.strips.new(seg, 1, act)
            if slot is not None and hasattr(strip, "action_slot"):
                strip.action_slot = slot
            o.location, o.rotation_quaternion = rest_local[o.name][0], rest_local[o.name][1]
        # hologram rig
        bone_series = {bn: [s[1][bn] for s in samples] for bn in rest_bones}
        moving_bones = [bn for bn, ser in bone_series.items()
                        if any(r.rotation_difference(rest_bones[bn][1]).angle > 1e-5 for _, r in ser)]
        if moving_bones:
            ad = rig.animation_data_create()
            act = bpy.data.actions.new(f"{seg}__{rig.name}")
            ad.action = act
            for i in range(len(samples)):
                for bn in moving_bones:
                    pb = rig.pose.bones[bn]
                    pb.rotation_quaternion = bone_series[bn][i][1]
                    pb.keyframe_insert("rotation_quaternion", frame=i + 1)
            linear_keys(rig)
            slot = ad.action_slot
            ad.action = None
            track = ad.nla_tracks.new()
            track.name = seg
            strip = track.strips.new(seg, 1, act)
            if slot is not None and hasattr(strip, "action_slot"):
                strip.action_slot = slot
            for bn in moving_bones:
                rig.pose.bones[bn].rotation_quaternion = rest_bones[bn][1]
        log(f"segment {seg}: {n_moving} nodes and {len(moving_bones)} bones move")

    # ---- joint data for the viewer ------------------------------------------
    def world(o):
        return o.matrix_world

    bpy.context.view_layer.update()
    joints = {}
    for n in GLOVES:
        o = O[n]
        m = world(o)
        axis = (m.to_3x3() @ Vector((0, 0, 1) if n == "IDX_ABAD" else (1, 0, 0))).normalized()
        joints[n] = {"pivot": b(m.translation), "axis": b(axis)}
    # Middle finger ab/ad: the abduction servo's output, placed as on the index finger
    # (IDX_ABAD sits on its servo's horn), axis normal to the palm.
    horn = O["Revolve1[1]"]
    hb = [horn.matrix_world @ Vector(c) for c in horn.bound_box]
    joints["middle_ABAD"] = {"pivot": b(sum(hb, Vector()) / 8), "axis": b(O["IDX_ABAD"].matrix_world.to_3x3() @ Vector((0, 0, 1)))}
    rings = {}
    for n in ("ROT_middle_MCP_ring", "ROT_middle_MCP_pitch", "ROT_middle_PIP_ring", "ROT_middle_PIP_pitch"):
        o = O[n]
        pts = [o.matrix_world @ Vector(p.co[:3]) for s in o.data.splines for p in s.points]
        c = sum(pts, Vector()) / len(pts)
        rings[n] = {"center": b(c), "radius": round(sum((p - c).length for p in pts) / len(pts), 6)}

    # ---- remove everything else ------------------------------------------
    for other in [sc for sc in bpy.data.scenes if sc != scene]:
        bpy.data.scenes.remove(other)
    for o in list(bpy.data.objects):
        if o.name not in names:
            bpy.data.objects.remove(o, do_unlink=True)

    # ---- materials ---------------------------------------------------------
    export_meshes = [o for o in ordered if o.type == "MESH"]
    for o in export_meshes:
        if o != holo:
            for m in list(o.modifiers):
                o.modifiers.remove(m)  # e.g. the pad's dent node group, which the film uses for its ball press
    mats = {s.material for o in export_meshes if o != holo for s in o.material_slots if s.material}
    for m in mats:
        simplify_material(m)
    log(f"{len(mats)} materials simplified")
    # The middle tactile sensor keeps its printed-circuit texture; the viewer shows it only
    # while the fingertip is apart.
    sensor = O[SENSOR]
    if sensor_image:
        mat = bpy.data.materials.new("Tactile sensor (middle)")
        try:
            mat.use_nodes = True
        except AttributeError:
            pass
        nt = mat.node_tree
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = sensor_image
        uvn = nt.nodes.new("ShaderNodeUVMap")
        uvn.uv_map = sensor.data.uv_layers[0].name
        nt.links.new(uvn.outputs["UV"], tex.inputs["Vector"])
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(tex.outputs["Alpha"], bsdf.inputs["Alpha"])
        bsdf.inputs["Roughness"].default_value = 0.35
        mat.surface_render_method = "BLENDED"
        sensor.data.materials.clear()
        sensor.data.materials.append(mat)
        log(f"sensor texture {sensor_image.name} {tuple(sensor_image.size)}")

    # ---- hologram: apply its subdivision, keep the armature ----------------
    rig.data.pose_position = "REST"
    arm_mod = next(m for m in holo.modifiers if m.type == "ARMATURE")
    arm_mod.show_viewport = False
    dg = bpy.context.evaluated_depsgraph_get()
    hmesh = bpy.data.meshes.new_from_object(holo.evaluated_get(dg), preserve_all_data_layers=True, depsgraph=dg)
    for m in [m for m in holo.modifiers if m.type != "ARMATURE"]:
        holo.modifiers.remove(m)
    holo.data = hmesh
    arm_mod.show_viewport = True
    rig.data.pose_position = "POSE"
    log(f"hologram {tri_count(hmesh)} tris")

    # ---- decimate each unique mesh once, so instanced parts stay instanced
    users = {}
    for o in export_meshes:
        if o != holo:
            users.setdefault(o.data, []).append(o)
    total = sum(tri_count(m) * len(us) for m, us in users.items())
    ratio = min(1.0, args.budget / max(1, total))
    log(f"source tris {total}, global ratio {ratio:.4f}")
    after = 0
    tip_detail = {CAP, PAD, *cot}
    for mesh, us in users.items():
        n = tri_count(mesh)
        names_here = {u.name for u in us}
        if SENSOR in names_here:
            r = 1.0  # small, and its texture needs the original UVs
        elif any(nm.startswith("TPU_") for nm in names_here):
            r = min(1.0, (TPU_SKIN_TRIS if "TPU_skin" in names_here else TPU_INSERT_TRIS) / max(1, n))
        elif names_here & tip_detail:
            r = min(1.0, TIP_DETAIL_TRIS / max(1, n))
        elif mesh.name.startswith("Ball_"):
            r = 0.15
        else:
            r = 1.0 if n <= args.min_tris else max(ratio, min(1.0, args.min_tris / n))
        if r < 0.999:
            o = us[0]
            mod = o.modifiers.new("web_decimate", "DECIMATE")
            mod.decimate_type = "COLLAPSE"
            mod.ratio = r
            mod.use_collapse_triangulate = True
            dg = bpy.context.evaluated_depsgraph_get()
            new = bpy.data.meshes.new_from_object(o.evaluated_get(dg), preserve_all_data_layers=False, depsgraph=dg)
            o.modifiers.remove(mod)
            new.name = mesh.name + "_web"
            for u in us:
                u.data = new
            mesh = new
        mesh.set_sharp_from_angle(angle=math.radians(args.smooth_angle))
        after += tri_count(mesh) * len(us)
    log(f"web tris {after}")

    # Only the textured sensor needs UVs.
    for me in {o.data for o in export_meshes if o.name != SENSOR}:
        while me.uv_layers:
            me.uv_layers.remove(me.uv_layers[0])

    # ---- export ------------------------------------------------------------
    scene.frame_start, scene.frame_end = 1, 200
    scene.frame_set(1)
    bpy.ops.export_scene.gltf(
        filepath=args.out,
        export_format="GLB",
        use_selection=False,
        export_cameras=False,
        export_lights=False,
        export_apply=False,
        export_texcoords=True,
        export_normals=True,
        export_materials="EXPORT",
        export_skins=True,
        export_animations=True,
        export_animation_mode="NLA_TRACKS",
        export_merge_animation="NLA_TRACK",
        export_anim_slide_to_zero=True,
        export_force_sampling=False,
        export_optimize_animation_size=True,
        export_draco_mesh_compression_enable=True,
        export_draco_mesh_compression_level=6,
        export_draco_position_quantization=14,
        export_draco_normal_quantization=10,
    )
    log(f"wrote {args.out} ({os.path.getsize(args.out)} bytes)")

    meta = {
        "source": "TriMI_lookdev_v37.blend",
        "fps": 30,
        "segments": {
            "components": {"samples": len(segments["components"]), "fps": 30, "shell": [0, 30]},
            "tip": {"samples": len(segments["tip"]), "fps": 30},
            "finger": {"samples": len(segments["finger"]), "fps": 30 / FINGER_STEP, "loop": True},
            "thumb": {"samples": len(segments["thumb"]), "fps": 30 / THUMB_STEP, "loop": True, "filmFrames": list(THUMB_RANGE)},
            **({"tpu": {"samples": len(segments["tpu"]), "fps": 30, "pose": tpu_pose}} if "tpu" in segments else {}),
        },
        "moving": {k: len(v) for k, v in nodes_moving.items()},
        "fingerHidden": finger_hidden,
        "quest": [n for n in QUEST_PARTS if n in O],
        "camera": [n for n in CAMERA_PARTS if n in O],
        "hologram": {"mesh": holo.name, "rig": rig.name},
        "joints": joints,
        "rings": rings,
        # Fingertip options: the tactile finger cot and the semi finger cot (no tactile sensor).
        "tactileCot": {"cap": CAP, "sensor": SENSOR, "pad": PAD},
        "semiCot": {"shell": "Cot_Shell", "nail": "Cot_Nail", "silicone": "Cot_Silicone"} if cot else None,
        # TPU hand latched into the finger cots, shown instead of the Quest in the modular stage
        "tpu": sorted(tpu),
    }
    meta_path = os.path.splitext(args.out)[0] + ".json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=1)
    log(f"wrote {meta_path}")


main()
