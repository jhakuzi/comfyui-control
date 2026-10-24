"use strict";

/* Placement only. Shared image controls work in both presentations; wide-layout
   arrangement is reversible. Requests and workflows stay in shared components. */
window.ComfyDesktopImagePresentation = class DesktopImagePresentation {
  constructor({ media, actions, preview, viewer, reuse, variation, images, cleanup, promptToggle, compare }) {
    Object.assign(this, { media, actions, preview, viewer, reuse, variation, images });
    this.cleanup = cleanup;
    this.promptToggle = promptToggle;
    this.negativeEditors = new Map();
    this.cleanupButtons = new Set();
    this.galleryRefresh = document.getElementById("refresh-gallery");
    this.refreshIcon = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9"/></svg>';
    this.offlineNotice = document.createElement("span");
    this.offlineNotice.id = "desktop-offline-notice";
    this.offlineNotice.className = "pill";
    this.offlineNotice.dataset.desktopSlot = "";
    this.offlineNotice.setAttribute("role", "status");
    this.offlineNotice.textContent = "Reconnecting...";
    this.offlineNotice.hidden = true;
    document.getElementById("connection").before(this.offlineNotice);
    this.originalVariationLabel = variation.textContent;
    this.viewerVariation = document.getElementById("vary-image");
    this.originalViewerVariationLabel = this.viewerVariation.textContent;
    this.viewerDetails = document.getElementById("image-details");
    this.viewerDetailsAnchor = document.createComment("Original viewer details placement");
    this.viewerDetails.before(this.viewerDetailsAnchor);
    // Phone keeps New variation and gets direct access to the same Compare flow.
    this.phoneCompare = document.createElement("button");
    this.phoneCompare.id = "phone-compare-image";
    this.phoneCompare.type = "button";
    this.phoneCompare.textContent = "Compare";
    this.phoneCompare.hidden = true;
    this.phoneCompare.addEventListener("click", compare);
    preview.append(this.phoneCompare);
    this.comparePicker = document.createElement("dialog");
    this.comparePicker.id = "desktop-compare-picker";
    this.comparePicker.dataset.desktopSlot = "";
    this.comparePicker.setAttribute("aria-labelledby", "desktop-compare-title");
    this.comparePicker.innerHTML = '<div class="heading"><h2 id="desktop-compare-title">Choose another image</h2><button type="button" class="small" aria-label="Close comparison gallery">Close</button></div><p class="hint" role="status"></p><div class="image-grid"></div>';
    this.compareGrid = this.comparePicker.querySelector(".image-grid");
    this.compareStatus = this.comparePicker.querySelector('[role="status"]');
    this.comparePicker.querySelector("button").addEventListener("click", () => this.comparePicker.close());
    this.comparePicker.addEventListener("close", () => {
      this.compareGrid.getAnimations({ subtree: true }).forEach((animation) => animation.cancel());
    });
    document.body.append(this.comparePicker);
    window.addEventListener("resize", () => this.sizeComparePicker());
    this.originalLabel = reuse.textContent;
    this.steps = document.createElement("span");
    this.steps.dataset.desktopSlot = "";
    this.steps.hidden = true;
    this.steps.append("Steps ");
    this.stepValue = document.createElement("b");
    this.stepValue.id = "stat-steps";
    this.steps.append(this.stepValue);
    document.getElementById("generation-stats").append(this.steps);
    this.sections = new Map();
    for (const id of ["lora-card", "settings-card", "resolution-card", "advanced"]) {
      const section = document.getElementById(id);
      const content = document.createElement("div");
      content.className = "desktop-section-content";
      content.dataset.desktopSlot = "";
      this.sections.set(section, content);
      section.addEventListener("toggle", () => this.sizeSections());
    }
    window.addEventListener("resize", () => this.sizeSections());
    window.addEventListener("scroll", () => this.sizeSections(), { passive: true });
    this.negativePrompt = null;
    this.loraSliders = new Map();
    this.selectors = new Map();
    this.sectionPlacements = new Map();
    this.rightColumn = document.createElement("div");
    this.rightColumn.id = "desktop-right-column";
    this.rightColumn.dataset.desktopSlot = "";
    this.rightColumn.hidden = true;
    document.getElementById("generation-panel").before(this.rightColumn);
    for (const id of ["generation-panel", "resolution-card", "advanced"]) {
      const element = document.getElementById(id);
      const anchor = document.createComment("Original desktop section placement");
      element.before(anchor);
      this.sectionPlacements.set(element, anchor);
    }
    this.imagesAnchor = document.createComment("Original result images");
    images.before(this.imagesAnchor);
    this.frame = document.createElement("div");
    this.frame.id = "desktop-result-preview";
    this.frame.dataset.desktopSlot = "";
    this.frame.hidden = true;
    this.footer = document.createElement("div");
    this.footer.id = "desktop-preview-footer";
    this.footer.dataset.desktopSlot = "";
    this.footer.hidden = true;
    const output = document.getElementById("job-output");
    output.after(this.frame, this.footer);
    this.workflowCard = document.querySelector("#generate-form > .card");
    this.geometryFrame = null;
    this.geometry = new ResizeObserver(() => {
      // Apply dependent panel geometry outside ResizeObserver's delivery cycle.
      if (this.geometryFrame !== null) return;
      this.geometryFrame = requestAnimationFrame(() => {
        this.geometryFrame = null;
        this.alignPreview();
      });
    });
    this.geometry.observe(this.workflowCard);
    this.geometry.observe(document.querySelector("#image-dialog .viewer"));
    this.anchor = document.createComment("Original preview actions");
    preview.before(this.anchor);
    this.actionsAnchor = document.createComment("Original saved-image actions");
    actions.before(this.actionsAnchor);
    this.slot = document.createElement("div");
    this.slot.id = "desktop-image-controls";
    this.slot.dataset.desktopSlot = "";
    this.slot.hidden = true;
    this.footer.append(this.slot);
  }

  get active() { return this.media.matches; }

  get comparing() { return this.comparePicker.open; }

  sizeComparePicker() {
    if (!this.comparing) return;
    // Phone uses the native safe-area/dynamic-viewport dialog bounds. Remove
    // Desktop's measured geometry before orientation or presentation changes.
    if (!this.active) {
      for (const key of ["width", "height", "left", "top"]) this.comparePicker.style.removeProperty(key);
      return;
    }
    const panel = document.getElementById("generation-panel");
    let rect = panel.getBoundingClientRect();
    // The same viewer is available on Gallery, where the Create column is hidden.
    if (!document.getElementById("gallery-page").hidden || !rect.height) {
      const tabs = document.querySelector(".tabs").getBoundingClientRect();
      const width = (tabs.width - (this.columnGap || 28)) / 2;
      rect = { width, height: parseFloat(panel.style.getPropertyValue("--desktop-preview-height")) || 800,
        left: tabs.right - width, top: document.getElementById("image-dialog").getBoundingClientRect().top };
    }
    const width = Math.min(rect.width, innerWidth - 24);
    let height = Math.min(rect.height, innerHeight - 24);
    let left = rect.left;
    let top = Math.max(12, Math.min(rect.top, innerHeight - height - 12));
    if (document.getElementById("image-dialog").open) {
      const button = this.viewerVariation.getBoundingClientRect();
      const action = this.actions.querySelector('[data-action="trash"]').getBoundingClientRect();
      const bottom = Math.min(action.bottom, innerHeight - 12);
      height = Math.min(height, Math.max(0, bottom - 12));
      left = Math.max(12, Math.min(button.left + button.width / 2 - width / 2, innerWidth - width - 12));
      top = bottom - height;
    }
    const geometry = {
      width: `${width}px`, height: `${height}px`, left: `${left}px`, top: `${top}px`,
    };
    for (const [key, value] of Object.entries(geometry)) {
      if (this.comparePicker.style[key] !== value) this.comparePicker.style[key] = value;
    }
  }

  prepareThumbnail(button, image) {
    button.dataset.thumbnailLoading = "";
    button.setAttribute("aria-busy", "true");
    const spinner = document.createElement("span");
    spinner.className = "desktop-thumbnail-spinner";
    spinner.setAttribute("aria-hidden", "true");
    button.append(spinner);
    const animation = matchMedia("(prefers-reduced-motion: reduce)").matches ? null :
      spinner.animate([{ transform: "rotate(0deg)" }, { transform: "rotate(360deg)" }],
        { duration: 800, iterations: Infinity });
    const ready = () => {
      animation?.cancel();
      spinner.remove();
      delete button.dataset.thumbnailLoading;
      button.removeAttribute("aria-busy");
    };
    image.addEventListener("load", async () => {
      try { await image.decode(); } catch { return; }
      if (image.naturalWidth) ready();
    });
    // The shared renderer retries the original image first, then shows its error.
    image.addEventListener("error", () => { if (!image.isConnected) ready(); });
  }

  openComparePicker(imageId) {
    this.comparePicker.dataset.imageId = imageId;
    this.compareGrid.replaceChildren();
    delete this.compareGrid.dataset.signature;
    this.compareStatus.textContent = "Loading gallery…";
    this.comparePicker.showModal();
    this.sizeComparePicker();
  }

  renderMetrics(progress) {
    this.steps.hidden = false;
    this.stepValue.textContent = progress ? `${progress.value} / ${progress.max}` : "-- / --";
  }

  alignPreview() {
    const panel = document.getElementById("generation-panel");
    if (this.active) {
      const measuredHeight = this.workflowCard.getBoundingClientRect().height;
      if (measuredHeight > 0) {
        const height = `${measuredHeight}px`;
        if (panel.style.getPropertyValue("--desktop-preview-height") !== height)
          panel.style.setProperty("--desktop-preview-height", height);
        this.columnGap = parseFloat(getComputedStyle(document.getElementById("workspace")).columnGap) || 28;
      }
    } else if (panel.style.getPropertyValue("--desktop-preview-height"))
      panel.style.removeProperty("--desktop-preview-height");
    this.sizeComparePicker();
    this.sizeEditors();
  }

  sizeEditors() {
    const bottom = this.workflowCard.getBoundingClientRect().bottom;
    for (const input of document.querySelectorAll('.prompt-editor textarea')) {
      const wrap = input.closest(".prompt-editor");
      if (!this.active) wrap.style.removeProperty("--desktop-editor-height");
      else {
        const height = `${Math.max(0, bottom - input.getBoundingClientRect().top)}px`;
        if (wrap.style.getPropertyValue("--desktop-editor-height") !== height)
          wrap.style.setProperty("--desktop-editor-height", height);
      }
    }
  }

  sizeSections() {
    if (!this.active) return;
    const top = Math.max(12, document.querySelector(".masthead").getBoundingClientRect().bottom + 12);
    for (const [section, content] of this.sections) {
      if (section.open && !section.hidden) {
        const height = `${Math.max(0, section.getBoundingClientRect().top - top)}px`;
        if (content.style.maxHeight !== height) content.style.maxHeight = height;
      }
    }
  }

  layout(previewing) {
    const negative = document.getElementById("negative-controls");
    if (this.negativePrompt && (!this.active || this.negativePrompt.element !== negative)) {
      this.negativePrompt.element.open = this.negativePrompt.open;
      this.negativePrompt = null;
    }
    if (this.active && negative && !this.negativePrompt) {
      this.negativePrompt = { element: negative, open: negative.open };
      negative.open = true;
    }
    for (const [input, editor] of this.negativeEditors) {
      if (!this.active || !input.isConnected) {
        editor.dispose();
        editor.heading.replaceWith(editor.label);
        if (editor.hiddenLabel) editor.label.classList.add("visually-hidden");
        editor.wrap.classList.remove("prompt-editor", "desktop-negative-editor", "expanded");
        editor.wrap.style.removeProperty("--desktop-editor-height");
        input.style.height = editor.height;
        this.negativeEditors.delete(input);
      }
    }
    if (this.active && negative) for (const input of negative.querySelectorAll('textarea[data-role="negative"]')) {
      if (this.negativeEditors.has(input)) continue;
      const wrap = input.closest(".control");
      const label = wrap.querySelector("label");
      const hiddenLabel = label.classList.contains("visually-hidden");
      const heading = document.createElement("div");
      heading.className = "prompt-editor-heading";
      heading.dataset.desktopSlot = "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "small prompt-editor-toggle";
      button.setAttribute("aria-controls", input.id);
      const height = input.style.height;
      label.classList.remove("visually-hidden");
      label.replaceWith(heading);
      heading.append(label, button);
      wrap.classList.add("prompt-editor", "desktop-negative-editor");
      const dispose = this.promptToggle(input, wrap, button);
      this.negativeEditors.set(input, { wrap, heading, label, hiddenLabel, height, dispose });
    }
    for (const [slider, original] of this.loraSliders) {
      if (!this.active || !slider.isConnected) {
        slider.min = original.min;
        slider.max = original.max;
        slider.value = original.input.value;
        this.loraSliders.delete(slider);
      }
    }
    if (this.active) for (const input of document.querySelectorAll('#lora-controls input[data-role="lora_strength"]')) {
      const slider = input.parentElement.querySelector('input[type="range"]');
      if (!slider || this.loraSliders.has(slider)) continue;
      this.loraSliders.set(slider, { min: slider.min, max: slider.max, input });
      slider.min = "-2";
      slider.max = "2";
      slider.value = input.value;
    }
    for (const [section, content] of this.sections) {
      if (this.active && content.parentElement !== section) {
        const summary = section.querySelector(":scope > summary");
        while (summary.nextSibling) content.append(summary.nextSibling);
        section.append(content);
      } else if (!this.active && content.parentElement === section) {
        content.replaceWith(...content.childNodes);
        content.style.removeProperty("max-height");
      }
    }
    if (!this.galleryRefresh.querySelector("svg")) {
      this.galleryRefresh.innerHTML = this.refreshIcon;
      this.galleryRefresh.setAttribute("aria-label", "Refresh gallery");
      this.galleryRefresh.title = "Refresh gallery";
    }
    for (const button of this.cleanupButtons) {
      if (!button.isConnected) {
        button.remove();
        this.cleanupButtons.delete(button);
      }
    }
    for (const toggle of document.querySelectorAll(".prompt-editor:not(.desktop-negative-editor) .prompt-editor-toggle")) {
      if (toggle.parentElement.querySelector(".desktop-vram-cleanup")) continue;
      const button = document.createElement("button");
      button.type = "button";
      button.className = "small desktop-vram-cleanup";
      button.dataset.desktopSlot = "";
      button.title = "Clean up VRAM (ComfyUI must be idle)";
      button.setAttribute("aria-label", "Clean up VRAM");
      button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="m14 10 6-7M12 9l5 4-4 8c-4 0-7-2-9-5l8-7ZM8 13l5 4M8 17l-1 2m4-1-1 2"/></svg>';
      button.addEventListener("click", () => this.cleanup());
      toggle.before(button);
      this.cleanupButtons.add(button);
    }
    this.frame.hidden = this.footer.hidden = !this.active || !previewing;
    this.rightColumn.hidden = !this.active || !previewing;
    for (const [element, anchor] of this.sectionPlacements) {
      if (this.active && previewing) {
        if (element.parentElement !== this.rightColumn) this.rightColumn.append(element);
      } else if (element.previousSibling !== anchor) anchor.after(element);
    }
    if (this.active) {
      if (this.images.parentElement !== this.frame) this.frame.append(this.images);
    } else if (this.images.previousSibling !== this.imagesAnchor) this.imagesAnchor.after(this.images);
    for (const input of document.querySelectorAll('#preset, #model-controls select')) {
      if (this.selectors.has(input)) continue;
      const source = document.getElementById(input.id === "preset" ? "refresh-workflows" : "refresh-models");
      const row = document.createElement("div");
      row.className = "desktop-selector-tools";
      row.dataset.desktopSlot = "";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "small desktop-selector-refresh";
      const label = document.querySelector(`label[for="${input.id}"]`)?.textContent || "model choices";
      button.setAttribute("aria-label", `Refresh ${label}`);
      button.title = `Refresh ${label}`;
      button.innerHTML = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 7v5h-5M4 17v-5h5M6.1 6.1A8 8 0 0 1 20 12M4 12a8 8 0 0 0 13.9 5.9"/></svg>';
      button.addEventListener("click", () => source.click());
      input.before(row);
      row.append(input, button);
      this.selectors.set(input, { row, button, source });
    }
    for (const [input, { row, button, source }] of this.selectors) {
      if (!row.isConnected) this.selectors.delete(input);
      else button.disabled = source.disabled;
    }
    this.alignPreview();
    this.sizeSections();
  }

  render({ viewing = false, previewing = true, selected = false, pending = false, imageId, canCleanup = false, reconnecting = false } = {}) {
    document.documentElement.dataset.presentation = this.active ? "desktop" : "mobile";
    if (this.comparing && ((!previewing && !viewing) || !selected || this.comparePicker.dataset.imageId !== imageId))
      this.comparePicker.close();
    const variationLabel = this.active ? "Compare" : this.originalVariationLabel;
    if (this.variation.textContent !== variationLabel) this.variation.textContent = variationLabel;
    const viewerLabel = this.active ? "Compare" : this.originalViewerVariationLabel;
    if (this.viewerVariation.textContent !== viewerLabel) this.viewerVariation.textContent = viewerLabel;
    this.viewerVariation.disabled = this.active
      ? !selected || pending : document.getElementById("reuse-image").disabled;
    this.offlineNotice.hidden = !this.active || !reconnecting;
    this.layout(previewing);
    for (const button of this.cleanupButtons) button.disabled = !canCleanup;
    const label = this.active ? "Reuse settings" : this.originalLabel;
    if (this.reuse.textContent !== label) this.reuse.textContent = label;
    this.reuse.disabled = this.variation.disabled = pending || (this.active && !selected);
    this.actions.hidden = !selected;
    this.phoneCompare.hidden = this.active || !selected;
    this.phoneCompare.disabled = !selected || pending;
    const phoneDestination = viewing ? this.viewer : this.preview;
    if (this.phoneCompare.parentElement !== phoneDestination) phoneDestination.append(this.phoneCompare);
    if (this.active) this.reuse.hidden = this.variation.hidden = !selected;
    this.slot.hidden = !this.active || !selected || !previewing;
    // Keep the two action rows accessible below the scrolling result, without
    // altering the image, panel or Generate geometry. Restore Phone placement.
    if (this.active && selected) {
      if (this.preview.parentElement !== this.slot) this.slot.append(this.preview);
    } else {
      if (this.preview.previousSibling !== this.anchor) this.anchor.after(this.preview);
      if (this.actions.previousSibling !== this.actionsAnchor) this.actionsAnchor.after(this.actions);
    }
    for (const button of this.images.children) {
      if (this.active && button.dataset.imageId === imageId) button.setAttribute("aria-current", "true");
      else button.removeAttribute("aria-current");
    }
    if (selected) {
      const destination = viewing ? this.viewer : this.preview;
      if (this.actions.parentElement !== destination.parentElement || this.actions.nextElementSibling !== destination)
        destination.before(this.actions);
    }
    // Use DOM order so keyboard navigation follows the visible Phone layout.
    if (this.active) {
      if (this.viewerDetails.previousSibling !== this.viewerDetailsAnchor)
        this.viewerDetailsAnchor.after(this.viewerDetails);
    } else if (this.viewerDetails.parentElement.lastElementChild !== this.viewerDetails)
      this.viewerDetails.parentElement.append(this.viewerDetails);
  }
};
