"use strict";
/* Desktop structure and placement. Move existing controls; never clone them or
   add API calls/state stores. Shared IDs are the component/slot contract. */
window.ComfyDesktopPresentation = (() => {
  const $ = (id) => document.getElementById(id);
  const openSections = new Set(["settings-card", "resolution-card", "lora-card", "negative-controls"]);
  function arrange({ compactSections, uiState, place }) {
    if ($("workflow-picker").parentElement !== $("desktop-toolbar")) {
      for (const node of [$("workflow-picker"), $("model-controls"), document.querySelector(".model-tools"),
        $("empty-presets"), $("comfy-offline")])
        place(node, $("desktop-toolbar"));
    }
    if ($("generate").parentElement !== $("desktop-generate-slot")) {
      place($("generate"), $("desktop-generate-slot"));
      place($("prompt-actions"), $("desktop-generate-slot"));
    }
    // Match the visual reading order without changing the mobile control tree.
    if ($("resolution-card").nextElementSibling !== $("lora-card"))
      place($("resolution-card"), $("settings-stack"), $("lora-card"));
    for (const id of openSections) {
      const section = $(id);
      if (!section) continue;
      const summary = section.querySelector(":scope > summary");
      if (!compactSections.has(id)) compactSections.set(id, uiState.details?.[id] ?? section.open);
      section.open = true;
      summary.tabIndex = -1;
      summary.setAttribute("aria-disabled", "true");
    }
  }
  function navigate() {
    $("create-page").hidden = false;
    $("gallery-page").hidden = false;
  }
  function metrics({ place }) {
    const metrics = $("job-metrics"), card = $("job-card"), cancel = $("cancel-controls");
    if (metrics.parentElement !== card) place(metrics, card, $("preview-stage"));
    if (cancel.parentElement !== $("desktop-generate-slot"))
      place(cancel, $("generate").parentNode, $("generate").nextSibling);
    $("header-generation").hidden = true;
  }
  function generation({ job, active, submitting, inspectingSavedImage, place }) {
    const dock = $("generation-dock"), card = $("job-card");
    const destination = $("job-output");
    card.hidden = !job && !submitting;
    $("preview-stage").hidden = !(active || submitting) || inspectingSavedImage;
    $("job-output").hidden = false;
    if (card.parentElement !== destination) {
      place(card, destination);
    }
    dock.hidden = false;
  }
  function selectedPreview({ item, place }) {
    if (item?.url) {
      if ($("selected-image-preview").getAttribute("src") !== item.url) $("selected-image-preview").src = item.url;
    } else $("selected-image-preview").removeAttribute("src");
    const tools = $("image-browse-tools");
    const inline = !!item && !$("workspace").hidden;
    const destination = inline ? $("selected-image-tools") : $("viewer-image-tools");
    const moved = tools.parentElement !== destination;
    if (moved) place(tools, destination);
    return { moved, inline };
  }
  function inspectImage(item, inspect, reducedMotion) {
    if (inspect && item)
      $("generation-panel").scrollIntoView({ block: "start", behavior: reducedMotion ? "instant" : "smooth" });
  }
  function openImage(items, index, select) {
    select(items[(index + items.length) % items.length], true);
    return true;
  }
  function reconcileViewer({ item, select, refresh }) {
    if ($("image-dialog").open) {
      if (item) select(item, true);
      $("image-dialog").close();
    } else refresh();
  }
  function focusGallery(reducedMotion) {
    $("gallery-page").scrollIntoView({ block: "nearest", behavior: reducedMotion ? "instant" : "smooth" });
  }
  return Object.freeze({ arrange, navigate, metrics, generation, selectedPreview, inspectImage,
    inlineImages: true, openImage, reconcileViewer, focusGallery,
    forcedOpen: (id) => openSections.has(id) });
})();
