"use strict";

/* Placement only. Selection, permissions, requests and workflows belong to the
   shared controller/components. Uses main's existing wide-layout breakpoint. */
window.ComfyDesktopImagePresentation = class DesktopImagePresentation {
  constructor({ media, actions, preview, viewer, reuse, variation, images }) {
    Object.assign(this, { media, actions, preview, viewer, reuse, variation, images });
    this.originalLabel = reuse.textContent;
    this.anchor = document.createComment("Original preview actions");
    preview.before(this.anchor);
    this.actionsAnchor = document.createComment("Original saved-image actions");
    actions.before(this.actionsAnchor);
    this.slot = document.createElement("div");
    this.slot.id = "desktop-image-controls";
    this.slot.dataset.desktopSlot = "";
    this.slot.hidden = true;
    document.getElementById("job-output").after(this.slot);
  }

  get active() { return this.media.matches; }

  render({ viewing = false, previewing = true, selected = false, pending = false, imageId } = {}) {
    document.documentElement.dataset.presentation = this.active ? "desktop" : "mobile";
    const label = this.active ? "Reuse settings" : this.originalLabel;
    if (this.reuse.textContent !== label) this.reuse.textContent = label;
    this.reuse.disabled = this.variation.disabled = this.active && (!selected || pending);
    this.actions.hidden = !this.active || !selected;
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
