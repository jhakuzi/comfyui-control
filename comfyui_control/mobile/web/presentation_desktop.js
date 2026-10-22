"use strict";
/* Desktop structure and placement. Move existing controls; never clone them or
   add API calls/state stores. Shared IDs are the component/slot contract. */
window.ComfyDesktopPresentation = (() => {
  const $ = (id) => document.getElementById(id);
  const openSections = new Set(["settings-card", "resolution-card", "lora-card", "negative-controls"]);
  const placeholders = new Map();
  const scrollFrames = new WeakMap();
  let initialized = false, detailsOpen = false;
  // Geometry writes run in the next frame, outside ResizeObserver delivery.
  const afterLayout = (update) => {
    let pending = false;
    return () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => { pending = false; update(); });
    };
  };
  const desktopNode = (tag, id, text, className) => {
    const node = document.createElement(tag);
    if (id) node.id = id;
    if (text) node.textContent = text;
    if (className) node.className = className;
    node.dataset.desktopSlot = "";
    return node;
  };
  function placePreview(place) {
    const zoom = $("desktop-image-zoom"), enlarged = zoom.open;
    const destination = enlarged ? $("desktop-zoom-stage") : $("desktop-selected-stage");
    const image = $("selected-image-preview");
    if (image.parentElement !== destination) place(image, destination);
    const heart = document.querySelector("#selected-image-actions .image-heart, #desktop-selected-stage .image-heart, #desktop-zoom-controls .image-heart");
    const controls = enlarged ? $("desktop-zoom-controls") : destination;
    if (heart && heart.parentElement !== controls)
      place(heart, controls, enlarged ? $("desktop-close-zoom") : null);
    // Move whole shared components so IDs, handlers and navigation context stay intact.
    const actionDestination = enlarged ? $("desktop-zoom-actions") : $("selected-image-panel");
    for (const node of [$("selected-image-tools"), $("selected-image-actions"),
      document.querySelector(".selected-image-reuse"), $("selected-reuse-status")]) {
      if (node.parentElement !== actionDestination) place(node, actionDestination);
    }
  }
  async function copyDetails() {
    const root = $("image-metadata");
    const fields = [...root.querySelectorAll("summary, h3, .metadata-prompt, dt")];
    const text = [$("selected-image-name").textContent,
      ...(fields.length ? fields.map((el) => el.tagName === "DT"
        ? `${el.textContent}: ${el.nextElementSibling.textContent}` : el.textContent) : [root.textContent])].join("\n\n");
    try {
      let copied = false;
      if (navigator.clipboard?.writeText && window.isSecureContext) {
        try { await navigator.clipboard.writeText(text); copied = true; } catch {}
      }
      if (!copied) {
        const input = document.createElement("textarea");
        input.value = text;
        input.readOnly = true;
        input.className = "clipboard-text";
        $("desktop-image-details").append(input);
        input.focus({ preventScroll: true });
        input.select();
        copied = document.execCommand("copy");
        input.remove();
        if (!copied) throw new Error();
      }
      $("desktop-copy-status").textContent = "Details copied.";
    } catch {
      $("desktop-copy-status").textContent = "Copy is unavailable. Select the details text to copy it.";
    }
    $("desktop-copy-details").focus({ preventScroll: true });
  }
  function initialize() {
    if (initialized) return;
    initialized = true;
    const cancel = desktopNode("div", "desktop-cancel-slot");
    $("desktop-toolbar").append(cancel);
    const stage = desktopNode("div", "desktop-selected-stage");
    $("selected-image-preview").before(stage);
    const zoom = desktopNode("dialog", "desktop-image-zoom");
    zoom.setAttribute("aria-label", "Enlarged image preview");
    const zoomStage = desktopNode("div", "desktop-zoom-stage");
    const zoomControls = desktopNode("div", "desktop-zoom-controls", null, "heading");
    const zoomViewer = desktopNode("div", null, null, "viewer");
    const zoomActions = desktopNode("div", "desktop-zoom-actions");
    const closeZoom = desktopNode("button", "desktop-close-zoom", "Close", "small");
    closeZoom.type = "button";
    zoomControls.append(closeZoom);
    zoomStage.append(zoomControls);
    zoomViewer.append(zoomStage, zoomActions);
    zoom.append(zoomViewer);
    document.body.append(zoom);
    closeZoom.addEventListener("click", () => zoom.close());
    zoom.addEventListener("keydown", (event) => {
      if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey ||
        !["ArrowLeft", "ArrowRight"].includes(event.key) ||
        event.target.closest("input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], [role='slider']") ||
        document.querySelector("dialog[open]:not(#desktop-image-zoom)")) return;
      event.preventDefault();
      $(event.key === "ArrowLeft" ? "previous-image" : "next-image").click();
    });
    zoom.addEventListener("close", () => {
      if (!ComfyPresentation.desktop.matches || zoom.open) return;
      placePreview(ComfyPresentation.place);
      positionHeart();
      if ($("selected-image-preview").getClientRects().length)
        $("selected-image-preview").focus({ preventScroll: true });
    });
    const button = desktopNode("button", "desktop-show-details", "Details");
    button.type = "button";
    button.setAttribute("aria-haspopup", "dialog");
    button.setAttribute("aria-controls", "desktop-image-details");
    $("image-browse-tools").querySelector(".actions").append(button);
    const dialog = desktopNode("dialog", "desktop-image-details");
    dialog.setAttribute("aria-labelledby", "desktop-details-title");
    const viewer = desktopNode("div", null, null, "viewer");
    const heading = desktopNode("div", null, null, "heading");
    const title = desktopNode("h2", "desktop-details-title", "Image details");
    const close = desktopNode("button", "desktop-close-details", "Close", "small");
    close.type = "button";
    heading.append(title, close);
    const copy = desktopNode("button", "desktop-copy-details", "Copy details", "small");
    copy.type = "button";
    const status = desktopNode("p", "desktop-copy-status", null, "hint");
    status.setAttribute("role", "status");
    viewer.append(heading, copy, status, desktopNode("div", "desktop-details-content"));
    dialog.append(viewer);
    document.body.append(dialog);
    button.addEventListener("click", () => {
      detailsOpen = $("image-details").open;
      $("desktop-copy-status").textContent = "";
      $("image-details").open = true; // The existing metadata loader owns the request.
      dialog.showModal();
    });
    close.addEventListener("click", () => dialog.close());
    copy.addEventListener("click", copyDetails);
    dialog.addEventListener("close", () => {
      // A queued close event must not override mobile's restored disclosure.
      if (ComfyPresentation.desktop.matches) $("image-details").open = detailsOpen;
    });
    const observer = new ResizeObserver(afterLayout(() => {
      if (!ComfyPresentation.desktop.matches) return;
      $("generation-panel").style.setProperty("--desktop-settings-height", `${Math.max(360, $("settings-stack").getBoundingClientRect().height)}px`);
      const batch = $("batch-count");
      if (batch?.getClientRects().length) {
        const bottom = batch.getBoundingClientRect().bottom;
        for (const editor of $("prompt-controls").querySelectorAll(".prompt-editor")) {
          const height = Math.max(112, bottom - editor.getBoundingClientRect().top);
          editor.style.setProperty("--desktop-prompt-expanded-height", `${height}px`);
        }
      }
    }));
    observer.observe($("settings-stack"));
    observer.observe($("settings-card"));
    observer.observe($("prompt-controls"));
    const image = $("selected-image-preview");
    const sizeZoomImage = () => {
      if (ComfyPresentation.desktop.matches && zoom.open && image.naturalWidth)
        zoomStage.style.setProperty("--desktop-zoom-ratio", String(image.naturalWidth / image.naturalHeight));
    };
    image.addEventListener("load", sizeZoomImage);
    const enlarge = () => {
      if (!ComfyPresentation.desktop.matches || !image.naturalWidth || !image.getAttribute("src") || zoom.open) return;
      zoomStage.style.setProperty("--desktop-zoom-ratio", String(image.naturalWidth / image.naturalHeight));
      zoom.showModal();
      placePreview(ComfyPresentation.place);
      closeZoom.focus({ preventScroll: true });
      zoomViewer.scrollTop = 0;
    };
    image.addEventListener("dblclick", enlarge);
    image.addEventListener("keydown", (event) => {
      if (ComfyPresentation.desktop.matches && ["Enter", " "].includes(event.key)) {
        event.preventDefault();
        enlarge();
      }
    });
    const positionHeart = afterLayout(() => {
      if (!ComfyPresentation.desktop.matches || image.parentElement !== stage || !image.getClientRects().length) return;
      const bounds = image.getBoundingClientRect(), container = stage.getBoundingClientRect();
      for (const [property, value] of [
        ["--desktop-heart-top", `${bounds.top - container.top + 8}px`],
        ["--desktop-heart-right", `${container.right - bounds.right + 8}px`],
      ]) {
        if (stage.style.getPropertyValue(property) !== value) stage.style.setProperty(property, value);
      }
    });
    const imageObserver = new ResizeObserver(positionHeart);
    imageObserver.observe(image);
    imageObserver.observe(stage);
    const grid = $("gallery-grid");
    const limitGallery = () => {
      if (!ComfyPresentation.desktop.matches || !grid.clientWidth) return;
      const tile = grid.querySelector("button");
      if (!tile) return;
      const css = getComputedStyle(grid);
      const height = tile.getBoundingClientRect().height * 8 + parseFloat(css.rowGap) * 7
        + parseFloat(css.paddingTop) + parseFloat(css.paddingBottom);
      const value = `${height}px`;
      if (grid.style.getPropertyValue("--desktop-gallery-limit") !== value)
        grid.style.setProperty("--desktop-gallery-limit", value);
    };
    new ResizeObserver(afterLayout(limitGallery)).observe(grid);
    new MutationObserver(limitGallery).observe(grid, { childList: true });
    ComfyPresentation.desktop.addEventListener("change", ({ matches }) => {
      if (matches) return;
      if (dialog.open) dialog.close();
      if (zoom.open) zoom.close();
      for (const attribute of ["tabindex", "role", "aria-label", "aria-haspopup", "aria-controls"])
        image.removeAttribute(attribute);
      for (const [input, placeholder] of placeholders) input.setAttribute("placeholder", placeholder);
      placeholders.clear();
    });
  }
  function arrange({ compactSections, uiState, place }) {
    initialize();
    if ($("workflow-picker").parentElement !== $("desktop-toolbar")) {
      for (const node of [$("workflow-picker"), $("model-controls"), document.querySelector(".model-tools"),
        $("empty-presets"), $("comfy-offline")])
        place(node, $("desktop-toolbar"));
    }
    if ($("generate").parentElement !== $("desktop-generate-slot")) {
      place($("generate"), $("desktop-generate-slot"));
      place($("prompt-actions"), $("desktop-generate-slot"));
    }
    const actions = $("selected-image-actions").querySelector(".saved-image-buttons");
    placePreview(place);
    const image = $("selected-image-preview");
    image.tabIndex = 0;
    image.setAttribute("role", "button");
    image.setAttribute("aria-label", "Enlarge image preview");
    image.setAttribute("aria-haspopup", "dialog");
    image.setAttribute("aria-controls", "desktop-image-zoom");
    if (actions && $("desktop-show-details").parentElement !== actions)
      place($("desktop-show-details"), actions, actions.querySelector('[data-action="trash"]'));
    for (const input of placeholders.keys()) if (!input.isConnected) placeholders.delete(input);
    if ($("reuse-last").parentElement !== document.querySelector(".model-tools"))
      place($("reuse-last"), document.querySelector(".model-tools"));
    if ($("advanced").parentElement !== $("generate-form"))
      place($("advanced"), $("generate-form"));
    if ($("image-details").parentElement !== $("desktop-details-content"))
      place($("image-details"), $("desktop-details-content"));
    for (const input of document.querySelectorAll('textarea.positive')) {
      if (!placeholders.has(input)) placeholders.set(input, input.getAttribute("placeholder"));
      input.placeholder = input.placeholder.replace(/(?:…|\.\.\.)$/, "");
    }
    const filters = document.querySelector(".library-filters");
    for (const id of ["select-compare", "compare-images"])
      if ($(id).parentElement !== filters) place($(id), filters);
    for (const input of document.querySelectorAll("textarea:not(.clipboard-text)")) {
      let frame = scrollFrames.get(input);
      if (!frame) {
        frame = desktopNode("div", null, null, "desktop-scroll-frame");
        input.before(frame);
        scrollFrames.set(input, frame);
      }
      if (input.parentElement !== frame) place(input, frame);
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
  function navigate(name) {
    if (name === "create" && $("desktop-image-zoom")?.open) $("desktop-image-zoom").close();
    $("create-page").hidden = false;
    $("gallery-page").hidden = false;
  }
  function metrics({ place }) {
    initialize();
    const metrics = $("job-metrics"), card = $("job-card"), cancel = $("cancel-controls");
    if (metrics.parentElement !== card) place(metrics, card, $("preview-stage"));
    if (cancel.parentElement !== $("desktop-cancel-slot"))
      place(cancel, $("desktop-cancel-slot"));
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
    if ($("desktop-image-zoom")?.open && ($("workspace").hidden || !item)) {
      $("desktop-image-zoom").close();
      placePreview(place);
    }
    if ($("desktop-image-details")?.open && (!item || $("selected-image-preview").getAttribute("src") !== item.url))
      $("desktop-image-details").close();
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
    if (inspect && item && !$("desktop-image-zoom")?.open)
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
  function imageActions({ buttons, capabilities, status, pending }) {
    const trash = capabilities.actions.trash;
    if (!pending && !trash.available && trash.reason) {
      buttons.get("trash").disabled = false;
      if (status.textContent === trash.reason) status.textContent = "";
    }
  }
  function unavailableImageAction({ action, reason, status }) {
    if (action === "trash" && reason) status.textContent = reason;
  }
  return Object.freeze({ imageActions, unavailableImageAction, arrange, navigate, metrics, generation, selectedPreview, inspectImage,
    inlineImages: true, openImage, reconcileViewer, focusGallery,
    forcedOpen: (id) => openSections.has(id) });
})();
