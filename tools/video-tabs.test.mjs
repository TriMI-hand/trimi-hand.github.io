import assert from "node:assert/strict";
import test from "node:test";
import { parseHTML } from "linkedom";
import { initializeVideoTabs } from "../src/scripts/video-tabs.ts";

function fixture() {
  const widget = (id) => `<section data-video-tabs id="${id}">
    <div role="tablist">
      ${[0, 1, 2].map((index) => `<button data-video-tab role="tab" aria-selected="${index === 0}" tabindex="${index === 0 ? 0 : -1}">${id} ${index}</button>`).join("")}
    </div>
    ${[0, 1, 2].map((index) => `<div data-video-panel role="tabpanel" ${index ? "hidden" : ""}><video></video></div>`).join("")}
  </section>`;
  const { document, window } = parseHTML(
    `<html><body>${widget("first")}${widget("second")}</body></html>`,
  );
  let focused;
  const groups = Array.from(document.querySelectorAll("[data-video-tabs]"));
  const tabs = groups.map((group) =>
    Array.from(group.querySelectorAll("[data-video-tab]")),
  );
  const panels = groups.map((group) =>
    Array.from(group.querySelectorAll("[data-video-panel]")),
  );
  const videos = groups.map((group) =>
    Array.from(group.querySelectorAll("video")),
  );
  for (const tab of tabs.flat()) {
    tab.focus = () => {
      focused = tab;
    };
  }
  for (const video of videos.flat()) {
    video.currentTime = 4.2;
    video.pauseCount = 0;
    video.playCount = 0;
    video.pause = () => {
      video.pauseCount += 1;
    };
    video.play = () => {
      video.playCount += 1;
    };
  }
  const key = (tab, value, modifiers = {}) => {
    const event = new window.Event("keydown", {
      bubbles: true,
      cancelable: true,
    });
    Object.assign(event, { key: value, ...modifiers });
    tab.dispatchEvent(event);
    return event;
  };
  const click = (tab) =>
    tab.dispatchEvent(new window.Event("click", { bubbles: true }));
  return { document, tabs, panels, videos, key, click, focused: () => focused };
}

function selectedIndex(tabs) {
  return tabs.findIndex((tab) => tab.getAttribute("aria-selected") === "true");
}

test("selecting a video pauses the old clip, retains time, and leaves other groups alone", () => {
  const f = fixture();
  initializeVideoTabs(f.document);
  f.click(f.tabs[0][1]);
  assert.equal(selectedIndex(f.tabs[0]), 1);
  assert.equal(selectedIndex(f.tabs[1]), 0);
  assert.deepEqual(
    f.panels[0].map((panel) => panel.hidden),
    [true, false, true],
  );
  assert.deepEqual(
    f.tabs[0].map((tab) => tab.getAttribute("tabindex")),
    ["-1", "0", "-1"],
  );
  assert.equal(f.videos[0][0].pauseCount, 1);
  assert.equal(f.videos[0][0].currentTime, 4.2);
  assert.equal(f.videos[0][1].playCount, 0);
  assert.equal(f.videos[1][0].pauseCount, 0);
  f.click(f.tabs[0][0]);
  assert.equal(f.videos[0][1].pauseCount, 1);
  assert.equal(f.videos[0][0].currentTime, 4.2);
});

test("keyboard selection wraps, moves focus, and supports Home and End", () => {
  const f = fixture();
  initializeVideoTabs(f.document);
  assert.equal(f.key(f.tabs[0][0], "ArrowLeft").defaultPrevented, true);
  assert.equal(selectedIndex(f.tabs[0]), 2);
  assert.equal(f.focused(), f.tabs[0][2]);
  f.key(f.tabs[0][2], "ArrowRight");
  assert.equal(selectedIndex(f.tabs[0]), 0);
  f.key(f.tabs[0][0], "End");
  assert.equal(selectedIndex(f.tabs[0]), 2);
  f.key(f.tabs[0][2], "Home");
  assert.equal(selectedIndex(f.tabs[0]), 0);
  assert.equal(f.focused(), f.tabs[0][0]);
  assert.equal(f.key(f.tabs[0][0], "Tab").defaultPrevented, false);
  assert.equal(
    f.key(f.tabs[0][0], "ArrowRight", { ctrlKey: true }).defaultPrevented,
    false,
  );
  assert.equal(selectedIndex(f.tabs[0]), 0);
});

test("reinitializing preserves selection without duplicating handlers", () => {
  const f = fixture();
  initializeVideoTabs(f.document);
  f.click(f.tabs[0][1]);
  initializeVideoTabs(f.document);
  assert.equal(selectedIndex(f.tabs[0]), 1);
  f.key(f.tabs[0][1], "ArrowRight");
  assert.equal(f.videos[0][1].pauseCount, 1);
  assert.equal(selectedIndex(f.tabs[0]), 2);
  f.click(f.tabs[0][2]);
  assert.equal(f.videos[0][2].pauseCount, 0);
});
