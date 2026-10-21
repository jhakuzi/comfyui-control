"use strict";
/* Presentation coordinator only. No API, job store, workflow or persistence logic.
   Loaded in <head> so the scoped stylesheet is selected before first paint. */
window.ComfyPresentation = (() => {
  const wide = window.matchMedia("(min-width: 1000px) and (min-height: 600px)");
  const desktop = window.matchMedia(
    "(min-width: 1024px) and (min-height: 600px) and (min-aspect-ratio: 4/3), " +
    "(min-width: 1440px) and (min-height: 600px)",
  );
  const compactSections = new Map(); // Temporary layout restoration, never saved separately.
  const placements = new Map();
  const $ = (id) => document.getElementById(id);
  const current = () => desktop.matches ? window.ComfyDesktopPresentation : window.ComfyMobilePresentation;
  const selectScope = () => {
    document.documentElement.dataset.presentation = desktop.matches ? "desktop" : "mobile";
  };
  selectScope();
  desktop.addEventListener("change", selectScope);

  function place(node, parent, before = null) {
    if (!desktop.matches) throw new Error("Desktop placement requires the desktop presentation.");
    if (!placements.has(node)) {
      const anchor = document.createComment("presentation return");
      node.before(anchor);
      placements.set(node, anchor);
    }
    parent.insertBefore(node, before);
  }
  function restorePlacements() {
    for (const [node, anchor] of placements) {
      if (anchor.parentNode) anchor.after(node);
      anchor.remove();
    }
    placements.clear();
  }

  return Object.freeze({
    wide, desktop, place,
    get inlineImages() { return current().inlineImages; },
    arrange(uiState) {
      if (!desktop.matches) restorePlacements();
      current().arrange({ compactSections, uiState, place });
    },
    navigate(name, uiState) {
      $("workspace").dataset.page = name;
      $("workspace").dataset.layout = desktop.matches ? "studio" : "compact";
      this.arrange(uiState);
      current().navigate(name);
      $("create-tab").classList.toggle("selected", name === "create");
      $("gallery-tab").classList.toggle("selected", name === "gallery");
    },
    sectionOpen(el) {
      return desktop.matches && compactSections.has(el.id) ? compactSections.get(el.id) : el.open;
    },
    forcedOpen(id) { return current().forcedOpen(id); },
    imageActions(view) { current().imageActions?.(view); },
    unavailableImageAction(view) { current().unavailableImageAction?.(view); },
    metrics(active) { current().metrics({ active, wide: wide.matches, place }); },
    generation(view) {
      const { job, active, submitting } = view;
      $("job-card").dataset.preparing = String(submitting && !active);
      $("preview-stage").dataset.preview = String(!$("preview").hidden && !submitting);
      $("preview-loading-phase").textContent = submitting && !active ? "Submitting workflow…"
        : $("job-title").textContent || "Preparing generation…";
      $("job-images").hidden = active || submitting;
      $("generation-panel").dataset.active = String(active || submitting);
      $("generation-panel").dataset.jobStatus = job?.status || "";
      $("generation-empty").hidden = !!job || submitting || !!view.selectedImage;
      $("dock-submitting").hidden = !submitting || active;
      this.metrics(active);
      current().generation({ ...view, wide: wide.matches, place });
    },
    selectedPreview(item) { return current().selectedPreview({ item, wide: wide.matches, place }); },
    inspectImage(item, inspect, reducedMotion) { current().inspectImage(item, inspect, reducedMotion); },
    openImage(items, index, select) { return current().openImage(items, index, select); },
    reconcileViewer(view) { current().reconcileViewer(view); },
    focusGallery(reducedMotion) { current().focusGallery(reducedMotion); },
    observeGeometry() {
      new ResizeObserver(() => {
        const height = $("generation-dock").getBoundingClientRect().height;
        document.documentElement.style.setProperty("--generation-dock-height", `${height}px`);
      }).observe($("generation-dock"));
      new ResizeObserver(([entry]) => {
        document.documentElement.style.setProperty("--masthead-height", `${entry.target.getBoundingClientRect().height}px`);
      }).observe(document.querySelector(".masthead"));
    },
    onChange(callbacks) {
      wide.addEventListener("change", callbacks.wide);
      desktop.addEventListener("change", callbacks.desktop);
    },
  });
})();
