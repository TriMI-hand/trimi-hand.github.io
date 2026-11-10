import { initHardwareViewer } from "./hardware-viewer.js";

const section = document.querySelector("#teleoperation");
const preference = window.matchMedia("(prefers-reduced-motion: reduce)");
let frame;

function luminance(rgb) {
  return rgb
    .map((channel) => {
      const value = channel / 255;
      return value <= 0.04045
        ? value / 12.92
        : ((value + 0.055) / 1.055) ** 2.4;
    })
    .reduce(
      (sum, value, index) => sum + value * [0.2126, 0.7152, 0.0722][index],
      0,
    );
}

function contrast(first, second) {
  return (Math.max(first, second) + 0.05) / (Math.min(first, second) + 0.05);
}

// Fade the section before its text reaches the middle of the viewport.
// Choose the higher-contrast black/white foreground from the rendered background.
// Their crossover is above 4.5:1, including at the midpoint of the fade.
function updateTheme() {
  frame = null;
  if (!section) return;
  if (preference.matches) {
    [
      "background-color",
      "color",
      "--teleop-muted",
      "--teleop-accent",
      "--teleop-line",
    ].forEach((name) => section.style.removeProperty(name));
    return;
  }
  const top = section.getBoundingClientRect().top;
  const progress = Math.min(
    1,
    Math.max(0, (window.innerHeight - top) / (window.innerHeight * 0.7)),
  );
  const ease = progress * progress * (3 - 2 * progress);
  const background = [255, 255, 255].map((v, i) =>
    Math.round(v + ([21, 23, 22][i] - v) * ease),
  );
  section.style.backgroundColor = `rgb(${background.join(",")})`;
  const backgroundLuminance = luminance(background);
  const dark =
    contrast(backgroundLuminance, 1) > contrast(backgroundLuminance, 0);
  const foreground = dark ? "#ffffff" : "#000000";
  section.style.color = foreground;
  section.style.setProperty("--teleop-muted", foreground);
  section.style.setProperty("--teleop-accent", foreground);
  section.style.setProperty("--teleop-line", foreground);
}
function scheduleTheme() {
  if (!frame) frame = requestAnimationFrame(updateTheme);
}
window.addEventListener("scroll", scheduleTheme, { passive: true });
window.addEventListener("resize", scheduleTheme);
preference.addEventListener("change", scheduleTheme);
updateTheme();
initHardwareViewer();
