/**
 * Scroll-driven tour of the TRIMI hardware in seven stages.
 *
 * Assets: data/cad/trimi_hardware.glb and trimi_hardware.json, exported from
 * TriMI_lookdev_v37.blend by tools/export_hardware_glb.py. The GLB holds one
 * animation per stage, baked from the .blend's own rig:
 *   components  the shell and the boards lift; the fingers stay assembled (scroll-driven)
 *   finger      the middle finger's MCP and PIP flex and extend (a loop)
 *   thumb       the Kapandji thumb-opposition sequence from the film (a loop)
 *   tip         the middle fingertip comes apart (scroll-driven); the tactile
 *               sensor floats between cap and pad, the semi finger cot opens alike
 * The fingertip stage alternates the two finger cots: the tactile one (PLA cap,
 * tactile sensor, silicone pad) and the semi finger cot (PLA shell and a
 * silicone fingerprint side, no tactile sensor).
 * The JSON holds joint axes and part lists, in Blender world coordinates
 * (x, y, z), which are (x, z, -y) in the GLB.
 */

// ---------------------------------------------------------------- stages
// Stage k spans scroll progress [k/7, (k+1)/7). Inside a stage, local time t
// runs 0..1: roughly the first quarter moves the camera from the previous
// stage, the rest shows the stage.
const STAGE_COUNT = 7;
// Where clicking a stage button lands, as local time inside that stage.
const STEP_LANDING = 0.72;

const ACCENT = 0xff7a1a; // rotation-centre orange from the film
const AXIS_OPACITY = 0.5; // translucent joint-axis cylinders
const LABELS = {
  components: [
    { node: "nano-board__Cut-Extrude6", title: "Tactile sensor board", dashed: true },
    { node: "U2D2_PCB", title: "ROBOTIS U2D2", sub: "USB to servo bus", dashed: true },
    { node: "DC15_A01_CASE_M_DUMMY.005", title: "Index", sub: "3 DoF" },
    { node: "DC15_A01_CASE_M_DUMMY.001", title: "Middle", sub: "3 DoF" },
    { node: "DC15_A01_CASE_M_DUMMY.010", title: "Ring / Pinky", sub: "3 DoF" },
    { node: "DC15_A01_CASE_M_DUMMY.022", title: "Thumb", sub: "4 DoF" },
  ],
  finger: [
    { joint: "mcpRing", title: "MCP flexion" },
    { joint: "pipRing", title: "PIP / DIP flexion" },
    { joint: "abad", title: "MCP abduction / adduction" },
    { node: "Ball_MCP_r_28m1", title: "Steel balls", sub: "Arc-slot bearing" },
  ],
  thumb: [
    { joint: "GLOVE_thumb_B1", title: "CMC abduction / adduction" },
    { joint: "GLOVE_thumb_B2", title: "CMC flexion / extension" },
    { joint: "GLOVE_thumb_MCP", title: "MCP abduction / adduction" },
    { joint: "GLOVE_thumb_IP", title: "IP flexion / extension" },
  ],
  // The rest of the hand fills the right of this shot, so these labels go left.
  // tip: the tactile finger cot; cot: the semi finger cot. The stage alternates them.
  tip: [
    { node: "Part 1", title: "Fingertip shell", sub: "PLA", side: "left" },
    { node: "TactileSensor_middle", title: "Tactile sensor", side: "left" },
    { node: "Part 5", title: "Silicone pad", sub: "Dragon Skin 10", side: "left" },
  ],
  cot: [
    { node: "Cot_Nail", title: "Finger nail", sub: "PLA", side: "left" },
    { node: "Cot_Shell", title: "Finger cot shell", sub: "PLA", side: "left" },
    { node: "Cot_Silicone", title: "Silicone pad", sub: "Dragon Skin 10", side: "left" },
  ],
  // Modular stage: the wrist camera and the Quest controller; TPU hand stage: the TPU hand.
  camera: [{ node: "Part 9.136", title: "OAK-1", sub: "Wrist camera" }],
  quest: [{ node: "quest_controller__quest_controller", title: "Meta Quest controller", sub: "Wrist position tracking" }],
  tpu: [{ node: "TPU_skin", title: "TPU hand", sub: "Latched into the finger cots" }],
};
// The two fingertip options, as buttons above the fingertip stage.
const COT_OPTIONS = [
  { title: "Tactile finger cot", sub: "With tactile sensor" },
  { title: "Semi finger cot", sub: "Without tactile sensor" },
];
// One full cycle of the fingertip options, in seconds: each is shown apart, closes, swaps.
const COT_PERIOD = 9;
// Parts made see-through in the finger stage so the steel balls show.
const BALL_COVERS = ["_mcp_link_r_v2_right", "_pip_link_r_v2_right"];
const LEDS = [
  { node: "U2D2_LED_PWR", color: 0xff2a14, blink: false },
  { node: "U2D2_LED_RxD", color: 0xff8a10, blink: true, seed: 3 },
  { node: "U2D2_LED_TxD", color: 0x22ff44, blink: true, seed: 11 },
];

const clamp01 = (v) => Math.max(0, Math.min(1, v));
const smooth = (a, b, v) => {
  const t = clamp01((v - a) / (b - a));
  return t * t * (3 - 2 * t);
};

/** Everything that depends on scroll progress p (0..1). */
function stageState(p) {
  const f = clamp01(p) * STAGE_COUNT;
  const k = Math.min(STAGE_COUNT - 1, Math.floor(f));
  const t = f - k;
  const s = {
    stage: k,
    t,
    explode: 0,
    tip: 0,
    finger: 0,
    thumb: 0,
    focus: 0, // fades out everything but the middle finger
    rings: 0,
    holo: 0,
    covers: 0,
    thumbAxes: 0,
    devices: 0, // the wrist camera
    quest: 0,
    tpu: 0, // the TPU hand
    tpuFit: 0, // TRIMI takes the TPU hand: fingers turn and flex, the thumb moves
    dark: 0,
    labels: {},
    shotFrom: Math.max(0, k - 1),
    shotTo: k,
    shotBlend: k === 0 ? 1 : smooth(0.06, 0.34, t),
  };
  if (k === 1) {
    s.explode = smooth(0.2, 0.62, t);
    s.labels.components = smooth(0.6, 0.72, t);
  }
  if (k === 2) {
    s.labels.components = 1 - smooth(0, 0.06, t);
    s.explode = 1 - smooth(0.02, 0.18, t);
    s.focus = smooth(0.14, 0.26, t);
    s.dark = smooth(0.1, 0.3, t);
    s.finger = smooth(0.24, 0.36, t);
    s.rings = smooth(0.34, 0.46, t);
    s.covers = smooth(0.34, 0.46, t);
    s.holo = smooth(0.42, 0.56, t);
    s.labels.finger = smooth(0.5, 0.62, t);
  }
  if (k === 3) {
    s.dark = 1;
    s.labels.finger = 1 - smooth(0, 0.05, t);
    s.holo = 1 - smooth(0, 0.08, t);
    s.rings = 1 - smooth(0, 0.08, t);
    s.covers = 1 - smooth(0, 0.08, t);
    s.finger = 1 - smooth(0.02, 0.14, t);
    s.focus = 1 - smooth(0.06, 0.18, t);
    s.thumb = smooth(0.26, 0.38, t);
    s.thumbAxes = smooth(0.34, 0.46, t);
    s.labels.thumb = smooth(0.44, 0.56, t);
  }
  if (k === 4) {
    s.dark = 1;
    s.labels.thumb = 1 - smooth(0, 0.05, t);
    s.thumbAxes = 1 - smooth(0, 0.08, t);
    s.thumb = 1 - smooth(0.02, 0.14, t);
    s.tip = smooth(0.36, 0.62, t);
    // Shared by both finger cots; the frame loop splits it between them.
    s.labels.tip = smooth(0.6, 0.72, t);
  }
  if (k === 5) {
    s.labels.tip = 1 - smooth(0, 0.05, t);
    s.tip = 1 - smooth(0.02, 0.16, t);
    s.dark = 1 - smooth(0.06, 0.26, t);
    s.devices = s.quest = smooth(0.28, 0.6, t);
    s.labels.modular = smooth(0.62, 0.74, t);
  }
  if (k === 6) {
    // The Quest controller comes off, TRIMI's fingers and thumb open to the TPU hand, which slides in.
    s.labels.modular = 1 - smooth(0, 0.06, t);
    s.devices = 1;
    s.quest = 1 - smooth(0.04, 0.3, t);
    s.tpuFit = smooth(0.2, 0.5, t);
    s.tpu = smooth(0.3, 0.62, t);
    s.labels.tpu = smooth(0.62, 0.74, t);
  }
  return s;
}

export function initHardwareViewer() {
  const base = import.meta.env.BASE_URL.replace(/\/?$/, "/");
  const section = document.querySelector("#hardware");
  const container = document.querySelector("#hardware-canvas");
  if (!section || !container) return () => {};

  const poster = container.querySelector(".hardware-poster");
  const overlay = document.querySelector("#hardware-labels");
  const status = document.querySelector("#hardware-status");
  const resetButton = document.querySelector("#hardware-reset");
  const motionButton = document.querySelector("#hardware-motion");
  const progressBar = document.querySelector("#hardware-progress");
  const steps = [...document.querySelectorAll("[data-hardware-step]")];
  const motionPreference = window.matchMedia(
    "(prefers-reduced-motion: reduce)",
  );
  const listeners = new AbortController();
  let progress = 0;
  let activeStep = -1;
  let inView = false;
  let loading = false;
  let destroyed = false;
  let cleanupScene = () => {};
  let wake = () => {};

  function setStatus(message) {
    if (status && status.textContent !== message) status.textContent = message;
  }

  function disableControls() {
    if (resetButton) resetButton.disabled = true;
    if (motionButton) motionButton.disabled = true;
  }

  function showPoster(message) {
    section.classList.add("hardware-static");
    section.classList.remove("is-dark");
    section.dataset.viewerState = "static";
    container.classList.remove("is-ready");
    if (poster) poster.hidden = false;
    if (overlay) overlay.replaceChildren();
    disableControls();
    setStatus(message);
    updateProgress();
  }

  function stageMetrics() {
    const stage = section.querySelector(".hardware-stage");
    const stageHeight = stage ? stage.offsetHeight : window.innerHeight;
    const stickyTop = stage ? parseFloat(getComputedStyle(stage).top) || 0 : 0;
    return { stageHeight, stickyTop };
  }

  function updateProgress() {
    const rect = section.getBoundingClientRect();
    // The progress range is the travel of the sticky stage, not the full section.
    const { stageHeight, stickyTop } = stageMetrics();
    progress = clamp01(
      (stickyTop - rect.top) / Math.max(1, rect.height - stageHeight),
    );
    if (progressBar) {
      progressBar.style.transform = `scaleX(${progress})`;
      progressBar.setAttribute(
        "aria-valuenow",
        String(Math.round(progress * 100)),
      );
    }
    const nextStep = Math.min(
      STAGE_COUNT - 1,
      Math.floor(progress * STAGE_COUNT),
    );
    if (nextStep !== activeStep) {
      activeStep = nextStep;
      steps.forEach((button) => {
        const selected = Number(button.dataset.hardwareStep) === nextStep;
        button.setAttribute("aria-pressed", String(selected));
        button.classList.toggle("is-active", selected);
      });
      section.dataset.hardwareStep = String(nextStep);
    }
    wake();
  }

  steps.forEach((button) =>
    button.addEventListener(
      "click",
      () => {
        const { stageHeight, stickyTop } = stageMetrics();
        const sectionTop = section.getBoundingClientRect().top + window.scrollY;
        const k = Number(button.dataset.hardwareStep);
        const stepProgress = k === 0 ? 0.02 : (k + STEP_LANDING) / STAGE_COUNT;
        window.scrollTo({
          top:
            sectionTop -
            stickyTop +
            Math.max(0, section.offsetHeight - stageHeight) * stepProgress,
          behavior: motionPreference.matches ? "instant" : "smooth",
        });
      },
      { signal: listeners.signal },
    ),
  );

  window.addEventListener("scroll", updateProgress, {
    passive: true,
    signal: listeners.signal,
  });
  window.addEventListener("resize", updateProgress, {
    passive: true,
    signal: listeners.signal,
  });
  updateProgress();
  disableControls();

  async function loadViewer() {
    if (loading || destroyed || motionPreference.matches) return;
    loading = true;
    section.classList.remove("hardware-static");
    section.dataset.viewerState = "loading";
    updateProgress();
    setStatus("Loading the interactive assembly…");
    let renderer;
    let model;
    let environment;
    let decoder;
    let resizeObserver;
    let raf = 0;
    let failed = false;
    let paused = false;
    let lastFrame = 0;
    let lastInteraction = 0;
    let smoothedProgress = progress;
    const disposables = [];
    const sceneListeners = new AbortController();

    function disposeModel(object) {
      object?.traverse((node) => {
        node.geometry?.dispose();
        const materials = Array.isArray(node.material)
          ? node.material
          : [node.material];
        materials.filter(Boolean).forEach((material) => {
          material.map?.dispose();
          material.dispose();
        });
      });
    }

    const disposeScene = () => {
      if (failed) return;
      failed = true;
      cancelAnimationFrame(raf);
      raf = 0;
      resizeObserver?.disconnect();
      sceneListeners.abort();
      decoder?.dispose();
      disposeModel(model);
      disposables.forEach((d) => d.dispose());
      environment?.dispose();
      renderer?.dispose();
      renderer?.domElement.remove();
      overlay?.replaceChildren();
      section.classList.remove("is-dark");
      section.style.backgroundColor = "";
      wake = () => {};
    };
    cleanupScene = disposeScene;

    try {
      const [THREE, { GLTFLoader }, { DRACOLoader }, { RoomEnvironment }] =
        await Promise.all([
          import("three"),
          import("three/addons/loaders/GLTFLoader.js"),
          import("three/addons/loaders/DRACOLoader.js"),
          import("three/addons/environments/RoomEnvironment.js"),
        ]);
      if (destroyed || failed || motionPreference.matches) return;

      renderer = new THREE.WebGLRenderer({
        alpha: true,
        antialias: true,
        powerPreference: "high-performance",
      });
      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.5));
      renderer.setClearColor(0x000000, 0);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.15;
      if ("transmissionResolutionScale" in renderer)
        renderer.transmissionResolutionScale = 0.6;
      renderer.domElement.setAttribute(
        "aria-label",
        "Interactive TRIMI assembly. Drag to rotate. Use arrow keys to rotate, or press R to reset.",
      );
      renderer.domElement.setAttribute("role", "img");
      renderer.domElement.tabIndex = 0;
      renderer.domElement.style.cssText =
        "display:block;width:100%;height:100%;position:absolute;inset:0;touch-action:pan-y;";
      container.append(renderer.domElement);

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(34, 1, 0.005, 100);
      const room = new RoomEnvironment();
      const pmrem = new THREE.PMREMGenerator(renderer);
      environment = pmrem.fromScene(room, 0.04);
      scene.environment = environment.texture;
      room.dispose();
      pmrem.dispose();
      const hemi = new THREE.HemisphereLight(0xffffff, 0xb2b4ba, 1.7);
      scene.add(hemi);
      const keyLight = new THREE.DirectionalLight(0xffffff, 2.2);
      keyLight.position.set(2, 5, 4);
      scene.add(keyLight);
      // Rim lights for the dark close-up stages.
      const rimA = new THREE.DirectionalLight(0xbcd4ff, 0);
      rimA.position.set(-4, 2, -3);
      const rimB = new THREE.DirectionalLight(0xffffff, 0);
      rimB.position.set(4, -1, -4);
      scene.add(rimA, rimB);

      decoder = new DRACOLoader();
      decoder.setDecoderPath(`${base}draco/`);
      decoder.setWorkerLimit(2);
      const loader = new GLTFLoader();
      loader.setDRACOLoader(decoder);
      const [gltf, meta] = await Promise.all([
        loader.loadAsync(`${base}data/cad/trimi_hardware.glb`),
        fetch(`${base}data/cad/trimi_hardware.json`).then((r) => {
          if (!r.ok) throw new Error(`trimi_hardware.json: ${r.status}`);
          return r.json();
        }),
      ]);
      if (destroyed || failed || motionPreference.matches) {
        disposeModel(gltf.scene);
        disposeScene();
        return;
      }
      model = gltf.scene;
      const sanitize = THREE.PropertyBinding.sanitizeNodeName;
      const node = (name) => model.getObjectByName(sanitize(name));
      const meshesOf = (object) => {
        const list = [];
        object?.traverse((n) => n.isMesh && list.push(n));
        return list;
      };
      // Blender world (x, y, z) to model space.
      const fromBlender = (v) => new THREE.Vector3(v[0], v[2], -v[1]);

      // ---- animation: one action per stage --------------------------------
      const mixer = new THREE.AnimationMixer(model);
      const clips = Object.fromEntries(gltf.animations.map((c) => [c.name, c]));
      const actions = {};
      for (const name of ["components", "tip", "finger", "thumb", ...(clips.tpu ? ["tpu"] : [])]) {
        if (!clips[name]) throw new Error(`missing animation ${name}`);
        const a = mixer.clipAction(clips[name]);
        a.play();
        a.paused = true;
        a.enabled = false;
        actions[name] = a;
      }
      // The loops were sampled every second frame, so they play at half the clip's rate.
      const loopSeconds = {
        finger: clips.finger.duration * 2,
        thumb: clips.thumb.duration * 2,
      };
      function setAction(name, weight, u) {
        const a = actions[name];
        a.enabled = weight > 0.001;
        a.setEffectiveWeight(weight);
        a.time = Math.min(u, 0.9999) * clips[name].duration;
      }

      // ---- scale and centre ------------------------------------------------
      model.updateMatrixWorld(true);
      const questParts = meta.quest.map(node).filter(Boolean);
      const cameraParts = meta.camera.map(node).filter(Boolean);
      const holoMesh = node(meta.hologram.mesh);
      const devices = [...questParts, ...cameraParts];
      const tpuParts = (meta.tpu ?? []).map(node).filter(Boolean);
      const excluded = new Set([...devices, ...tpuParts, holoMesh].filter(Boolean));
      function boundsOf(objects) {
        const box = new THREE.Box3();
        for (const o of objects) box.expandByObject(o);
        return box;
      }
      const assemblyParts = [];
      model.traverse((n) => {
        if (!n.isMesh) return;
        for (let p = n; p; p = p.parent) if (excluded.has(p)) return;
        assemblyParts.push(n);
      });
      const restBox = boundsOf(assemblyParts);
      const restSize = restBox.getSize(new THREE.Vector3());
      const scale = 2.2 / Math.max(restSize.x, restSize.y, restSize.z);
      const restCenter = restBox.getCenter(new THREE.Vector3());
      const assembly = new THREE.Group();
      assembly.scale.setScalar(scale);
      model.position.copy(restCenter).negate();
      assembly.add(model);
      scene.add(assembly);
      assembly.updateMatrixWorld(true);

      // ---- materials -------------------------------------------------------
      // Palm cover: slightly frosted clear resin (Formlabs Clear).
      const resin = new THREE.MeshPhysicalMaterial({
        color: 0xffffff,
        metalness: 0,
        roughness: 0.2,
        transmission: 1,
        thickness: 0.0025,
        ior: 1.5,
        attenuationColor: new THREE.Color(0.94, 0.97, 0.96),
        attenuationDistance: 0.04,
        clearcoat: 0.5,
        clearcoatRoughness: 0.2,
        specularIntensity: 1,
      });
      disposables.push(resin);
      const cover = node("cover_new");
      meshesOf(cover).forEach((m) => {
        m.material = resin;
      });
      // Silicone (Dragon Skin) pads and the semi finger cot's fingerprint side: translucent.
      const silicone = new THREE.MeshStandardMaterial({
        color: new THREE.Color(0.5, 0.52, 0.49),
        roughness: 0.42,
        metalness: 0,
        transparent: true,
        opacity: 0.8,
      });
      disposables.push(silicone);
      model.traverse((n) => {
        if (n.isMesh && n.material?.name?.startsWith("DragonSkin")) n.material = silicone;
      });
      // TPU hand: a soft, warm mid tone, set apart from the white PLA and the dark servos. Its
      // joint inserts show through the skin; they take the same colour, so the hand reads as one.
      const tpuSkin = new THREE.MeshStandardMaterial({ color: new THREE.Color(0.36, 0.25, 0.18), roughness: 0.72, metalness: 0 });
      disposables.push(tpuSkin);
      model.traverse((n) => {
        if (n.isMesh && (n.material?.name === "TPU" || n.material?.name === "TPU insert")) n.material = tpuSkin;
      });
      // Tactile sensors: a faint film normally; the middle one shows its printed
      // circuit (the .blend's texture) while the fingertip is apart.
      const sensorFilm = new THREE.MeshStandardMaterial({
        color: 0xd08a3c,
        roughness: 0.4,
        metalness: 0,
        transparent: true,
        opacity: 0.2,
        depthWrite: false,
        side: THREE.DoubleSide,
      });
      disposables.push(sensorFilm);
      let sensorPrint = null;
      const sensorMeshes = [];
      model.traverse((n) => n.isMesh && /^TactileSensor/.test(n.name) && sensorMeshes.push(n));
      // Collected first: the print overlay added below is a child mesh too.
      sensorMeshes.forEach((n) => {
        const map = n.material?.map;
        n.material = sensorFilm;
        n.renderOrder = 2;
        if (map && !sensorPrint) {
          // Its own film, faded by opacity: hiding this mesh would hide the print too.
          const film = sensorFilm.clone();
          n.material = film;
          const mat = new THREE.MeshStandardMaterial({
            map,
            roughness: 0.38,
            metalness: 0,
            transparent: true,
            opacity: 0,
            side: THREE.DoubleSide,
          });
          const overlayMesh = new THREE.Mesh(n.geometry, mat);
          overlayMesh.renderOrder = 3;
          overlayMesh.visible = false;
          n.add(overlayMesh);
          sensorPrint = { mesh: overlayMesh, mat, film, filmOpacity: film.opacity };
          disposables.push(mat, map, film);
        }
      });

      // Status LEDs on the U2D2 glow as in the .blend.
      const glowTexture = (() => {
        const c = document.createElement("canvas");
        c.width = c.height = 64;
        const g = c.getContext("2d");
        const grad = g.createRadialGradient(32, 32, 0, 32, 32, 32);
        grad.addColorStop(0, "rgba(255,255,255,1)");
        grad.addColorStop(0.25, "rgba(255,255,255,0.55)");
        grad.addColorStop(1, "rgba(255,255,255,0)");
        g.fillStyle = grad;
        g.fillRect(0, 0, 64, 64);
        const tex = new THREE.CanvasTexture(c);
        tex.colorSpace = THREE.SRGBColorSpace;
        return tex;
      })();
      disposables.push(glowTexture);
      const leds = [];
      for (const def of LEDS) {
        const led = node(def.node);
        if (!led) continue;
        const color = new THREE.Color(def.color);
        const mat = new THREE.MeshBasicMaterial({ color, toneMapped: false });
        meshesOf(led).forEach((m) => (m.material = mat));
        const lens = node(`${def.node}_lens`);
        meshesOf(lens).forEach((m) => {
          m.material = new THREE.MeshBasicMaterial({
            color: color.clone().lerp(new THREE.Color(1, 1, 1), 0.35),
            toneMapped: false,
            transparent: true,
            opacity: 0.85,
          });
        });
        const sprite = new THREE.Sprite(
          new THREE.SpriteMaterial({
            map: glowTexture,
            color,
            transparent: true,
            depthTest: false,
            depthWrite: false,
            toneMapped: false,
          }),
        );
        sprite.renderOrder = 20;
        const box = new THREE.Box3().setFromObject(led);
        sprite.position.copy(box.getCenter(new THREE.Vector3()));
        sprite.scale.setScalar(0.006 * scale);
        scene.add(sprite);
        leds.push({ def, mat, color, sprite, led, base: color.clone() });
      }
      const ledUp = new THREE.Vector3(0, 1, 0);

      // Hologram hand: fresnel glow with scan lines, as the .blend's Hologram material.
      let holoMat = null;
      if (holoMesh) {
        holoMat = new THREE.ShaderMaterial({
          uniforms: {
            uColor: { value: new THREE.Color(0.03, 0.32, 1.0) },
            uOpacity: { value: 0 },
            uTime: { value: 0 },
            uModelInverse: { value: new THREE.Matrix4() },
          },
          vertexShader: `
            #include <common>
            #include <skinning_pars_vertex>
            uniform mat4 uModelInverse;
            varying vec3 vNormalV;
            varying vec3 vViewDir;
            varying vec3 vModelPos;
            void main() {
              #include <skinbase_vertex>
              #include <beginnormal_vertex>
              #include <skinnormal_vertex>
              #include <begin_vertex>
              #include <skinning_vertex>
              vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
              vNormalV = normalize(normalMatrix * objectNormal);
              vViewDir = normalize(-mvPosition.xyz);
              vModelPos = (uModelInverse * modelMatrix * vec4(transformed, 1.0)).xyz;
              gl_Position = projectionMatrix * mvPosition;
            }`,
          // As the .blend's Hologram material: facing-ratio glow, scan lines
          // 2 mm apart, faded out towards the wrist (Blender y 0.10 to 0.18 m).
          fragmentShader: `
            uniform vec3 uColor;
            uniform float uOpacity;
            uniform float uTime;
            varying vec3 vNormalV;
            varying vec3 vViewDir;
            varying vec3 vModelPos;
            void main() {
              float facing = abs(dot(normalize(vNormalV), normalize(vViewDir)));
              float fres = pow(1.0 - facing, 1.6);
              float scan = smoothstep(0.6, 1.0, 0.5 + 0.5 * sin((vModelPos.y + uTime * 0.004) * 2991.993));
              float wrist = 1.0 - smoothstep(0.10, 0.18, -vModelPos.z);
              float a = (fres * 0.6 + 0.08 + scan * 0.1) * wrist * uOpacity;
              vec3 col = uColor * (0.5 + fres * 1.6) * 0.32;
              gl_FragColor = vec4(col * a, a);
              #include <colorspace_fragment>
            }`,
          toneMapped: false,
          transparent: true,
          depthWrite: false,
          side: THREE.DoubleSide,
          blending: THREE.CustomBlending,
          blendSrc: THREE.OneFactor,
          blendDst: THREE.OneFactor,
        });
        disposables.push(holoMat);
        meshesOf(holoMesh).forEach((m) => {
          m.material = holoMat;
          m.frustumCulled = false;
          m.renderOrder = 10;
        });
        holoMat.uniforms.uModelInverse.value.copy(model.matrixWorld).invert();
        holoMesh.visible = false;
      }

      // Per-part opacity, for parts that fade in a stage. Materials are cloned on first use.
      const fades = new Map();
      function fader(mesh) {
        let f = fades.get(mesh);
        if (!f) {
          const original = mesh.material;
          const mat = original.clone();
          mesh.material = mat;
          f = { mesh, mat, original, value: 1 };
          fades.set(mesh, f);
        }
        return f;
      }
      function setOpacity(mesh, value, floor = 0) {
        const f = fader(mesh);
        const v = Math.max(floor, value);
        if (v === f.value) return;
        f.value = v;
        if (f.mat.transmission > 0) {
          mesh.visible = v > 0.5;
          return;
        }
        mesh.visible = v > 0.005;
        const fading = v < 0.999;
        // Materials that are see-through anyway (silicone, sensor film) keep blending.
        const transparent = fading || f.original.transparent;
        if (f.mat.transparent !== transparent) {
          f.mat.transparent = transparent;
          f.mat.needsUpdate = true;
        }
        f.mat.opacity = (fading ? v : 1) * (f.original.opacity ?? 1);
        f.mat.depthWrite = fading ? false : f.original.depthWrite;
      }
      // LEDs are switched with their glow instead of fading.
      const ledMeshes = new Set(
        LEDS.flatMap((d) => [...meshesOf(node(d.node)), ...meshesOf(node(`${d.node}_lens`))]),
      );
      const focusFade = meta.fingerHidden
        .map(node)
        .filter(Boolean)
        .flatMap(meshesOf)
        .filter((m) => !ledMeshes.has(m));
      const ballCovers = BALL_COVERS.map(node).filter(Boolean).flatMap(meshesOf);

      // ---- joint graphics -----------------------------------------------------
      const overlayGroup = new THREE.Group();
      scene.add(overlayGroup);
      const accentMat = (opacity = 1) =>
        new THREE.MeshBasicMaterial({
          color: ACCENT,
          transparent: true,
          opacity,
          depthWrite: false,
          toneMapped: false,
        });
      const ringMats = [];
      /** Adds a child to `parentNode` at a Blender-world point, keeping it fixed to that part. */
      function attach(parentNode, object, positionB) {
        const host = parentNode || model;
        host.add(object);
        const p = fromBlender(positionB);
        // Blender world -> model space -> host local.
        const worldP = model.localToWorld(p.clone());
        host.worldToLocal(worldP);
        object.position.copy(worldP);
        return object;
      }
      function alignAxis(object, host, axisB) {
        // Orient the object's local +Y along a Blender-world axis, expressed in host space.
        const a = fromBlender(axisB).normalize();
        const hostQ = new THREE.Quaternion();
        (host || model).getWorldQuaternion(hostQ);
        const modelQ = new THREE.Quaternion();
        model.getWorldQuaternion(modelQ);
        a.applyQuaternion(modelQ).applyQuaternion(hostQ.invert());
        object.quaternion.setFromUnitVectors(new THREE.Vector3(0, 1, 0), a);
      }
      const jointAnchors = {};
      const rings = meta.rings;
      const fingerAxis = meta.joints.GLOVE_middle_MCP.axis;
      function ringSet(prefix, hostName) {
        const host = hostName ? node(hostName) : null;
        const ring = rings[`ROT_middle_${prefix}_ring`];
        const pitch = rings[`ROT_middle_${prefix}_pitch`];
        const group = new THREE.Group();
        attach(host, group, ring.center);
        alignAxis(group, host, fingerAxis);
        const m1 = accentMat();
        const m2 = new THREE.LineBasicMaterial({
          color: ACCENT,
          transparent: true,
          opacity: 0.9,
          depthWrite: false,
          toneMapped: false,
        });
        const torus = new THREE.Mesh(
          new THREE.TorusGeometry(ring.radius, 0.00035, 8, 96),
          m1,
        );
        torus.rotation.x = Math.PI / 2;
        const dot = new THREE.Mesh(new THREE.SphereGeometry(0.0016, 20, 12), m1);
        const circle = new THREE.LineLoop(
          new THREE.BufferGeometry().setFromPoints(
            Array.from({ length: 160 }, (_, i) => {
              const a = (i / 160) * Math.PI * 2;
              return new THREE.Vector3(
                Math.cos(a) * pitch.radius,
                0,
                Math.sin(a) * pitch.radius,
              );
            }),
          ),
          m2,
        );
        group.add(torus, dot, circle);
        group.traverse((n) => (n.renderOrder = 12));
        ringMats.push(m1, m2);
        disposables.push(torus.geometry, dot.geometry, circle.geometry, m1, m2);
        jointAnchors[`${prefix.toLowerCase()}Ring`] = {
          object: group,
          local: new THREE.Vector3(ring.radius * 0.7, 0, -ring.radius * 0.7),
        };
        group.visible = false;
        return group;
      }
      const ringGroups = [ringSet("MCP", null), ringSet("PIP", "GLOVE_middle_MCP")];

      function axisCylinder(jointName, host, positionB, axisB, length, radius) {
        const group = new THREE.Group();
        attach(host, group, positionB);
        alignAxis(group, host, axisB);
        const glass = new THREE.MeshStandardMaterial({
          color: ACCENT,
          emissive: ACCENT,
          emissiveIntensity: 0.6,
          roughness: 0.35,
          metalness: 0,
          transparent: true,
          opacity: AXIS_OPACITY,
          depthWrite: false,
        });
        const cyl = new THREE.Mesh(
          new THREE.CylinderGeometry(radius, radius, length, 40, 1, false),
          glass,
        );
        const lineMat = new THREE.LineDashedMaterial({
          color: ACCENT,
          dashSize: 0.002,
          gapSize: 0.0015,
          transparent: true,
          depthWrite: false,
          toneMapped: false,
        });
        const line = new THREE.Line(
          new THREE.BufferGeometry().setFromPoints([
            new THREE.Vector3(0, -length * 1.1, 0),
            new THREE.Vector3(0, length * 1.1, 0),
          ]),
          lineMat,
        );
        line.computeLineDistances();
        group.add(cyl, line);
        group.traverse((n) => (n.renderOrder = 11));
        disposables.push(cyl.geometry, line.geometry, glass, lineMat);
        jointAnchors[jointName] = {
          object: group,
          local: new THREE.Vector3(0, length * 0.5, 0),
        };
        group.visible = false;
        return { group, mats: [glass, lineMat] };
      }
      const abad = meta.joints.middle_ABAD;
      const abadAxis = axisCylinder("abad", null, abad.pivot, abad.axis, 0.034, 0.0042);
      const thumbAxes = ["GLOVE_thumb_B1", "GLOVE_thumb_B2", "GLOVE_thumb_MCP", "GLOVE_thumb_IP"].map(
        (name) => {
          const j = meta.joints[name];
          return axisCylinder(name, node(name), j.pivot, j.axis, 0.032, 0.0042);
        },
      );

      // ---- fingertip options: the tactile finger cot and the semi finger cot ------
      // Both sit on the middle finger. The fingertip stage shows one apart, closes
      // it, swaps to the other while closed, and opens that one.
      const sensorMesh = sensorPrint?.mesh.parent ?? null;
      const meshSet = (objects) =>
        [...new Set(objects.flatMap(meshesOf))].filter(
          (m) => m !== sensorMesh && m !== sensorPrint?.mesh,
        );
      const tactileMeshes = meshSet(Object.values(meta.tactileCot ?? {}).map(node).filter(Boolean));
      const semiMeshes = meshSet(Object.values(meta.semiCot ?? {}).map(node).filter(Boolean));
      semiMeshes.forEach((m) => (m.visible = false));
      /**
       * Two options taking turns: one is shown (open), closes, they swap while
       * closed, the other opens. at() returns open (0..1) and second (0 first
       * option .. 1 second option); pick() jumps to an option's hold.
       */
      function optionCycle(period, forcedParam) {
        let clock = null;
        return {
          at(time, amount) {
            if (amount > 0.98 && clock === null) clock = time;
            if (amount < 0.02) clock = null;
            const forced = params.has(forcedParam) ? Number(params.get(forcedParam)) : null;
            // Starts in the first option's hold, since scrolling has just shown it.
            const c = forced ?? (clock === null ? 0.08 : ((time - clock) / period + 0.08) % 1);
            const second = c >= 0.5;
            const half = second ? (c - 0.5) * 2 : c * 2;
            const open = smooth(0, 0.14, half) * (1 - smooth(0.76, 0.9, half));
            const swap = smooth(0.9, 1, half);
            return { open, second: second ? 1 - swap : swap };
          },
          pick(index, time) {
            clock = time - index * 0.5 * period;
          },
        };
      }
      const cotCycle = optionCycle(COT_PERIOD, "hwcot");

      // ---- devices (Quest controller and wrist camera) -------------------------
      // Parts inside another device part (the Quest's menu button, B and logo) ride along with it.
      const deviceSet = new Set(devices);
      const nested = (o) => {
        for (let p = o.parent; p; p = p.parent) if (deviceSet.has(p)) return true;
        return false;
      };
      const deviceRest = devices.filter((o) => !nested(o)).map((o) => ({ o, y: o.position.clone() }));
      const tpuRest = tpuParts.map((o) => ({ o, y: o.position.clone() }));
      const tpuMeshes = tpuParts.flatMap(meshesOf);
      const lift = new THREE.Vector3();
      /** Moves a part by a model-space offset (model units, i.e. metres), from its rest position. */
      function offsetPart(o, rest, x, y, z) {
        lift.set(x, y, z);
        const parentQ = new THREE.Quaternion();
        o.parent.getWorldQuaternion(parentQ);
        const modelQ = new THREE.Quaternion();
        model.getWorldQuaternion(modelQ);
        lift.applyQuaternion(modelQ).applyQuaternion(parentQ.invert());
        const parentS = new THREE.Vector3();
        o.parent.getWorldScale(parentS);
        lift.multiplyScalar(scale / parentS.x);
        o.position.copy(rest).add(lift);
      }
      function placeDevices(questAmount, cameraAmount = questAmount) {
        const q = smooth(0, 0.7, questAmount);
        const c = smooth(0.3, 1, cameraAmount);
        for (const { o, y } of deviceRest) {
          const isQuest = questParts.includes(o);
          const v = isQuest ? q : c;
          o.visible = v > 0.001;
          // Slide in along model up (+Y) from above for the Quest, from below for the camera.
          offsetPart(o, y, 0, (isQuest ? 1 : -1) * 0.07 * (1 - v) ** 2, 0);
        }
      }
      /** The TPU hand slides in from the wrist side (Blender +y is model -z) and fades in. */
      function placeTpu(amount) {
        const v = smooth(0, 1, amount);
        for (const { o, y } of tpuRest) offsetPart(o, y, 0, 0, -0.06 * (1 - v) ** 2);
        for (const m of tpuMeshes) setOpacity(m, smooth(0, 0.5, amount));
      }
      placeDevices(0);
      tpuMeshes.forEach((m) => (m.visible = false));

      // ---- camera shots --------------------------------------------------------
      function fitRadius(box) {
        return box.getSize(new THREE.Vector3()).length() / 2;
      }
      function worldBox(objects) {
        model.updateMatrixWorld(true);
        return boundsOf(objects);
      }
      setAction("components", 1, 1);
      mixer.update(0);
      const explodedBox = worldBox(assemblyParts);
      setAction("components", 0, 0);
      mixer.update(0);
      model.updateMatrixWorld(true);
      const restWorld = worldBox(assemblyParts);
      const middleFinger = [
        "_mcp_link_r_v2_right",
        "_mcp_link_m_v2_right",
        "_pip_link_r_v2_right",
        "Part 5",
        "Part 1",
        "DC15_A01_CASE_M_DUMMY.001",
      ]
        .map(node)
        .filter(Boolean);
      const fingerBox = worldBox(middleFinger);
      const thumbBox = worldBox(
        [
          "DC15_A01_CASE_M_DUMMY.022",
          "DC15_A01_CASE_M_DUMMY.024",
          "DC15_A01_CASE_M_DUMMY.025",
          "Part 4.003",
          "Part 5.006",
          "thumb_fingercot",
        ]
          .map(node)
          .filter(Boolean),
      );
      setAction("tip", 1, 1);
      mixer.update(0);
      const tipBox = worldBox(["Part 5", "Part 1", "TactileSensor_middle"].map(node).filter(Boolean));
      setAction("tip", 0, 0);
      mixer.update(0);
      devices.forEach((o) => (o.visible = true));
      placeDevices(1);
      const fullBox = worldBox([...assemblyParts, ...devices]);
      placeDevices(0);
      // Finger close-up: both joints' concentric circles (pitch radius around each centre).
      const ringBox = new THREE.Box3();
      for (const key of ["ROT_middle_MCP_pitch", "ROT_middle_PIP_pitch"]) {
        const c = model.localToWorld(fromBlender(rings[key].center));
        const r = rings[key].radius * scale;
        ringBox.expandByPoint(c.clone().addScalar(r)).expandByPoint(c.clone().addScalar(-r));
      }
      ringBox.union(fingerBox);
      const center = (box) => box.getCenter(new THREE.Vector3());
      const shots = [
        // overview: as before, three-quarter view from the front right
        { target: center(restWorld), yaw: 0.5, pitch: 0.31, radius: fitRadius(restWorld) * 0.72, drift: 1, box: restWorld },
        { target: center(explodedBox), yaw: 0.85, pitch: 0.42, radius: fitRadius(explodedBox) * 0.84, drift: 0.6, box: explodedBox },
        // finger: side close-up from the index side, like the film's rotation-centre shot
        { target: center(ringBox).add(new THREE.Vector3(0, -0.022 * scale, 0.004 * scale)), yaw: Math.PI / 2, pitch: 0.05, radius: fitRadius(ringBox) * 0.92, drift: 0.12, box: ringBox },
        // thumb: from the thumb side, slightly below, so the opposition reads
        { target: center(thumbBox).lerp(center(restWorld), 0.15), yaw: 1.15, pitch: -0.16, radius: fitRadius(thumbBox) * 0.95, drift: 0.15, box: thumbBox },
        // fingertip: the middle fingertip apart, everything else assembled
        { target: center(tipBox), yaw: 1.4, pitch: 0.55, radius: fitRadius(tipBox) * 1.45, drift: 0.12, box: tipBox },
        // modular: the whole device with the Quest controller and wrist camera
        { target: center(fullBox), yaw: -0.65, pitch: 0.24, radius: fitRadius(fullBox) * 0.7, drift: 0.8, box: fullBox },
        // TPU hand: from below and to the side, where the hand under the device shows
        { target: center(fullBox).add(new THREE.Vector3(0, -0.02 * scale, 0)), yaw: -1.0, pitch: -0.28, radius: fitRadius(fullBox) * 0.7, drift: 0.5, box: fullBox },
      ];
      const labelStage = { components: 1, finger: 2, thumb: 3, tip: 4, cot: 4, camera: 5, quest: 5, tpu: 6 };

      // ---- the tactile sensor unrolls flat while the tactile finger cot is apart ----
      // Its UV layout is the flat cut pattern (the printed-circuit image), so the flat
      // sheet is built from the UVs at true size: metres per UV unit along u and v come
      // from the edge lengths, since the flex sensor is bent from a flat sheet. The sheet
      // lies parallel to the palm: its flat palm-side part stays where it is and the part
      // that wraps the fingertip opens out into the same plane, so closing the cot rolls
      // it straight back onto the cap.
      let sensorFlat = false;
      if (sensorPrint && sensorMesh?.geometry.attributes.uv) {
        const g = sensorMesh.geometry;
        model.updateMatrixWorld(true);
        const toModel = new THREE.Matrix4().copy(model.matrixWorld).invert().multiply(sensorMesh.matrixWorld);
        const toLocal = toModel.clone().invert();
        const pos = g.attributes.position;
        const uv = g.attributes.uv;
        const P = Array.from({ length: pos.count }, (_, i) => new THREE.Vector3().fromBufferAttribute(pos, i).applyMatrix4(toModel));
        const idx = g.index?.array;
        const triCount = idx ? idx.length / 3 : pos.count / 3;
        let s11 = 0, s12 = 0, s22 = 0, r1 = 0, r2 = 0;
        for (let t = 0; t < triCount; t++) {
          for (let e = 0; e < 3; e++) {
            const a = idx ? idx[3 * t + e] : 3 * t + e;
            const b = idx ? idx[3 * t + ((e + 1) % 3)] : 3 * t + ((e + 1) % 3);
            const du2 = (uv.getX(a) - uv.getX(b)) ** 2;
            const dv2 = (uv.getY(a) - uv.getY(b)) ** 2;
            const d2 = P[a].distanceToSquared(P[b]);
            s11 += du2 * du2;
            s12 += du2 * dv2;
            s22 += dv2 * dv2;
            r1 += du2 * d2;
            r2 += dv2 * d2;
          }
        }
        const det = s11 * s22 - s12 * s12;
        const su = Math.sqrt(Math.max(1e-12, (r1 * s22 - r2 * s12) / det));
        const sv = Math.sqrt(Math.max(1e-12, (s11 * r2 - s12 * r1) / det));
        // The middle cap sits square to the model at rest: back of the hand +y, fingertip +z.
        const n = new THREE.Vector3(0, 1, 0);
        const ax = new THREE.Vector3(0, 0, 1);
        const lat = new THREE.Vector3(1, 0, 0);
        // the palm-side part: faces within 30 degrees of the palm plane's normal
        const nm = new THREE.Matrix3().getNormalMatrix(toModel);
        const nrm = g.attributes.normal;
        const flatPart = [];
        const tmpN = new THREE.Vector3();
        for (let i = 0; i < pos.count; i++) {
          tmpN.fromBufferAttribute(nrm, i).applyMatrix3(nm).normalize();
          if (Math.abs(tmpN.y) > Math.cos(THREE.MathUtils.degToRad(30))) flatPart.push(i);
        }
        const part = flatPart.length > 40 ? flatPart : [...Array(pos.count).keys()];
        // 2D rigid fit (rotation, or rotation with a mirror) of the pattern onto that part,
        // in the palm plane
        const L = (i) => [uv.getX(i) * su, uv.getY(i) * sv];
        const Q = (i) => [P[i].dot(ax), P[i].dot(lat)];
        const mean = (f, mirror) => {
          let x = 0, y = 0;
          for (const i of part) {
            const p = f(i);
            x += p[0];
            y += mirror ? -p[1] : p[1];
          }
          return [x / part.length, y / part.length];
        };
        const qm = mean(Q, false);
        let fit = null;
        for (const mirror of [false, true]) {
          const lm = mean(L, mirror);
          let sc = 0, ss = 0;
          for (const i of part) {
            const l = L(i);
            const lx = l[0] - lm[0], ly = (mirror ? -l[1] : l[1]) - lm[1];
            const q = Q(i);
            const qx = q[0] - qm[0], qy = q[1] - qm[1];
            sc += lx * qx + ly * qy;
            ss += lx * qy - ly * qx;
          }
          const th = Math.atan2(ss, sc);
          let err = 0;
          for (const i of part) {
            const l = L(i);
            const lx = l[0] - lm[0], ly = (mirror ? -l[1] : l[1]) - lm[1];
            const q = Q(i);
            const dx = Math.cos(th) * lx - Math.sin(th) * ly - (q[0] - qm[0]);
            const dy = Math.sin(th) * lx + Math.cos(th) * ly - (q[1] - qm[1]);
            err += dx * dx + dy * dy;
          }
          if (!fit || err < fit.err) fit = { mirror, th, lm, err };
        }
        let h = 0;
        for (const i of part) h += P[i].dot(n);
        h /= part.length;
        const nLocal = n.clone().transformDirection(toLocal);
        const flat = new Float32Array(pos.count * 3);
        const normals = new Float32Array(pos.count * 3);
        const v = new THREE.Vector3();
        for (let i = 0; i < pos.count; i++) {
          const l = L(i);
          const lx = l[0] - fit.lm[0], ly = (fit.mirror ? -l[1] : l[1]) - fit.lm[1];
          const a = Math.cos(fit.th) * lx - Math.sin(fit.th) * ly + qm[0];
          const b = Math.sin(fit.th) * lx + Math.cos(fit.th) * ly + qm[1];
          v.set(0, 0, 0).addScaledVector(ax, a).addScaledVector(lat, b).addScaledVector(n, h).applyMatrix4(toLocal);
          flat.set([v.x, v.y, v.z], 3 * i);
          normals.set([nLocal.x, nLocal.y, nLocal.z], 3 * i);
        }
        g.morphAttributes.position = [new THREE.Float32BufferAttribute(flat, 3)];
        g.morphAttributes.normal = [new THREE.Float32BufferAttribute(normals, 3)];
        for (const m of [sensorMesh, sensorPrint.mesh]) {
          m.updateMorphTargets();
          m.morphTargetInfluences[0] = 0;
          m.frustumCulled = false;
        }
        sensorFlat = true;
      }

      // ---- labels ----------------------------------------------------------------
      const svgNS = "http://www.w3.org/2000/svg";
      const svg = document.createElementNS(svgNS, "svg");
      svg.setAttribute("class", "hw-leaders");
      svg.setAttribute("aria-hidden", "true");
      overlay?.replaceChildren(svg);
      /** Two buttons above the stage: the shown option is filled, a tap switches to the other. */
      function optionSwitch(label, options, onPick) {
        const el = document.createElement("div");
        el.className = "hw-switch";
        el.setAttribute("role", "group");
        el.setAttribute("aria-label", label);
        el.hidden = true;
        const buttons = options.map((opt, i) => {
          const button = document.createElement("button");
          button.type = "button";
          button.innerHTML = `<strong></strong>${opt.sub ? "<span></span>" : ""}`;
          button.querySelector("strong").textContent = opt.title;
          if (opt.sub) button.querySelector("span").textContent = opt.sub;
          button.setAttribute("aria-pressed", "false");
          button.addEventListener(
            "click",
            () => {
              onPick(i);
              lastInteraction = performance.now();
              wake();
            },
            { signal: sceneListeners.signal },
          );
          el.append(button);
          return button;
        });
        overlay?.append(el);
        let active = -1;
        return {
          update(amount, second) {
            el.hidden = amount < 0.01;
            if (el.hidden) return;
            el.style.opacity = String(amount);
            el.style.pointerEvents = amount > 0.5 ? "auto" : "none";
            const now = second > 0.5 ? 1 : 0;
            if (now === active) return;
            active = now;
            buttons.forEach((b, i) => {
              b.classList.toggle("on", i === now);
              b.setAttribute("aria-pressed", String(i === now));
            });
          },
        };
      }
      let lastTime = 0;
      let cotOpen = 1;
      let cotSemi = 0;
      const cotSwitch = semiMeshes.length
        ? optionSwitch("Finger cot", COT_OPTIONS, (i) => cotCycle.pick(i, lastTime))
        : null;
      const labelSets = {};
      for (const [group, defs] of Object.entries(LABELS)) {
        labelSets[group] = defs
          .map((def) => {
            let object;
            let local;
            if (def.joint) {
              const a = jointAnchors[def.joint];
              if (!a) return null;
              object = a.object;
              local = a.local.clone();
            } else {
              object = node(def.node);
              if (!object) return null;
              object.updateWorldMatrix(true, true);
              const c = new THREE.Box3()
                .setFromObject(object)
                .getCenter(new THREE.Vector3());
              local = object.worldToLocal(c);
            }
            const el = document.createElement("div");
            el.className = "hw-label";
            el.innerHTML = `<strong></strong>${def.sub ? "<span></span>" : ""}`;
            el.querySelector("strong").textContent = def.title;
            if (def.sub) el.querySelector("span").textContent = def.sub;
            overlay?.append(el);
            const path = document.createElementNS(svgNS, "path");
            if (def.dashed) path.setAttribute("stroke-dasharray", "3 3");
            const dotEl = document.createElementNS(svgNS, "circle");
            dotEl.setAttribute("r", "3");
            svg.append(path, dotEl);
            return { def, object, local, el, path, dot: dotEl, x: 0, y: 0 };
          })
          .filter(Boolean);
      }
      const projected = new THREE.Vector3();
      const corner = new THREE.Vector3();
      /** Screen rectangle of a world box, in canvas pixels. */
      function screenRect(box, w, h) {
        const r = { minX: Infinity, maxX: -Infinity, minY: Infinity, maxY: -Infinity };
        for (let i = 0; i < 8; i++) {
          corner.set(
            i & 1 ? box.max.x : box.min.x,
            i & 2 ? box.max.y : box.min.y,
            i & 4 ? box.max.z : box.min.z,
          );
          corner.project(camera);
          const x = (corner.x * 0.5 + 0.5) * w;
          const y = (-corner.y * 0.5 + 0.5) * h;
          r.minX = Math.min(r.minX, x);
          r.maxX = Math.max(r.maxX, x);
          r.minY = Math.min(r.minY, y);
          r.maxY = Math.max(r.maxY, y);
        }
        return r;
      }
      function layoutLabels(state) {
        if (!overlay) return;
        const w = container.clientWidth;
        const h = container.clientHeight;
        svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
        const compact = w < 640;
        for (const [group, items] of Object.entries(labelSets)) {
          const opacity = state.labels[group] || 0;
          const show = opacity > 0.01;
          const placed = { left: [], right: [] };
          // Labels sit in columns just outside the stage's subject.
          const rect = show ? screenRect(shots[labelStage[group]].box, w, h) : null;
          for (const it of items) {
            it.el.style.opacity = String(opacity);
            it.path.style.opacity = String(opacity);
            it.dot.style.opacity = String(opacity);
            it.el.hidden = !show;
            it.path.style.display = show ? "" : "none";
            it.dot.style.display = show ? "" : "none";
            if (!show) continue;
            projected.copy(it.local);
            it.object.localToWorld(projected);
            projected.project(camera);
            const visible = projected.z < 1 && Math.abs(projected.x) < 1.2 && Math.abs(projected.y) < 1.2;
            if (!visible) {
              it.el.hidden = true;
              it.path.style.display = "none";
              it.dot.style.display = "none";
              continue;
            }
            it.ax = (projected.x * 0.5 + 0.5) * w;
            it.ay = (-projected.y * 0.5 + 0.5) * h;
            const mid = (rect.minX + rect.maxX) / 2;
            const side = it.def.side || (it.ax < mid ? "left" : "right");
            it.side = side;
            placed[side].push(it);
          }
          for (const side of ["left", "right"]) {
            const list = placed[side].sort((a, b) => a.ay - b.ay);
            const gap = compact ? 30 : 40;
            const reach = compact ? 18 : 44;
            const margin = compact ? 6 : 14;
            let prev = -Infinity;
            for (const it of list) {
              let y = Math.max(it.ay - (compact ? 10 : 18), prev + gap);
              y = Math.min(Math.max(y, 18), h - 18);
              prev = y;
              const width = it.el.offsetWidth || 120;
              let x =
                side === "left"
                  ? Math.min(it.ax - reach, rect.minX - reach)
                  : Math.max(it.ax + reach, rect.maxX + reach);
              x = side === "left" ? Math.max(margin + width, x) : Math.min(w - margin - width, x);
              it.x = x;
              it.y = y;
            }
            // Re-resolve from the bottom so the stack stays on screen.
            let next = Infinity;
            for (let i = list.length - 1; i >= 0; i--) {
              const it = list[i];
              it.y = Math.min(it.y, next - gap);
              next = it.y;
            }
            for (const it of list) {
              const dir = side === "left" ? -1 : 1;
              const elbowX = it.x - dir * (compact ? 8 : 14);
              it.path.setAttribute(
                "d",
                `M${it.ax.toFixed(1)},${it.ay.toFixed(1)} L${elbowX.toFixed(1)},${it.y.toFixed(1)} L${it.x.toFixed(1)},${it.y.toFixed(1)}`,
              );
              it.dot.setAttribute("cx", it.ax.toFixed(1));
              it.dot.setAttribute("cy", it.ay.toFixed(1));
              it.el.dataset.side = side;
              it.el.style.transform = `translate(${it.x.toFixed(1)}px, ${it.y.toFixed(1)}px) translate(${side === "left" ? "-100%" : "0"}, -50%)`;
            }
          }
        }
      }

      // ---- interaction -------------------------------------------------------------
      let userYaw = 0;
      let userPitch = 0;
      let velYaw = 0;
      let dragging = false;
      let lastX = 0;
      let lastY = 0;
      let idleYaw = 0;
      const canvas = renderer.domElement;
      canvas.addEventListener(
        "pointerdown",
        (event) => {
          dragging = true;
          lastX = event.clientX;
          lastY = event.clientY;
          velYaw = 0;
          lastInteraction = performance.now();
          canvas.setPointerCapture?.(event.pointerId);
          wake();
        },
        { signal: sceneListeners.signal },
      );
      canvas.addEventListener(
        "pointermove",
        (event) => {
          if (!dragging) return;
          const dx = event.clientX - lastX;
          const dy = event.clientY - lastY;
          lastX = event.clientX;
          lastY = event.clientY;
          const k = 5 / Math.max(300, container.clientWidth);
          velYaw = -dx * k;
          userYaw += velYaw;
          if (event.pointerType !== "touch")
            userPitch = Math.max(-0.9, Math.min(0.9, userPitch + dy * k));
          lastInteraction = performance.now();
          wake();
        },
        { signal: sceneListeners.signal },
      );
      const endDrag = () => {
        dragging = false;
        lastInteraction = performance.now();
        wake();
      };
      canvas.addEventListener("pointerup", endDrag, { signal: sceneListeners.signal });
      canvas.addEventListener("pointercancel", endDrag, { signal: sceneListeners.signal });

      function resetCamera() {
        userYaw = 0;
        userPitch = 0;
        velYaw = 0;
        idleYaw = 0;
        lastInteraction = performance.now();
        wake();
      }

      function fitDistance(radius) {
        const aspect = Math.max(
          0.1,
          container.clientWidth / Math.max(1, container.clientHeight),
        );
        const halfFov = THREE.MathUtils.degToRad(camera.fov / 2);
        const limitingFov = Math.min(halfFov, Math.atan(Math.tan(halfFov) * aspect));
        return (radius / Math.sin(limitingFov)) * 1.02;
      }

      function resize() {
        const width = container.clientWidth;
        const height = container.clientHeight;
        if (!width || !height) return;
        renderer.setSize(width, height, false);
        camera.aspect = width / height;
        camera.updateProjectionMatrix();
        wake();
      }

      // ---- frame -----------------------------------------------------------------
      const target = new THREE.Vector3();
      const camOffset = new THREE.Vector3();
      const ledWorld = new THREE.Vector3();
      const ledBox = new THREE.Box3();
      const viewDir = new THREE.Vector3();
      const bgLight = new THREE.Color().setStyle("#f4f4f5", THREE.SRGBColorSpace);
      const bgDark = new THREE.Color().setStyle("#0e1014", THREE.SRGBColorSpace);
      const bg = new THREE.Color();
      let lastBackground = "";
      let lastScroll = progress;
      const start = performance.now();
      // ?hwsnap skips scroll smoothing and ?hwtime=<s> freezes the loops, for screenshots.
      const params = new URLSearchParams(location.search);
      const snap = params.has("hwsnap");
      const frozenTime = params.has("hwtime") ? Number(params.get("hwtime")) : null;
      function lerpAngle(a, b, w) {
        let d = b - a;
        while (d > Math.PI) d -= Math.PI * 2;
        while (d < -Math.PI) d += Math.PI * 2;
        return a + d * w;
      }
      function frame(now) {
        raf = 0;
        if (destroyed || failed || !inView || document.hidden || motionPreference.matches) return;
        // The assembly is detailed; cap rendering at 30 fps.
        if (now - lastFrame < 1000 / 30) {
          raf = requestAnimationFrame(frame);
          return;
        }
        const delta = Math.min((now - lastFrame) / 1000 || 0, 0.05);
        lastFrame = now;
        const time = frozenTime ?? (now - start) / 1000;
        smoothedProgress = snap
          ? progress
          : smoothedProgress + (progress - smoothedProgress) * 0.12;
        const scrolling = Math.abs(progress - lastScroll) > 1e-4;
        lastScroll = progress;
        const s = stageState(smoothedProgress);

        // Fingertip stage: the two finger cots take turns. As the stage closes,
        // the tactile cot (the one on the product) comes back.
        lastTime = time;
        const cyc = semiMeshes.length ? cotCycle.at(time, s.tip) : { open: 1, second: 0 };
        // Eased, so a tap on a switch button blends rather than jumps.
        const ease = snap ? 1 : Math.min(1, delta * 9);
        cotOpen += (cyc.open - cotOpen) * ease;
        cotSemi += (cyc.second - cotSemi) * ease;
        const semi = cotSemi * smooth(0.15, 0.6, s.tip);
        const tipOpen = s.tip * cotOpen;
        const labelsTip = s.labels.tip || 0;
        const labelOpen = smooth(0.55, 1, cotOpen);
        s.labels.tip = labelsTip * labelOpen * (1 - semi);
        s.labels.cot = labelsTip * labelOpen * semi;

        // Actions. Only one stage's animation is non-rest at a time.
        setAction("components", s.explode > 0 ? 1 : 0, s.explode);
        setAction("tip", tipOpen > 0 ? 1 : 0, tipOpen);
        setAction("finger", s.finger, ((time / loopSeconds.finger) % 1));
        setAction("thumb", s.thumb, ((time / loopSeconds.thumb) % 1));
        if (actions.tpu) setAction("tpu", s.tpuFit > 0 ? 1 : 0, s.tpuFit);
        mixer.update(0);

        // Focus on the middle finger.
        for (const m of focusFade) setOpacity(m, 1 - s.focus);
        for (const m of ballCovers) setOpacity(m, 1 - 0.78 * s.covers);
        // Modular stage: camera and Quest; TPU hand stage: the Quest comes off, the TPU hand goes in.
        placeDevices(s.quest, s.devices);
        if (tpuParts.length) placeTpu(s.tpu);
        s.labels.camera = s.labels.quest = s.labels.modular || 0;

        // Joint graphics.
        ringGroups.forEach((g) => (g.visible = s.rings > 0.01));
        ringMats.forEach((m) => (m.opacity = s.rings * (m.isLineBasicMaterial ? 0.9 : 1)));
        abadAxis.group.visible = s.rings > 0.01;
        abadAxis.mats[0].opacity = AXIS_OPACITY * s.rings;
        abadAxis.mats[1].opacity = s.rings;
        thumbAxes.forEach(({ group, mats }) => {
          group.visible = s.thumbAxes > 0.01;
          mats[0].opacity = AXIS_OPACITY * s.thumbAxes;
          mats[1].opacity = s.thumbAxes;
        });
        if (holoMat) {
          holoMat.uniforms.uOpacity.value = s.holo;
          holoMat.uniforms.uTime.value = time;
          holoMesh.visible = s.holo > 0.01;
        }
        for (const m of tactileMeshes) setOpacity(m, 1 - semi);
        for (const m of semiMeshes) setOpacity(m, semi);
        // The sensor's printed circuit shows only while the tactile cot is apart.
        if (sensorPrint) {
          const print = smooth(0.35, 0.9, tipOpen) * (1 - semi);
          const film = sensorPrint.filmOpacity * (1 - semi) * (1 - print);
          sensorPrint.mat.opacity = print;
          sensorPrint.mesh.visible = print > 0.01;
          sensorPrint.film.opacity = film;
          sensorMesh.visible = print > 0.01 || film > 0.002;
          if (sensorFlat) {
            const flatten = smooth(0.45, 0.95, tipOpen) * (1 - semi);
            sensorMesh.morphTargetInfluences[0] = flatten;
            sensorPrint.mesh.morphTargetInfluences[0] = flatten;
          }
        }

        // Dark stages: page background and rim light. The canvas is opaque in
        // the section's colour so the clear resin refracts the backdrop.
        bg.copy(bgLight).lerp(bgDark, s.dark);
        renderer.setClearColor(bg, 1);
        const css = `#${bg.getHexString(THREE.SRGBColorSpace)}`;
        if (css !== lastBackground) section.style.backgroundColor = lastBackground = css;
        section.classList.toggle("is-dark", s.dark > 0.5);
        hemi.intensity = 1.7 - 0.9 * s.dark;
        rimA.intensity = 2.4 * s.dark;
        rimB.intensity = 1.6 * s.dark;
        renderer.toneMappingExposure = 1.15 + 0.1 * s.dark;

        // Camera.
        if (scrolling && !dragging) {
          // Ease the user's own rotation back while the tour moves on.
          userYaw *= 0.94;
          userPitch *= 0.94;
        }
        if (!dragging) {
          userYaw += velYaw;
          velYaw *= 0.9;
        }
        const a = shots[s.shotFrom];
        const b = shots[s.shotTo];
        const w = s.shotBlend;
        const autoRotate = !paused && !dragging && now - lastInteraction > 3500;
        const drift = a.drift + (b.drift - a.drift) * w;
        if (autoRotate) idleYaw += delta * 0.055 * drift;
        idleYaw *= drift < 0.5 ? 0.97 : 1;
        target.lerpVectors(a.target, b.target, w);
        // The components shot follows the parts outward.
        const yaw = lerpAngle(a.yaw, b.yaw, w) + userYaw + idleYaw + Math.sin(time * 0.35) * 0.04 * (1 - drift);
        const pitch = Math.max(-1.2, Math.min(1.25, a.pitch + (b.pitch - a.pitch) * w + userPitch));
        const ra = fitDistance(a.radius);
        const rb = fitDistance(b.radius);
        const dist = Math.exp(Math.log(ra) + (Math.log(rb) - Math.log(ra)) * w);
        camOffset.set(
          Math.cos(pitch) * Math.sin(yaw),
          Math.sin(pitch),
          Math.cos(pitch) * Math.cos(yaw),
        ).multiplyScalar(dist);
        camera.position.copy(target).add(camOffset);
        camera.near = dist * 0.02;
        camera.far = dist * 20;
        camera.updateProjectionMatrix();
        camera.lookAt(target);

        // LEDs: steady power light, flickering data lights.
        const ledsOn = s.focus < 0.5;
        ledMeshes.forEach((m) => (m.visible = ledsOn));
        for (const l of leds) {
          let level = 1;
          if (l.def.blink) {
            const slot = Math.floor(time * 14 + l.def.seed);
            const n = Math.sin(slot * 12.9898 + l.def.seed * 78.233) * 43758.5453;
            const burst = 0.5 + 0.5 * Math.sin(time * 0.9 + l.def.seed);
            level = n - Math.floor(n) < 0.45 + 0.4 * burst ? 1 : 0.18;
          }
          l.mat.color.copy(l.base).multiplyScalar(0.25 + 1.6 * level);
          l.led.getWorldPosition(ledWorld);
          viewDir.copy(camera.position).sub(ledWorld).normalize();
          const facing = smooth(0.05, 0.35, viewDir.dot(ledUp));
          l.sprite.material.opacity = (0.35 + 0.65 * level) * facing * (ledsOn ? 1 : 0);
          l.sprite.visible = l.sprite.material.opacity > 0.01;
          // Follow the board when the shell lifts.
          ledBox.setFromObject(l.led).getCenter(l.sprite.position);
        }

        renderer.render(scene, camera);
        layoutLabels(s);
        cotSwitch?.update(labelsTip, semi);
        if (!raf) raf = requestAnimationFrame(frame);
      }

      wake = () => {
        if (!raf && inView && !document.hidden && !failed)
          raf = requestAnimationFrame(frame);
      };
      resetButton?.addEventListener("click", resetCamera, {
        signal: sceneListeners.signal,
      });
      motionButton?.addEventListener(
        "click",
        () => {
          paused = !paused;
          motionButton.textContent = paused ? "Resume rotation" : "Pause rotation";
          motionButton.setAttribute("aria-pressed", String(paused));
          setStatus(
            paused
              ? "Rotation paused. Drag to explore the assembly."
              : "Drag to rotate · Scroll to explore",
          );
          wake();
        },
        { signal: sceneListeners.signal },
      );
      canvas.addEventListener(
        "keydown",
        (event) => {
          if (event.key.toLowerCase() === "r") {
            resetCamera();
            event.preventDefault();
            return;
          }
          const keys = { ArrowLeft: [-0.15, 0], ArrowRight: [0.15, 0], ArrowUp: [0, -0.15], ArrowDown: [0, 0.15] };
          if (!keys[event.key]) return;
          event.preventDefault();
          userYaw += keys[event.key][0];
          userPitch = Math.max(-0.9, Math.min(0.9, userPitch + keys[event.key][1]));
          lastInteraction = performance.now();
          wake();
        },
        { signal: sceneListeners.signal },
      );
      canvas.addEventListener(
        "webglcontextlost",
        (event) => {
          event.preventDefault();
          disposeScene();
          showPoster("Assembly preview · The interactive view is unavailable.");
        },
        { signal: sceneListeners.signal },
      );
      document.addEventListener("visibilitychange", wake, {
        signal: sceneListeners.signal,
      });
      resizeObserver = new ResizeObserver(resize);
      resizeObserver.observe(container);
      resize();
      lastInteraction = performance.now();
      if (poster) poster.hidden = true;
      container.classList.add("is-ready");
      section.dataset.viewerState = "ready";
      if (resetButton) resetButton.disabled = false;
      if (motionButton) {
        motionButton.disabled = false;
        motionButton.textContent = "Pause rotation";
        motionButton.setAttribute("aria-pressed", "false");
      }
      setStatus("Drag to rotate · Scroll to explore");
      frame(performance.now());
    } catch (error) {
      // A previous load may finish after the motion setting has changed.
      if (failed || destroyed) return;
      disposeScene();
      showPoster("Assembly preview · The interactive view is unavailable.");
      console.warn("TRIMI hardware viewer could not load.", error);
    }
  }

  const observer = new IntersectionObserver(
    (entries) => {
      inView = entries[0].isIntersecting;
      if (inView) {
        loadViewer();
        wake();
      }
    },
    { rootMargin: "150px" },
  );
  observer.observe(container);

  motionPreference.addEventListener(
    "change",
    () => {
      if (motionPreference.matches) {
        cleanupScene();
        loading = false;
        showPoster("Assembly preview · Reduced motion is enabled.");
      } else if (inView) {
        loadViewer();
      }
    },
    { signal: listeners.signal },
  );
  if (motionPreference.matches)
    showPoster("Assembly preview · Reduced motion is enabled.");

  return () => {
    destroyed = true;
    observer.disconnect();
    listeners.abort();
    cleanupScene();
  };
}
