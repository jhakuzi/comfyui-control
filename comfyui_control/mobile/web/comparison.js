"use strict";

class ImageComparison {
  constructor({ api, notice, read, write, unauthorized }) {
    this.api = api;
    this.notice = notice;
    this.write = write;
    this.unauthorized = unauthorized;
    const saved = read("compare", {});
    this.selecting = !!saved.selecting;
    this.selected = Array.isArray(saved.selected) ? saved.selected.slice(0, 2) : [];
    this.items = [];
    this.metadata = new Map();
    // Only the selected pair lives in memory. Nothing private is written to
    // CacheStorage/localStorage; blob URLs work over ordinary LAN HTTP too.
    this.images = new Map();
    this.loading = null;
    this.epoch = 0;
    const el = (id) => document.getElementById(id);
    this.el = el;
    el("select-compare").addEventListener("click", () => {
      this.selecting = !this.selecting;
      this.update();
    });
    el("compare-images").addEventListener("click", () => this.open());
    el("retry-compare").addEventListener("click", () => this.open());
    el("close-compare").addEventListener("click", () => el("compare-dialog").close());
    el("compare-dialog").addEventListener("close", () => {
      this.epoch++;
      this.loading?.abort();
      el("compare-a").removeAttribute("src");
      el("compare-b").removeAttribute("src");
      const scroll = this.scroll || 0;
      requestAnimationFrame(() => window.scrollTo(0, scroll));
    });
    el("compare-slider").addEventListener("input", () => this.divider());
    el("reset-compare").addEventListener("click", () => {
      el("compare-slider").value = 50;
      this.divider();
    });
    el("swap-compare").addEventListener("click", async () => {
      this.selected.reverse();
      try { await this.render(); }
      catch { this.notice("Could not display the images. Close comparison and try again."); }
      this.update();
    });
    let pointer = null;
    const viewport = el("compare-viewport");
    const drag = (event) => {
      const rect = viewport.getBoundingClientRect();
      el("compare-slider").value = Math.max(0, Math.min(100, 100 * (event.clientX - rect.left) / rect.width));
      this.divider();
    };
    viewport.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || !event.isPrimary) return;
      event.preventDefault();
      pointer = event.pointerId;
      viewport.setPointerCapture(pointer);
      el("compare-slider").focus({ preventScroll: true });
      drag(event);
    });
    viewport.addEventListener("pointermove", (event) => {
      if (event.pointerId === pointer) drag(event);
    });
    const release = () => { pointer = null; };
    viewport.addEventListener("pointerup", release);
    viewport.addEventListener("pointercancel", release);
    viewport.addEventListener("lostpointercapture", release);
    for (const side of ["a", "b"]) {
      el("compare-" + side).addEventListener("load", () => {
        const images = [el("compare-a"), el("compare-b")];
        const ratios = images.filter((image) => image.naturalWidth).map((image) => image.naturalWidth / image.naturalHeight);
        if (ratios.length) viewport.style.aspectRatio = Math.max(...ratios);
      });
      el("compare-" + side).addEventListener("error", () => {
        if (!el("compare-dialog").open) return;
        el("compare-error").hidden = false;
        el("compare-error").textContent = "An image is unavailable or was deleted. Close comparison and refresh the gallery.";
      });
    }
    this.update();
  }

  gallery(items) {
    this.items = items;
    this.selected = this.selected.filter((id) => items.some((item) => item.id === id));
    this.update();
  }

  choose(item) {
    if (!this.selecting) return false;
    if (this.selected.includes(item.id)) this.selected = this.selected.filter((id) => id !== item.id);
    else if (this.selected.length < 2) this.selected.push(item.id);
    else this.notice("Select exactly two images. Deselect A or B to choose another.");
    this.update();
    return true;
  }

  update() {
    for (const [id, image] of this.images) {
      if (!this.selected.includes(id) || !this.items.some((item) => item.id === id && item.url === image.source)) {
        URL.revokeObjectURL(image.url);
        this.images.delete(id);
      }
    }
    for (const id of this.metadata.keys()) {
      if (!this.selected.includes(id)) this.metadata.delete(id);
    }
    this.el("select-compare").textContent = this.selecting ? "Done selecting" : "Select two images";
    this.el("select-compare").setAttribute("aria-pressed", String(this.selecting));
    this.el("compare-images").textContent = `Compare · ${this.selected.length}/2`;
    this.el("compare-images").disabled = this.selected.length !== 2;
    for (const button of this.el("gallery-grid").querySelectorAll("button[data-image-id]")) {
      const index = this.selected.indexOf(button.dataset.imageId);
      button.classList.toggle("comparison-selected", this.selecting && index >= 0);
      button.dataset.comparisonLabel = index === 0 ? "A" : "B";
      if (this.selecting) button.setAttribute("aria-pressed", String(index >= 0));
      else button.removeAttribute("aria-pressed");
    }
    this.write("compare", { selecting: this.selecting, selected: this.selected });
  }

  async open() {
    if (this.selected.length !== 2) return;
    const epoch = ++this.epoch;
    this.loading?.abort();
    const controller = this.loading = new AbortController();
    const ids = [...this.selected];
    if (!this.el("compare-dialog").open) this.scroll = window.scrollY;
    this.el("compare-slider").value = 50;
    this.divider();
    this.el("compare-error").hidden = true;
    this.el("retry-compare").hidden = true;
    this.el("compare-viewport").hidden = true;
    for (const id of ["compare-slider", "swap-compare", "reset-compare"]) this.el(id).disabled = true;
    const status = this.el("compare-loading");
    status.hidden = false;
    let ready = 0;
    status.textContent = "Loading images · 0/2 ready…";
    if (!this.el("compare-dialog").open) {
      this.el("compare-dialog").showModal();
      this.el("compare-dialog").scrollTop = 0;
    }
    this.renderParameters();
    // Metadata is optional and must never delay a cached/offline comparison.
    void Promise.all(ids.map(async (id) => {
      if (this.metadata.has(id)) return;
      let fields;
      try { fields = await this.api(`/api/images/${id}/parameters`); }
      catch { return; }
      if (epoch !== this.epoch) return;
      this.metadata.set(id, fields);
      this.renderParameters();
    }));
    const timeout = setTimeout(() => controller.abort(), 120000);
    try {
      const results = await Promise.allSettled(ids.map(async (id) => {
        const item = this.items.find((item) => item.id === id);
        if (!item) throw new Error("An image is no longer in the gallery. Refresh the gallery and select it again.");
        await this.loadImage(item, controller.signal);
        if (epoch === this.epoch) status.textContent = `Loading images · ${++ready}/2 ready…`;
      }));
      if (epoch !== this.epoch) return;
      const failure = results.find((result) => result.status === "rejected");
      if (failure) throw failure.reason;
      await this.render();
      if (epoch !== this.epoch) return;
      this.el("compare-viewport").hidden = false;
      for (const id of ["compare-slider", "swap-compare", "reset-compare"]) this.el(id).disabled = false;
      status.textContent = "Ready to compare";
    } catch (error) {
      if (epoch !== this.epoch) return;
      this.el("compare-error").textContent = error.message || "Could not load both images.";
      this.el("compare-error").hidden = false;
      this.el("retry-compare").hidden = false;
      status.textContent = `${ready}/2 images ready. Retry keeps the images already loaded.`;
    } finally {
      clearTimeout(timeout);
      if (this.loading === controller) this.loading = null;
    }
  }

  async loadImage(item, signal) {
    if (this.images.has(item.id)) return;
    let url;
    let failure = "Could not finish loading both images. Check your connection and retry.";
    try {
      const response = await fetch(item.url, { credentials: "same-origin", cache: "no-store", signal });
      if (response.status === 401) {
        failure = "Sign in again to load these images.";
        this.unauthorized?.();
        throw new Error(failure);
      }
      if (response.status === 404) failure = "An image is unavailable or was deleted. Refresh the gallery and select another image.";
      if (!response.ok) throw new Error(failure);
      const blob = await response.blob();
      if (signal.aborted) throw new Error();
      url = URL.createObjectURL(blob);
      const image = new Image();
      image.src = url;
      await image.decode();
      if (signal.aborted) throw new Error();
      if (!this.selected.includes(item.id) || !this.items.some((entry) => entry.id === item.id && entry.url === item.url)) {
        failure = "An image is no longer in the gallery. Refresh the gallery and select it again.";
        throw new Error(failure);
      }
      this.images.set(item.id, { url, source: item.url });
    } catch {
      if (url) URL.revokeObjectURL(url);
      throw new Error(failure);
    }
  }

  clearImages() {
    this.epoch++;
    this.loading?.abort();
    for (const image of this.images.values()) URL.revokeObjectURL(image.url);
    this.images.clear();
    this.metadata.clear();
    for (const side of ["a", "b"]) this.el("compare-" + side).removeAttribute("src");
  }

  divider() {
    const value = this.el("compare-slider").value;
    this.el("compare-viewport").style.setProperty("--split", value + "%");
    this.el("compare-slider").setAttribute("aria-valuetext", `${value}% image A`);
  }

  async render() {
    if (this.selected.length !== 2 || this.selected.some((id) => !this.images.has(id)))
      throw new Error("The image selection changed. Close comparison and select two images again.");
    this.selected.forEach((id, index) => {
      const item = this.items.find((item) => item.id === id);
      const image = this.images.get(id);
      if (item && image) this.el(index ? "compare-b" : "compare-a").src = image.url;
    });
    await Promise.all(["a", "b"].map((side) => this.el("compare-" + side).decode()));
    this.renderParameters();
  }

  renderParameters() {
    const lists = this.selected.map((id) => this.metadata.get(id) || []);
    const keys = [...new Set(lists.flatMap((list) => list.map((field) => field.key)))];
    const body = this.el("compare-parameters");
    body.replaceChildren();
    if (!keys.length) {
      const row = body.insertRow();
      const cell = row.insertCell();
      cell.colSpan = 3;
      cell.textContent = "Generation metadata is unavailable for these images.";
      return;
    }
    for (const key of keys) {
      const fields = lists.map((list) => list.find((field) => field.key === key));
      const row = body.insertRow();
      const label = document.createElement("th");
      label.scope = "row";
      label.textContent = (fields[0] || fields[1]).label;
      row.append(label);
      const values = fields.map((field) => field ? String(field.value) : "--");
      row.classList.toggle("parameter-difference", values[0] !== values[1]);
      for (const value of values) row.insertCell().textContent = value;
    }
  }
}
