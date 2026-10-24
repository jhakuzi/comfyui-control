"use strict";

/* A transient collection view. Image selection, actions, gallery transport and
   generation state stay in the existing controller and shared renderer. */
window.ComfyGalleryLibrary = class GalleryLibrary {
  constructor({ load, renderImages, openImage }) {
    Object.assign(this, { load, renderImages, openImage });
    this.epoch = 0;
    this.items = [];
    const refresh = document.getElementById("refresh-gallery");
    const tools = document.createElement("div");
    tools.className = "gallery-library-tools";
    refresh.before(tools);
    tools.append(refresh);
    const icons = {
      wastebin: '<path d="M4 7h16M9 7V4h6v3M6 7l1 14h10l1-14M10 11v6m4-6v6"/>',
      favourites: '<path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z"/>',
    };
    for (const [mode, label] of [["wastebin", "Wastebin"], ["favourites", "Favourites"]]) {
      const button = document.createElement("button");
      button.id = `gallery-${mode}`;
      button.type = "button";
      button.className = "small";
      button.title = label;
      button.setAttribute("aria-label", label);
      button.setAttribute("aria-haspopup", "dialog");
      button.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[mode]}</svg>`;
      button.addEventListener("click", () => this.open(mode));
      tools.append(button);
    }
    this.dialog = document.createElement("dialog");
    this.dialog.id = "gallery-library-dialog";
    this.dialog.setAttribute("aria-labelledby", "gallery-library-title");
    this.dialog.innerHTML = '<div class="heading"><h2 id="gallery-library-title"></h2><div class="gallery-library-tools"><button id="refresh-gallery-library" type="button" class="small">Refresh</button><button id="close-gallery-library" type="button" class="small">Close</button></div></div><p class="hint gallery-library-status" role="status"></p><div class="image-grid"></div><div class="gallery-library-deleted" hidden><img alt="Deleted image preview"/><p class="hint"></p><button type="button">Back to Wastebin</button></div>';
    document.body.append(this.dialog);
    this.title = this.dialog.querySelector("h2");
    this.status = this.dialog.querySelector('[role="status"]');
    this.grid = this.dialog.querySelector(".image-grid");
    this.detail = this.dialog.querySelector(".gallery-library-deleted");
    this.detailImage = this.detail.querySelector("img");
    this.detailText = this.detail.querySelector("p");
    this.refreshButton = this.dialog.querySelector("#refresh-gallery-library");
    this.refreshButton.addEventListener("click", () => this.refresh());
    this.dialog.querySelector("#close-gallery-library").addEventListener("click", () => this.close());
    this.detail.querySelector("button").addEventListener("click", () => this.showGrid());
    this.detailImage.addEventListener("error", () => {
      if (!this.dialog.open || this.detail.hidden) return;
      this.status.textContent = "Preview unavailable. The Wastebin entry is still listed.";
    });
    this.dialog.addEventListener("close", () => {
      if (this.dialog.open) return;
      this.epoch++;
      this.loading = false;
      this.grid.getAnimations({ subtree: true }).forEach((animation) => animation.cancel());
      this.grid.replaceChildren();
      delete this.grid.dataset.signature;
      this.detailImage.removeAttribute("src");
      this.items = [];
    });
  }

  close() {
    this.epoch++;
    if (this.dialog.open) this.dialog.close();
  }

  async open(mode) {
    this.mode = mode;
    this.title.textContent = mode === "favourites" ? "Favourites" : "Wastebin";
    this.items = [];
    this.grid.replaceChildren();
    delete this.grid.dataset.signature;
    this.showGrid();
    this.dialog.showModal();
    await this.refresh();
  }

  showGrid() {
    this.detail.hidden = true;
    this.detailImage.removeAttribute("src");
    this.grid.hidden = false;
    this.render();
  }

  async refresh() {
    if (!this.dialog.open || document.hidden) return;
    const epoch = ++this.epoch, mode = this.mode;
    this.loading = true;
    this.grid.inert = true;
    this.refreshButton.disabled = true;
    this.status.textContent = "Loading images…";
    try {
      const items = await this.load(mode);
      if (!this.dialog.open || epoch !== this.epoch) return;
      this.items.splice(0, this.items.length, ...items);
      this.showGrid();
    } catch (error) {
      if (this.dialog.open && epoch === this.epoch) this.status.textContent = `${error.message} Use Refresh to try again.`;
    } finally {
      if (epoch === this.epoch) {
        this.loading = false;
        this.grid.inert = false;
        this.refreshButton.disabled = false;
      }
    }
  }

  changed(item, result) {
    if (!this.dialog.open) return;
    if (this.loading) { void this.refresh(); return; }
    if (this.mode !== "favourites") return;
    const index = this.items.findIndex((entry) => entry.id === item.id);
    if (result.trash || !result.kept) {
      if (index >= 0) this.items.splice(index, 1);
    } else if (index < 0) this.items.unshift({ ...item, kept: true });
    this.render();
  }

  render() {
    this.status.textContent = this.items.length ? "" : this.mode === "favourites"
      ? "No favourites yet. Mark an image with a heart to find it here."
      : "Wastebin is empty.";
    this.renderImages(this.grid, this.items, (item) => {
      if (this.mode === "favourites") {
        const index = this.items.findIndex((entry) => entry.id === item.id);
        if (index >= 0) this.openImage(this.items, index);
      } else {
        this.grid.hidden = true;
        this.detail.hidden = false;
        this.detailImage.src = item.url;
        this.detailText.textContent = [item.filename, item.error, item.notice].filter(Boolean).join(" · ");
        this.status.textContent = "Deleted image thumbnail preview";
      }
    });
  }
};
