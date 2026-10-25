"use strict";

/* Desktop-only transient selection. Reuse the controller's image-action transport
   and confirmed-result reconciliation; never persist a second image library. */
window.ComfyGalleryBulk = class GalleryBulk {
  constructor({ grid, comparison, media, canAct, mutating, act, changed, finished, confirmAction }) {
    Object.assign(this, { grid, comparison, media, canAct, mutating, act, changed, finished, confirmAction });
    this.selected = new Map();
    this.epoch = 0;
    this.selecting = false;
    this.pending = false;
    this.items = [];
    this.toggle = document.createElement("button");
    this.toggle.id = "select-gallery-images";
    this.toggle.type = "button";
    this.toggle.dataset.desktopSlot = "";
    this.toggle.setAttribute("aria-controls", grid.id);
    this.toggle.addEventListener("click", () => {
      if (this.pending || !this.canAct()) return;
      if (this.selecting) this.reset();
      else {
        comparison.selecting = false;
        comparison.update();
        this.selecting = true;
        this.status.textContent = "";
        this.render();
      }
    });
    this.selectCompare = document.getElementById("select-compare");
    this.compareButton = document.getElementById("compare-images");
    this.selectCompare.after(this.toggle);
    this.controls = document.createElement("div");
    this.controls.className = "actions gallery-bulk-actions";
    this.controls.dataset.desktopSlot = "";
    this.controls.setAttribute("role", "group");
    this.controls.setAttribute("aria-label", "Selected image actions");
    this.controls.innerHTML = '<span class="gallery-bulk-count" aria-live="polite"></span><button id="favourite-gallery-selected" type="button">Favourite selected</button><button id="delete-gallery-selected" type="button" class="danger">Delete selected</button><p class="hint gallery-bulk-status" role="status"></p>';
    this.selectCompare.parentElement.after(this.controls);
    this.count = this.controls.querySelector("span");
    this.status = this.controls.querySelector("p");
    this.keepButton = this.controls.querySelector("#favourite-gallery-selected");
    this.deleteButton = this.controls.querySelector("#delete-gallery-selected");
    this.keepButton.addEventListener("click", () => this.perform("keep"));
    this.deleteButton.addEventListener("click", () => this.perform("delete"));
    this.selectCompare.addEventListener("click", () => this.reset(), true);
    this.compareButton.addEventListener("click", () => this.reset(), true);
    this.render();
  }

  reset() {
    this.epoch++;
    this.selecting = false;
    this.selected.clear();
    this.status.textContent = "";
    this.render();
  }

  gallery(items) {
    this.items = items;
    for (const [id, selected] of this.selected) {
      const current = items.find((item) => item.id === id && item.modified === selected.modified);
      if (current) this.selected.set(id, { ...current });
      else this.selected.delete(id);
    }
    this.render();
  }

  choose(item) {
    if (!this.selecting || !this.media.matches) return false;
    if (!this.pending && this.canAct()) {
      if (this.selected.has(item.id)) this.selected.delete(item.id);
      else this.selected.set(item.id, { ...item });
      this.status.textContent = "";
      this.render();
    }
    return true;
  }

  render() {
    this.toggle.hidden = !this.media.matches;
    this.toggle.textContent = this.selecting ? "Done selecting" : "Select";
    this.toggle.setAttribute("aria-pressed", String(this.selecting));
    this.toggle.disabled = this.pending || !this.canAct();
    this.controls.hidden = !this.selecting || !this.media.matches;
    this.controls.setAttribute("aria-busy", String(this.pending));
    this.count.textContent = `${this.selected.size} selected`;
    this.keepButton.disabled = this.deleteButton.disabled = this.pending || !this.selected.size || !this.canAct();
    this.selectCompare.disabled = this.pending;
    this.compareButton.disabled = this.pending || this.selecting || this.comparison.selected.length !== 2;
    for (const button of this.grid.querySelectorAll("button[data-image-id]")) {
      const selected = this.selecting && this.selected.has(button.dataset.imageId);
      button.classList.toggle("gallery-bulk-selected", selected);
      if (this.selecting) button.setAttribute("aria-pressed", String(selected));
      else if (!this.comparison.selecting) button.removeAttribute("aria-pressed");
    }
  }

  async perform(action) {
    if (!this.selecting || this.pending || this.confirming || !this.selected.size || !this.canAct()) return;
    // Capture the exact image versions before confirming; later selections and
    // refreshed/replaced images can never be added to this operation.
    const snapshot = [...this.selected.values()].map((item) => ({ ...item }));
    const epoch = this.epoch;
    if (action === "delete") {
      this.confirming = true;
      let confirmed;
      try {
        confirmed = await this.confirmAction({ title: "Move selected images to Wastebin?", accept: "Delete selected",
          message: `Move ${snapshot.length} selected image${snapshot.length === 1 ? "" : "s"} to Wastebin?${snapshot.some((item) => item.kept) ? " This includes favourites." : ""} Original files stay in place.`,
          current: () => this.epoch === epoch && this.canAct(),
        });
      } finally { this.confirming = false; }
      if (!confirmed) return;
    }
    if (!this.canAct() || this.epoch !== epoch) return;
    let completed = 0, uncertain = false;
    const failures = [];
    this.pending = true;
    this.mutating();
    this.render();
    try {
      for (const [index, item] of snapshot.entries()) {
        if (epoch !== this.epoch || !this.canAct()) break;
        if (this.selected.get(item.id)?.modified !== item.modified) {
          failures.push(`${item.filename}: removed or replaced; select it again.`);
          continue;
        }
        this.status.textContent = `${action === "keep" ? "Favouriting" : "Moving to Wastebin"} ${index + 1} of ${snapshot.length}…`;
        try {
          const result = await this.act(item, action);
          if (result?.image_id !== item.id || (action === "keep" ? result.kept !== true : !result.trash))
            throw new Error("Invalid image-action response.");
          if (epoch !== this.epoch) break;
          await this.changed(item, result);
          this.selected.delete(item.id);
          completed++;
        } catch (error) {
          if (epoch !== this.epoch) break;
          failures.push(`${item.filename}: ${error.message}`);
          if (![400, 403, 404, 409, 413, 415, 422].includes(error.status)) {
            uncertain = true;
            break; // A lost response may have succeeded; never retry it automatically.
          }
        }
        if (epoch === this.epoch) this.render();
      }
    } finally {
      this.pending = false;
      if (epoch === this.epoch) {
        const remaining = this.selected.size;
        this.status.textContent = `${completed} image${completed === 1 ? "" : "s"} ${action === "keep" ? "added to Favourites" : "moved to Wastebin"}.${remaining ? ` ${remaining} remain selected.` : ""}${failures.length ? " " + failures.slice(0, 3).join(" ") : ""}${uncertain ? " Refresh Gallery to check the result before retrying." : ""}`;
      }
      this.finished(action, completed, epoch === this.epoch);
      this.render();
    }
  }
};
