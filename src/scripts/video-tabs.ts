const initialized = new WeakSet<Element>();

/** Enhance each independently rendered video tab group once. */
export function initializeVideoTabs(scope: ParentNode = document): void {
  scope.querySelectorAll<HTMLElement>("[data-video-tabs]").forEach((group) => {
    if (initialized.has(group)) return;

    const tabs = Array.from(
      group.querySelectorAll<HTMLButtonElement>("[data-video-tab]"),
    );
    const panels = Array.from(
      group.querySelectorAll<HTMLElement>("[data-video-panel]"),
    );
    if (tabs.length === 0 || tabs.length !== panels.length) return;

    let selected = tabs.findIndex(
      (tab) => tab.getAttribute("aria-selected") === "true",
    );
    if (selected < 0) selected = 0;

    function select(index: number, moveFocus = false): void {
      if (index !== selected) {
        panels[selected].querySelectorAll("video").forEach((video) => {
          video.pause();
        });
      }

      selected = index;
      tabs.forEach((tab, tabIndex) => {
        const active = tabIndex === selected;
        tab.setAttribute("aria-selected", String(active));
        tab.tabIndex = active ? 0 : -1;
        panels[tabIndex].hidden = !active;
      });
      if (moveFocus) tabs[selected].focus();
    }

    select(selected);
    tabs.forEach((tab, index) => {
      tab.addEventListener("click", () => select(index));
      tab.addEventListener("keydown", (event) => {
        if (event.altKey || event.ctrlKey || event.metaKey) return;

        let next: number;
        switch (event.key) {
          case "ArrowLeft":
            next = (index - 1 + tabs.length) % tabs.length;
            break;
          case "ArrowRight":
            next = (index + 1) % tabs.length;
            break;
          case "Home":
            next = 0;
            break;
          case "End":
            next = tabs.length - 1;
            break;
          default:
            return;
        }
        event.preventDefault();
        select(next, true);
      });
    });
    initialized.add(group);
  });
}
