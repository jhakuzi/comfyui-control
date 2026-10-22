"use strict";

/* One action view for any explicitly selected saved image. No last-job lookup. */
class SavedImageActions {
  constructor(container, { api, changed, workflow }) {
    this.container = container;
    this.api = api;
    this.changed = changed;
    this.workflow = workflow;
    this.epoch = 0;
    this.item = null;
    this.buttons = new Map();
    const row = document.createElement("div");
    row.className = "actions saved-image-buttons";
    for (const [key, label] of [["keep", "♡"], ["edit", "Edit"], ["upscale", "Upscale"], ["trash", "Trash"]]) {
      const button = document.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.dataset.action = key;
      if (key === "keep") button.classList.add("image-heart");
      if (key === "trash") button.classList.add("danger");
      button.addEventListener("click", () => this.perform(key));
      row.append(button);
      this.buttons.set(key, button);
    }
    this.status = document.createElement("p");
    this.status.className = "hint image-action-status";
    this.status.setAttribute("role", "status");
    this.unavailable = document.createElement("p");
    this.unavailable.className = "hint image-workflow-status";
    container.append(row, this.unavailable, this.status);
    ComfyPresentation.desktop.addEventListener("change", () => this.renderCapabilities());
  }

  renderCapabilities() {
    if (!this.capabilities) return;
    this.buttons.forEach((button, key) => {
      button.disabled = !!this.pending || !this.capabilities.actions[key]?.available;
      if (key !== "keep" || !this.capabilities.actions[key]?.available)
        button.title = this.capabilities.actions[key]?.reason || "";
    });
    const trash = this.capabilities.actions.trash;
    if (!trash.available && !this.pending) this.status.textContent = trash.reason;
    ComfyPresentation.imageActions({ buttons: this.buttons, capabilities: this.capabilities,
      status: this.status, pending: !!this.pending });
  }

  renderHeart(kept) {
    const button = this.buttons.get("keep");
    button.textContent = kept ? "♥" : "♡";
    button.setAttribute("aria-label", kept ? "Remove image from Favourites" : "Add image to Favourites");
    button.setAttribute("aria-pressed", String(!!kept));
    button.title = kept ? "Remove image from Favourites" : "Add image to Favourites";
  }

  async select(item) {
    const epoch = ++this.epoch;
    this.item = item ? { ...item } : null;
    this.capabilities = null;
    this.container.hidden = !item;
    this.status.textContent = "";
    this.unavailable.textContent = "";
    this.buttons.forEach((button) => { button.disabled = true; });
    if (!item) return;
    this.renderHeart(item.kept);
    try {
      const result = await this.api(`/api/images/${encodeURIComponent(item.id)}/actions`);
      if (epoch !== this.epoch) return;
      this.capabilities = result;
      this.item.kept = result.kept;
      this.renderHeart(result.kept);
      this.renderCapabilities();
      this.unavailable.textContent = ["edit", "upscale"].map((key) => result.actions[key]?.reason).filter(Boolean).join(" ");
    } catch (error) {
      if (epoch === this.epoch) this.status.textContent = error.message;
    }
  }

  async perform(action) {
    if (!this.item || this.pending) return;
    if (!this.capabilities?.actions[action]?.available) {
      ComfyPresentation.unavailableImageAction({ action, reason: this.capabilities?.actions[action]?.reason,
        status: this.status });
      return;
    }
    const item = { ...this.item }, capability = this.capabilities, epoch = this.epoch;
    if (action === "trash" && !confirm(`Move “${item.filename}” to Trash?${item.kept ? " This image is in Favourites." : ""} You can restore it from Gallery → Trash.`)) return;
    this.pending = true;
    this.buttons.forEach((button) => { button.disabled = true; });
    this.status.textContent = action === "trash" ? "Moving image to Trash…"
      : action === "edit" || action === "upscale" ? "Preparing image…" : "Saving…";
    try {
      if (action === "edit" || action === "upscale") {
        await this.workflow(item, action, capability.modified);
        if (epoch === this.epoch) this.status.textContent = "";
        return;
      }
      const result = await this.api(`/api/images/${encodeURIComponent(item.id)}/actions`, {
        method: "POST", body: JSON.stringify({ action, modified: capability.modified,
          ...(action === "keep" ? { keep: !item.kept } : { confirm: true }) }),
      });
      await this.changed(item, result);
    } catch (error) {
      if (epoch === this.epoch) this.status.textContent = error.message;
    } finally {
      this.pending = false;
      // select() may have advanced the epoch while the action refreshed the image.
      // Render the current capabilities so a fast response cannot leave it disabled.
      this.renderCapabilities();
    }
  }
}
