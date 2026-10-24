"use strict";

/* A transient collection view. Image selection, actions, gallery transport and
   generation state stay in the existing controller and shared renderer. */
window.ComfyGalleryLibrary = class GalleryLibrary {
  constructor({ load, renderImages, openImage, empty }) {
    Object.assign(this, { load, renderImages, openImage, empty });
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
    this.dialog.innerHTML = '<div class="heading"><h2 id="gallery-library-title"></h2><div class="gallery-library-tools"><button id="clear-gallery-bin" type="button" class="small danger" hidden>Clear Bin</button><button id="refresh-gallery-library" type="button" class="small">Refresh</button><button id="close-gallery-library" type="button" class="small">Close</button></div></div><p class="hint gallery-library-status" role="status"></p><div class="image-grid"></div><div class="gallery-library-deleted" hidden><img alt="Deleted image preview"/><p class="hint"></p><button type="button">Back to Wastebin</button></div>';
    document.body.append(this.dialog);
    this.title = this.dialog.querySelector("h2");
    this.status = this.dialog.querySelector('[role="status"]');
    this.grid = this.dialog.querySelector(".image-grid");
    this.detail = this.dialog.querySelector(".gallery-library-deleted");
    this.detailImage = this.detail.querySelector("img");
    this.detailText = this.detail.querySelector("p");
    this.refreshButton = this.dialog.querySelector("#refresh-gallery-library");
    this.clearButton = this.dialog.querySelector("#clear-gallery-bin");
    this.clearButton.addEventListener("click", () => this.clearBin());
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
    this.loading = true;
    this.status.textContent = "";
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
    this.syncControls();
    this.status.textContent = "";
    try {
      const items = await this.load(mode);
      if (!this.dialog.open || epoch !== this.epoch) return;
      this.items.splice(0, this.items.length, ...items);
      this.loading = false;
      this.showGrid();
      return true;
    } catch (error) {
      if (this.dialog.open && epoch === this.epoch) this.status.textContent = `${error.message} Use Refresh to try again.`;
      return false;
    } finally {
      if (epoch === this.epoch) {
        this.loading = false;
        this.syncControls();
      }
    }
  }

  syncControls() {
    const busy = !!this.loading || !!this.clearing;
    this.grid.inert = busy;
    this.refreshButton.disabled = busy;
    this.clearButton.hidden = this.mode !== "wastebin";
    this.clearButton.disabled = busy || !this.items.length;
    this.dialog.setAttribute("aria-busy", String(busy));
    this.refreshButton.setAttribute("aria-label", this.loading ? "Refreshing images" : "Refresh images");
  }

  async clearBin() {
    if (this.mode !== "wastebin" || this.loading || this.clearing || !this.items.length) return;
    // Snapshot before confirmation. Newly binned images are never added to it.
    const tokens = this.items.map((item) => item.token);
    if (!confirm(`Permanently delete ${tokens.length} image${tokens.length === 1 ? "" : "s"} from Wastebin? This removes the original files and cannot be undone.`)) return;
    const epoch = ++this.epoch;
    this.clearing = true;
    this.status.textContent = "Deleting images…";
    this.syncControls();
    try {
      const result = await this.empty(tokens);
      if (!this.dialog.open || epoch !== this.epoch) return;
      if (!Array.isArray(result?.results)) throw new Error("Deletion could not be confirmed. Refresh Wastebin before retrying.");
      const deleted = new Set(result.results.filter((entry) => entry.deleted === true).map((entry) => entry.token));
      const failures = result.results.filter((entry) => entry.error);
      this.items.splice(0, this.items.length, ...this.items.filter((item) => !deleted.has(item.token)));
      this.clearing = false;
      this.showGrid();
      const nextEpoch = this.epoch + 1;
      const refreshed = await this.refresh();
      if (!refreshed || !this.dialog.open || this.epoch !== nextEpoch) return;
      this.status.textContent = failures.length
        ? `${failures.length} image${failures.length === 1 ? "" : "s"} could not be deleted. ${failures[0].error}`
        : this.items.length ? `Deleted ${deleted.size} images. ${this.items.length} remain in Wastebin.` : "Wastebin is empty.";
    } catch (error) {
      if (this.dialog.open && epoch === this.epoch)
        this.status.textContent = `${error.message} Use Refresh to check Wastebin before retrying.`;
    } finally {
      this.clearing = false;
      this.syncControls();
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
    this.status.textContent = this.loading || this.clearing || this.items.length ? "" : this.mode === "favourites"
      ? "No favourites yet. Mark an image with a heart to find it here."
      : "Wastebin is empty.";
    this.syncControls();
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
