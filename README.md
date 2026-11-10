# TriMI research page

Adapted from the [NAS-GS-Page template](https://github.com/SenseRoboticsLab/NAS-GS-Page). This version retains the centered paper title, Noto Sans typography, resource-link pills, MDX content, and grey highlighted sections. It includes video galleries for dexterity, demonstrations, autonomous execution, wearability, and teleoperation, a scroll-driven Three.js hardware tour, and a placeholder for the main project video.

## Run and build

Requires Node.js 24+ and pnpm 11.25.0. From this directory:

```sh
pnpm install --frozen-lockfile
pnpm dev --host 127.0.0.1
pnpm build
pnpm preview --host 127.0.0.1
```

`build` runs Astro's type checks and produces `dist/`. Serve `dist/` for a production preview. Internet access is needed during installation and the first build to obtain dependencies and font files. Videos and their poster frames are served locally. If pnpm requests dependency build approvals during installation, review and approve the listed `esbuild` and `sharp` packages with `pnpm approve-builds esbuild sharp`.

For deployment below a subpath such as `/TRIMI/`, run `pnpm check` then `pnpm astro build --base /TRIMI/`. Asset references and the viewer respect Astro's base URL. Pushing to `main` runs `.github/workflows/deploy.yml`, which builds with the repository name as the base path and publishes to GitHub Pages at https://trimi-hand.github.io/.

## Edit the content

- `src/paper.mdx`: title, links, author order, shared affiliation, and research sections.
- `src/pages/index.astro`: NAS-GS-derived page shell and template attribution.
- `src/styles/global.css`: upstream Tailwind typography and layout.
- `src/styles/trimi.css`: responsive hardware viewer, video tabs, placeholders, and TriMI additions.
- `src/components/HardwareExplorer.astro` and `src/scripts/hardware-viewer.js`: scroll-driven hardware tour in seven stages, with callout labels, drag/keyboard rotation, pause, reset, and stage buttons.
- `src/components/VideoCard.astro`: uniform 16:9 players, posters, captions, and policy results.
- `src/components/VideoTabs.astro` and `src/scripts/video-tabs.ts`: one large player per selected tab, keyboard navigation, and automatic pausing of the previous clip.
- `src/components/MediaPlaceholder.astro`: main project video placeholder.
- `src/components/Teleoperation.astro`: cross-hand and Midas force-feedback sections.
- `src/scripts/theme.js`: contrasting foregrounds throughout the teleoperation fade.
- `public/data/`: existing project assets.
- `public/videos/`: H.264 MP4s, JPEG posters, and a source/timing manifest.

The hardware viewer stops rendering off screen, respects reduced motion, and falls back to an existing CAD image if 3D graphics cannot load. `public/draco/` contains the decoder distributed with Three.js 0.172.0; retain its notices when updating.

Multi-video sections use tabs to show one large player at a time. Switching tabs pauses the previous clip and preserves its playback position. Arrow keys, Home, and End select tabs; with JavaScript disabled, all clips are shown. Run the interaction checks with `node --test tools/video-tabs.test.mjs`.

## Prepare videos

The supplied clips are converted to 1280×720 H.264 MP4 with faststart and AAC audio. Portrait footage is letterboxed without cropping; HDR demonstrations are tone-mapped to SDR. Players start muted, with controls and posters; videos load on demand.

With Python and FFmpeg available, run:

```sh
python tools/prepare_media.py --source-root ../../video_assets
```

The script also detects a portable `imageio-ffmpeg` installation in `../../.media-tools`. Original footage is left untouched. `public/videos/manifest.json` records source names, output durations, and segment boundaries. `IMG_3880.mov` is the cube pick-and-place rollout; `IMG_3877.mov` is cap unscrewing. Teleoperation is split into 0–3 seconds and the remainder of `teleop.mov`.

## Hardware viewer

The hardware section scrolls through seven stages:

1. Overview: the assembled interface.
2. Components: the shell and the boards lift, with labels for the boards and fingers. The fingers stay assembled.
3. Finger Design: a side close-up of the middle finger flexing. It shows each joint's rotation centre as concentric circles, the MCP abduction axis, the steel balls (one side link turns see-through), and the hologram hand.
4. Thumb Design: the thumb-opposition sequence, with a translucent cylinder and a label on each thumb axis.
5. Fingertip Design: the middle fingertip's two finger cots take turns, seen from above. The tactile finger cot comes apart into the PLA cap, the tactile sensor and the silicone pad. The sensor unrolls flat, parallel to the palm, and shows its printed circuit. The semi finger cot (no tactile sensor) comes apart into its PLA finger nail, PLA shell and silicone pad.
6. Modular Design: the Quest controller and the OAK-1 wrist camera attach.
7. TPU Hand: the Quest controller comes off and the TPU hand slides in, about where the hologram hand sits. It keeps its STEP shape with no joint bent. Its back lies on the palm holder's upper face and its fingertips sit in the finger cots. TRIMI moves to take it:
   - its fingers stay straight (MCP and PIP at zero); each finger only turns at MCP ab/ad;
   - its thumb IP bends 10 degrees, and the thumb's other three joints move to the TPU thumb.

   The fingertip latch knobs end up 1 to 9 mm from their keyhole slots: index 2, middle 1, ring and pinky 9, thumb 6. The TPU hand is one skin colour; its joint inserts take the same colour.

Stage 5 switches between its two finger cots on a timer. The buttons above it switch at once.

Stages 3–5 switch the section to a dark backdrop, as in the film.

`public/data/cad/trimi_hardware.glb` (about 3.9 MB) and `trimi_hardware.json` are exported from `TriMI_lookdev_v37.blend` by `tools/export_hardware_glb.py`. The .blend is about 260 MB, so keep it outside the repository.

The script bakes the .blend's own rig into one animation per stage:

- `CTRL_Explode` for the shell and the fingertip
- the `GLOVE_*` empties for the finger and thumb motion. Their parts follow through CHILD_OF constraints and drivers.

It also adds the semi finger cot from its Onshape STEP, whose frame is the middle cap's local frame, and the placed TPU hand, with TRIMI's pose for it baked as the `tpu` animation. It decimates the 7M-triangle CAD to about 560k triangles and replaces the look-dev materials with plain PBR colors, except the middle tactile sensor, which keeps its printed-circuit texture. The JSON holds joint axes, the ring sizes from the `ROT_*` curves, and the part names of both finger cots.

The viewer adds the rest itself:

- the clear-resin palm cover and the translucent silicone
- the glowing U2D2 status LEDs
- the hologram shader
- the finger cot cycle
- the sensor's printed circuit, which shows only while the tactile finger cot is apart. It unrolls along its UV layout (the flat cut pattern) into the plane of its palm-side face, so closing the cot rolls it back onto the cap.

The TPU hand (Onshape `FULLHAND_V5`) is modelled flat, with its fingers together, and keeps that shape. `tools/fit_tpu_hand.py` places it first:

- It finds the latch knobs on the fingertips and the keyhole slots in the cots.
- TRIMI's palm holder (`palm_holder_v2`) has an upper face over the back of the hand and, on the pinky side, a half lower face under the palm. The hand goes between them, so only the upper face, and the part behind it over the wrist (`palm_holder_v4`), count as the back-of-hand cover.
- The hand starts level, with its middle finger along TRIMI's and the middle fingertip latched. It then turns about that fingertip:
  - It rolls about its middle finger (about 10 degrees, index side up) and moves up or down, so the other fingertips come into their cots. TRIMI's cots fall away toward the pinky, as a hand does, while the TPU hand is flat. The roll and height balance all four latches, thumb included, for the least rms error.
  - It tilts about the fingertips, wrist up (about 8 degrees), until its back lies on the holder's upper face along the middle finger, from the knuckles to the wrist.
- The holder's upper face arches more than the TPU back does, so its ends press into the soft TPU, up to about 20 mm at the index-side end. No other part of TRIMI enters the hand.
- TRIMI's fingers are rigged for flexion only; the index has an ab/ad empty that does not carry its flexing parts. So each finger's MCP ab/ad is a turn of the whole finger module and its `GLOVE_*` chain about its ab/ad servo horn. TRIMI's fingers stay straight (`STRAIGHT_FINGERS`). The thumb IP is held at 10 degrees of bend (`THUMB_IP`). The script searches each module's ab/ad and the thumb's B1, B2 and MCP so the cot slots meet the knobs.
- The export bakes that TRIMI pose as the `tpu` animation (rest to fitted). In the .blend, each finger part is parented to its module and also follows its `GLOVE_*` chain through CHILD_OF, so a preview that turns both nodes in Blender doubles the turn. The export turns the baked glTF nodes, where no part has both nodes as ancestors.

```sh
pip install cascadio
python tools/step_to_glb.py path/to/V7_1.5mm_Fingercot_Silicon_Index_Middle.step fingercot.glb
python tools/step_to_glb.py path/to/FULLHAND_V5.step tpu_hand.glb
blender -b path/to/TriMI_lookdev_v37.blend \
  --python tools/fit_tpu_hand.py -- --tpu tpu_hand.glb --out tpu_fitted.glb
blender -b path/to/TriMI_lookdev_v37.blend \
  --python tools/export_hardware_glb.py -- \
  --out public/data/cad/trimi_hardware.glb --cot fingercot.glb --tpu tpu_fitted.glb
```

`--budget` sets the triangle target (default 520000). Without `--cot` the fingertip stage shows the tactile finger cot only. Without `--tpu` there is no TPU hand to show in the last stage.

In `src/scripts/hardware-viewer.js`:

- Callout text lives in `LABELS`.
- Each stage's timing lives in `stageState()`.
- Camera framing lives in `shots`.
- `?hwsnap&hwtime=<seconds>` in the page URL skips scroll smoothing and freezes the loops, for screenshots. `&hwcot=<0..1>` pins the finger cot cycle (below 0.5 the tactile finger cot, above it the semi finger cot).

## Materials still needed

Physical hardware photographs are still to come. The CMC and IP thumb axis names are inferred from the rig's axis directions; confirm them before publication.

The main project video, arXiv URL, X Summary URL, and public GitHub release link remain pending. Resource pills without a URL are visibly disabled. Add the arXiv, Summary, and GitHub URLs in `src/paper.mdx` when available. The citation section can be restored when the paper is released.

See `TEMPLATE.md` for source attribution and license information.
