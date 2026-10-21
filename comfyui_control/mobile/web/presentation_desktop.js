"use strict";
/* Desktop structure and placement. Move existing controls; never clone them or
   add API calls/state stores. Shared IDs are the component/slot contract. */
window.ComfyDesktopPresentation = (() => {
  const $ = (id) => document.getElementById(id);
  const openSections = new Set(["settings-card", "resolution-card", "lora-card", "negative-controls"]);
  const placeholders = new Map();
  let initialized = false, detailsOpen = false;
  const desktopNode = (tag, id, text, className) => {
    const node = document.createElement(tag);
    if (id) node.id = id;
    if (text) node.textContent = text;
    if (className) node.className = className;
    node.dataset.desktopSlot = "";
    return node;
  };
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
    const observer = new ResizeObserver(() => {
      if (ComfyPresentation.desktop.matches)
        $("generation-panel").style.setProperty("--desktop-settings-height", `${Math.max(360, $("settings-stack").getBoundingClientRect().height)}px`);
    });
    observer.observe($("settings-stack"));
    ComfyPresentation.desktop.addEventListener("change", ({ matches }) => {
      if (matches) return;
      if (dialog.open) dialog.close();
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
    if (actions && $("desktop-show-details").parentElement !== actions)
      place($("desktop-show-details"), actions, actions.querySelector('[data-action="trash"]'));
    for (const input of placeholders.keys()) if (!input.isConnected) placeholders.delete(input);
    if ($("reuse-last").parentElement !== document.querySelector(".model-tools"))
      place($("reuse-last"), document.querySelector(".model-tools"));
    if ($("advanced").parentElement !== $("generate-form"))
      place($("advanced"), $("generate-form"));
    if ($("image-details").parentElement !== $("desktop-details-content"))
      place($("image-details"), $("desktop-details-content"));
    if ($("selected-image-preview").parentElement !== $("desktop-selected-stage"))
      place($("selected-image-preview"), $("desktop-selected-stage"));
    for (const input of document.querySelectorAll('textarea.positive')) {
      if (!placeholders.has(input)) placeholders.set(input, input.getAttribute("placeholder"));
      input.placeholder = input.placeholder.replace(/(?:…|\.\.\.)$/, "");
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
