"use strict";

class ImageDetails {
  constructor({ api }) {
    this.api = api;
    this.item = null;
    this.epoch = 0;
    this.loaded = false;
    this.loading = false;
    this.el = (id) => document.getElementById(id);
    this.copyButton = this.el("copy-image-prompt");
    this.copyStatus = this.el("copy-prompt-status");
    this.el("image-details").addEventListener("toggle", () => {
      if (this.el("image-details").open) this.load();
    });
    this.el("image-dialog").addEventListener("close", () => {
      // A resize can move these same controls into the desktop preview before
      // the old dialog's close event is delivered.
      if (this.el("image-dialog").contains(this.el("image-details"))) this.select(null);
    });
    this.copyButton.addEventListener("click", async () => {
      try {
        let copied = false;
        if (navigator.clipboard?.writeText && window.isSecureContext) {
          try {
            await navigator.clipboard.writeText(this.positive);
            copied = true;
          } catch {}
        }
        if (!copied) {
          // Clipboard API needs HTTPS; selection copying also works on LAN HTTP.
          const text = document.createElement("textarea");
          text.value = this.positive;
          text.readOnly = true;
          text.className = "clipboard-text";
          this.el("image-details").append(text);
          text.focus({ preventScroll: true });
          text.select();
          text.setSelectionRange(0, text.value.length);
          copied = document.execCommand("copy");
          text.remove();
          if (!copied) throw new Error();
        }
        this.copyStatus.textContent = "Prompt copied.";
      } catch {
        this.copyStatus.textContent = "Copy is unavailable. Select the prompt text to copy it.";
      }
    });
  }

  select(item) {
    this.epoch++;
    this.item = item;
    this.loaded = this.loading = false;
    this.positive = "";
    this.copyButton.disabled = true;
    this.copyStatus.textContent = "";
    this.copyButton.remove();
    this.copyStatus.remove();
    this.el("image-metadata").textContent = item ? "Loading saved details…" : "";
    if (item && this.el("image-details").open) this.load();
  }

  async load() {
    if (!this.item || this.loaded || this.loading) return;
    const epoch = this.epoch;
    this.loading = true;
    try {
      const data = await this.api(`/api/images/${this.item.id}/details`);
      if (epoch !== this.epoch) return;
      this.loaded = true;
      this.render(data);
    } catch (error) {
      if (epoch === this.epoch) this.el("image-metadata").textContent = error.message + " Reopen Details to try again.";
    } finally {
      if (epoch === this.epoch) this.loading = false;
    }
  }

  render(data) {
    const root = this.el("image-metadata");
    root.replaceChildren();
    const el = (tag, text, cls) => {
      const item = document.createElement(tag);
      if (text !== undefined) item.textContent = text;
      if (cls) item.className = cls;
      return item;
    };
    if (data.restricted) {
      root.append(el("p", "Generation details are unavailable for this browser session.", "hint"));
      return;
    }
    const section = (title, open = true) => {
      const details = el("details", undefined, "metadata-card");
      details.open = open;
      details.append(el("summary", title));
      root.append(details);
      return details;
    };
    const rows = (target, fields) => {
      const list = el("dl", undefined, "metadata-list");
      for (const field of fields) list.append(el("dt", field.label), el("dd", String(field.value)));
      target.append(list);
    };
    const prompts = [...(data.positive || []), ...(data.negative || [])];
    if (prompts.length) {
      const target = section("Prompts");
      const tools = el("div", undefined, "metadata-prompt-tools");
      tools.append(this.copyStatus, this.copyButton);
      target.append(tools);
      for (const [role, title] of [["positive", "Positive prompt"], ["negative", "Negative prompt"]]) {
        const fields = data[role] || [];
        fields.forEach((field, index) => {
          target.append(el("h3", fields.length > 1 ? field.label : title));
          target.append(el("p", field.value || "(Empty)", "metadata-prompt"));
        });
      }
    }
    this.positive = (data.positive || []).map((field) => field.value).join("\n\n");
    this.copyButton.disabled = !this.positive;
    const modelRoles = new Set(["model", "diffusion_model", "vae", "text_encoder", "lora_model", "lora_strength"]);
    const fields = data.parameters || [];
    const models = fields.filter((field) => modelRoles.has(field.key.split(":")[0]) &&
      (!data.loras?.length || !field.key.startsWith("lora_")));
    const common = fields.filter((field) => !modelRoles.has(field.key.split(":")[0]));
    if (data.image) common.unshift({ label: "Image resolution", value: `${data.image.width} × ${data.image.height}` });
    if (common.length) rows(section("Generation"), common);
    if (models.length || data.loras?.length) {
      const target = section("Models & LoRAs", false);
      if (models.length) rows(target, models);
      for (const lora of data.loras || []) {
        target.append(el("h3", String(lora.name)));
        rows(target, lora.fields);
      }
    }
    if (data.additional?.length) rows(section("Additional parameters", false), data.additional);
    if (!prompts.length && !fields.length && !data.additional?.length)
      root.append(el("p", data.unavailable ? "This image is unavailable or was deleted." : "No generation metadata was saved with this image.", "hint"));
  }
}
