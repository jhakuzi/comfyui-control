"use strict";
/* Mobile/tablet structure and placement. Desktop must never edit this adapter. */
window.ComfyMobilePresentation = (() => {
  const $ = (id) => document.getElementById(id);
  function arrange({ compactSections }) {
    // The coordinator has already returned desktop placements to their anchors.
    for (const [id, open] of compactSections) {
      const section = $(id);
      if (!section) continue;
      section.open = open;
      const summary = section.querySelector(":scope > summary");
      summary.removeAttribute("tabindex");
      summary.removeAttribute("aria-disabled");
    }
    compactSections.clear();
  }
  function navigate(name) {
    $("create-page").hidden = name !== "create";
    $("gallery-page").hidden = name !== "gallery";
  }
  function metrics({ active, wide }) {
    const header = $("header-generation"), metrics = $("job-metrics");
    const atTop = active && wide && !$("workspace").hidden;
    const destination = atTop ? header : $("job-card");
    if (metrics.parentElement !== destination) {
      if (atTop) destination.append(metrics);
      else destination.insertBefore(metrics, $("preview-stage"));
    }
    const cancel = $("cancel-controls"), heading = $("job-card").querySelector(".heading");
    if (cancel.parentElement !== heading) heading.append(cancel);
    header.hidden = !atTop;
  }
  function generation({ job, active, submitting, wide }) {
    const dock = $("generation-dock"), card = $("job-card");
    const destination = active || (submitting && wide) ? dock : $("job-output");
    card.hidden = !job && !(submitting && wide);
    $("preview-stage").hidden = !(active || submitting);
    $("job-output").hidden = !$("gallery-page").hidden;
    if (card.parentElement !== destination) {
      if (active) destination.prepend(card);
      else destination.append(card);
    }
    dock.hidden = !active && !submitting && !$("gallery-page").hidden;
  }
  function selectedPreview({ item, wide }) {
    const source = wide ? item?.url : null;
    if (source) {
      if ($("selected-image-preview").getAttribute("src") !== source) $("selected-image-preview").src = source;
    } else $("selected-image-preview").removeAttribute("src");
    const tools = $("image-browse-tools"), destination = $("viewer-image-tools");
    const moved = tools.parentElement !== destination;
    if (moved) destination.append(tools);
    return { moved, inline: false };
  }
  return Object.freeze({ arrange, navigate, metrics, generation, selectedPreview,
    inlineImages: false, openImage: () => false,
    reconcileViewer({ refresh }) { refresh(); },
    forcedOpen: () => false, inspectImage() {}, focusGallery() {} });
})();
