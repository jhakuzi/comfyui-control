"use strict";

class PromptHistoryView {
  constructor({ api, reuse }) {
    this.api = api;
    this.reuse = reuse;
    this.entries = [];
    this.epoch = 0;
    this.el = (id) => document.getElementById(id);
    this.el("prompt-history").addEventListener("click", () => this.open());
    this.el("close-prompt-history").addEventListener("click", () => this.el("prompt-history-dialog").close());
    this.el("prompt-history-dialog").addEventListener("close", () => { this.epoch++; this.entries = []; this.render(); });
    this.el("prompt-history-search").addEventListener("input", () => this.render());
    this.el("clear-prompt-history").addEventListener("click", () => this.action(async () => {
      if (!confirm("Clear your prompt history? Your favourite images and saved workflows are kept.")) return;
      await this.api("/api/prompts", { method: "DELETE", body: "{}" });
      this.entries = [];
      this.render();
    }, this.el("clear-prompt-history")));
  }

  async action(action, button) {
    if (button?.disabled) return;
    if (button) button.disabled = true;
    try { await action(); }
    catch (error) { this.el("prompt-history-status").textContent = error.message; }
    finally { if (button) button.disabled = false; }
  }

  async open() {
    this.el("prompt-history-search").value = "";
    const epoch = ++this.epoch;
    this.el("prompt-history-status").textContent = "Loading your prompts…";
    this.el("prompt-history-dialog").showModal();
    await this.action(async () => {
      const entries = await this.api("/api/prompts");
      if (epoch !== this.epoch) return;
      this.entries = entries;
      this.el("prompt-history-status").textContent = "";
      this.render();
    });
  }

  render() {
    const el = (tag, text, cls) => {
      const item = document.createElement(tag);
      if (text !== undefined) item.textContent = text;
      if (cls) item.className = cls;
      return item;
    };
    const query = this.el("prompt-history-search").value.toLocaleLowerCase().trim();
    const text = (entry, role) => (entry[role] || []).map((field) => field.value).join("\n\n");
    const items = this.entries.filter((entry) =>
      (text(entry, "positive") + "\n" + text(entry, "negative")).toLocaleLowerCase().includes(query));
    const list = this.el("prompt-history-list");
    list.replaceChildren();
    if (!items.length) list.append(el("p", query ? "No matching prompts." : "Prompts appear here after a generation is accepted.", "hint"));
    for (const entry of items) {
      const card = el("article", undefined, "prompt-entry");
      const reuse = el("button", undefined, "prompt-reuse");
      reuse.type = "button";
      reuse.setAttribute("aria-label", "Reuse prompt");
      reuse.append(el("span", text(entry, "positive") || "(Empty positive prompt)", "prompt-excerpt"));
      if (text(entry, "negative")) reuse.append(el("span", "Negative: " + text(entry, "negative"), "prompt-excerpt hint"));
      reuse.addEventListener("click", () => this.action(async () => {
        this.reuse(entry);
        this.el("prompt-history-dialog").close();
      }, reuse));
      const actions = el("div", undefined, "actions");
      const remove = el("button", "Delete", "text-button danger");
      remove.type = "button";
      remove.addEventListener("click", () => this.action(async () => {
        await this.api("/api/prompts/" + entry.id, { method: "DELETE", body: "{}" });
        this.entries = this.entries.filter((item) => item.id !== entry.id);
        this.render();
      }, remove));
      actions.append(remove);
      card.append(reuse, actions);
      list.append(card);
    }
  }
}
