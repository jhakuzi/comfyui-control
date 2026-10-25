"use strict";

/* Shared transient Gallery selection. Reuse the controller's image-action transport
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
    this.toggle.innerHTML = '<svg class="gallery-select-icon" viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="3"/><path d="m8 12 3 3 5-6"/></svg><span class="gallery-select-label"></span>';
    this.toggleLabel = this.toggle.querySelector("span");
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
    this.controls.innerHTML = '<span class="gallery-bulk-count" aria-live="polite"></span><span class="hint gallery-bulk-help">Right-click a selected image for actions.</span><p class="hint gallery-bulk-status" role="status"></p>';
    this.selectCompare.parentElement.after(this.controls);
    this.count = this.controls.querySelector("span");
    this.status = this.controls.querySelector("p");
    this.menu = document.createElement("div");
    this.menu.id = "gallery-selection-menu";
    this.menu.hidden = true;
    this.menu.setAttribute("role", "menu");
    this.menu.setAttribute("aria-label", "Selected image actions");
    this.menu.innerHTML = '<button id="favourite-gallery-selected" type="button" role="menuitem" tabindex="-1">Favourite selected</button><button id="delete-gallery-selected" type="button" role="menuitem" tabindex="-1" class="danger">Delete selected</button>';
    document.body.append(this.menu);
    this.keepButton = this.menu.querySelector("#favourite-gallery-selected");
    this.deleteButton = this.menu.querySelector("#delete-gallery-selected");
    this.keepButton.addEventListener("click", () => { this.closeMenu(true); this.suppressClick = null; this.perform("keep"); });
    this.deleteButton.addEventListener("click", () => { this.closeMenu(true); this.suppressClick = null; this.perform("delete"); });
    grid.addEventListener("contextmenu", (event) => {
      const button = event.target.closest("button[data-image-id]");
      if (!button || !this.canOpenMenu(button)) return;
      event.preventDefault();
      if (!this.media.matches) {
        this.cancelPress();
        this.suppressClick = { button, until: performance.now() + 1000 };
      }
      this.openMenu(button, event.clientX, event.clientY);
    });
    grid.addEventListener("pointerdown", (event) => {
      this.cancelPress();
      if (this.media.matches || event.pointerType !== "touch" || !event.isPrimary) return;
      const button = event.target.closest("button[data-image-id]");
      if (!button || !this.canOpenMenu(button)) return;
      const press = this.press = { id: event.pointerId, button, x: event.clientX, y: event.clientY };
      press.timer = setTimeout(() => {
        if (this.press !== press) return;
        this.cancelPress();
        if (!this.canOpenMenu(button)) return;
        this.suppressClick = { button, until: performance.now() + 1000 };
        this.openMenu(button, press.x, press.y);
      }, 550);
    }, { passive: true });
    grid.addEventListener("pointermove", (event) => {
      if (this.press && event.pointerId === this.press.id &&
          Math.hypot(event.clientX - this.press.x, event.clientY - this.press.y) > 10) this.cancelPress();
    }, { passive: true });
    for (const name of ["pointerup", "pointercancel"]) document.addEventListener(name, () => this.cancelPress(), { passive: true });
    grid.addEventListener("click", (event) => {
      if (this.suppressClick?.button.contains(event.target) && performance.now() <= this.suppressClick.until) {
        this.suppressClick = null;
        event.preventDefault();
        event.stopImmediatePropagation(); // The release after a hold must not deselect the image.
      }
    }, true);
    grid.addEventListener("keydown", (event) => {
      if (event.key !== "ContextMenu" && !(event.shiftKey && event.key === "F10")) return;
      const button = event.target.closest("button[data-image-id]");
      if (!button || !this.canOpenMenu(button)) return;
      event.preventDefault();
      const rect = button.getBoundingClientRect();
      this.openMenu(button, rect.left + 8, rect.top + 8);
    });
    this.menu.addEventListener("contextmenu", (event) => event.preventDefault());
    this.menu.addEventListener("keydown", (event) => {
      const buttons = [this.keepButton, this.deleteButton];
      if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
        event.preventDefault();
        const index = buttons.indexOf(document.activeElement);
        buttons[event.key === "Home" ? 0 : event.key === "End" ? 1 : (index + (event.key === "ArrowUp" ? -1 : 1) + buttons.length) % buttons.length].focus();
      } else if (event.key === "Escape") {
        event.preventDefault();
        event.stopPropagation();
        this.closeMenu(true);
      } else if (event.key === "Tab") this.closeMenu(true);
    });
    document.addEventListener("pointerdown", (event) => {
      if (this.press && event.pointerId !== this.press.id) this.cancelPress();
      if (!this.menu.contains(event.target)) this.closeMenu();
    }, true);
    document.addEventListener("scroll", (event) => {
      this.cancelPress();
      if (!this.menu.contains(event.target)) this.closeMenu(true);
    }, true);
    window.addEventListener("resize", () => { this.cancelPress(); this.closeMenu(true); });
    this.selectCompare.addEventListener("click", () => this.reset(), true);
    this.compareButton.addEventListener("click", () => this.reset(), true);
    this.render();
  }

  cancelPress() {
    if (this.press) clearTimeout(this.press.timer);
    this.press = null;
  }

  reset() {
    this.cancelPress();
    this.suppressClick = null;
    this.closeMenu();
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
      else {
        this.selected.delete(id);
        this.closeMenu(true);
      }
    }
    this.render();
  }

  choose(item) {
    if (!this.selecting) return false;
    if (!this.pending && this.canAct()) {
      if (this.selected.has(item.id)) this.selected.delete(item.id);
      else this.selected.set(item.id, { ...item });
      this.status.textContent = "";
      this.render();
    }
    return true;
  }

  canOpenMenu(button) {
    return this.selecting && !this.pending && !this.confirming && this.canAct() &&
      this.grid.contains(button) && this.selected.has(button.dataset.imageId);
  }

  openMenu(button, x, y) {
    if (!this.canOpenMenu(button)) return;
    this.menuAnchor = button;
    this.menu.hidden = false;
    this.menu.style.left = this.menu.style.top = "0px";
    const rect = this.menu.getBoundingClientRect();
    this.menu.style.left = `${Math.max(8, Math.min(x, window.innerWidth - rect.width - 8))}px`;
    this.menu.style.top = `${Math.max(8, Math.min(y, window.innerHeight - rect.height - 8))}px`;
    this.keepButton.focus({ preventScroll: true });
  }

  closeMenu(restoreFocus = false) {
    if (!this.menu || this.menu.hidden) return;
    this.menu.hidden = true;
    if (restoreFocus && this.menuAnchor?.isConnected) this.menuAnchor.focus({ preventScroll: true });
    this.menuAnchor = null;
  }

  render() {
    this.toggleLabel.textContent = this.selecting ? "Done selecting" : "Select";
    this.toggle.setAttribute("aria-label", this.selecting ? "Done selecting images" : "Select images");
    this.toggle.title = this.selecting ? "Done selecting images" : "Select images";
    this.toggle.setAttribute("aria-pressed", String(this.selecting));
    this.toggle.disabled = this.pending || !this.canAct();
    this.controls.hidden = !this.selecting;
    this.controls.setAttribute("aria-busy", String(this.pending));
    this.count.textContent = `${this.selected.size} selected`;
    this.keepButton.disabled = this.deleteButton.disabled = this.pending || !this.selected.size || !this.canAct();
    this.menu.setAttribute("aria-label", `Actions for ${this.selected.size} selected images`);
    if (!this.selecting || this.pending || this.confirming || !this.selected.size || !this.canAct()) {
      this.cancelPress();
      this.closeMenu();
    }
    this.grid.classList.toggle("gallery-multi-select", this.selecting);
    this.selectCompare.disabled = this.pending;
    this.compareButton.disabled = this.pending || this.selecting || this.comparison.selected.length !== 2;
    for (const button of this.grid.querySelectorAll("button[data-image-id]")) {
      const selected = this.selecting && this.selected.has(button.dataset.imageId);
      button.classList.toggle("gallery-bulk-selected", selected);
      if (this.selecting) button.setAttribute("aria-pressed", String(selected));
      else if (!this.comparison.selecting) button.removeAttribute("aria-pressed");
      if (selected) {
        button.setAttribute("aria-haspopup", "menu");
        button.setAttribute("aria-controls", this.menu.id);
        button.setAttribute("aria-keyshortcuts", "Shift+F10");
      } else {
        button.removeAttribute("aria-haspopup");
        button.removeAttribute("aria-controls");
        button.removeAttribute("aria-keyshortcuts");
      }
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
