"use strict";

class ImageComparison {
  constructor({ api, notice, read, write }) {
    this.api = api;
    this.notice = notice;
    this.write = write;
    const saved = read("compare", {});
    this.selecting = !!saved.selecting;
    this.selected = Array.isArray(saved.selected) ? saved.selected.slice(0, 2) : [];
    this.items = [];
    this.metadata = new Map();
    this.epoch = 0;
    const el = (id) => document.getElementById(id);
    this.el = el;
    el("select-compare").addEventListener("click", () => {
      this.selecting = !this.selecting;
      this.update();
    });
    el("compare-images").addEventListener("click", () => this.open());
    el("close-compare").addEventListener("click", () => el("compare-dialog").close());
    el("compare-dialog").addEventListener("close", () => {
      this.epoch++;
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
    el("swap-compare").addEventListener("click", () => {
      this.selected.reverse();
      this.render();
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
    this.scroll = window.scrollY;
    this.el("compare-slider").value = 50;
    this.divider();
    this.el("compare-error").hidden = true;
    this.el("compare-dialog").showModal();
    this.metadata.clear();
    this.render();
    await Promise.all(this.selected.map(async (id) => {
      let fields;
      try { fields = await this.api(`/api/images/${id}/parameters`); }
      catch { fields = []; }
      if (epoch !== this.epoch) return;
      this.metadata.set(id, fields);
      this.renderParameters();
    }));
  }

  divider() {
    const value = this.el("compare-slider").value;
    this.el("compare-viewport").style.setProperty("--split", value + "%");
    this.el("compare-slider").setAttribute("aria-valuetext", `${value}% image A`);
  }

  render() {
    this.selected.forEach((id, index) => {
      const item = this.items.find((item) => item.id === id);
      if (item) this.el(index ? "compare-b" : "compare-a").src = item.url;
    });
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
