"use strict";

/* Placement only. Selection, permissions, requests and workflows belong to the
   shared controller/components. Uses main's existing wide-layout breakpoint. */
window.ComfyDesktopImagePresentation = class DesktopImagePresentation {
  constructor({ media, actions, preview, viewer, reuse, variation, images }) {
    Object.assign(this, { media, actions, preview, viewer, reuse, variation, images });
    this.originalLabel = reuse.textContent;
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
    this.geometry = new ResizeObserver(() => this.alignPreview());
    this.geometry.observe(this.workflowCard);
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

  alignPreview() {
    const panel = document.getElementById("generation-panel");
    if (this.active) panel.style.setProperty("--desktop-preview-height", `${this.workflowCard.getBoundingClientRect().height}px`);
    else panel.style.removeProperty("--desktop-preview-height");
  }

  layout(previewing) {
    this.frame.hidden = this.footer.hidden = !this.active || !previewing;
    this.rightColumn.hidden = !this.active || !previewing;
    for (const [element, anchor] of this.sectionPlacements) {
      if (this.active && previewing) {
        if (element.parentElement !== this.rightColumn) this.rightColumn.append(element);
      } else if (element.previousSibling !== anchor) anchor.after(element);
    }
    if (this.active) {
      if (this.images.parentElement !== this.frame) this.frame.append(this.images);
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
    } else {
      if (this.images.previousSibling !== this.imagesAnchor) this.imagesAnchor.after(this.images);
      for (const [input, { row }] of this.selectors) {
        if (row.isConnected) row.replaceWith(input);
      }
      this.selectors.clear();
    }
    for (const [input, { row, button, source }] of this.selectors) {
      if (!row.isConnected) this.selectors.delete(input);
      else button.disabled = source.disabled;
    }
    this.alignPreview();
  }

  render({ viewing = false, previewing = true, selected = false, pending = false, imageId } = {}) {
    document.documentElement.dataset.presentation = this.active ? "desktop" : "mobile";
    this.layout(previewing);
    const label = this.active ? "Reuse settings" : this.originalLabel;
    if (this.reuse.textContent !== label) this.reuse.textContent = label;
    this.reuse.disabled = this.variation.disabled = this.active && (!selected || pending);
    this.actions.hidden = !this.active || !selected;
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
    if (this.active && selected) {
      const destination = viewing ? this.viewer : this.preview;
      if (this.actions.parentElement !== destination.parentElement || this.actions.nextElementSibling !== destination)
        destination.before(this.actions);
    }
  }
};
