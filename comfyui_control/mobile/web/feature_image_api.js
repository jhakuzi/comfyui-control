"use strict";
/* Staged transport only. The future adapter must provide main's existing
   pending-submission journal; this component creates no persistence or UI. */
window.ComfyImageFeatureAPI = class ImageFeatureAPI {
  constructor({ api, readPending, writePending, accepted = () => {}, requestId }) {
    if ([api, readPending, writePending, requestId].some((value) => typeof value !== "function"))
      throw new TypeError("Supply the existing API, pending journal and request-ID callbacks.");
    this.api = api;
    this.readPending = readPending;
    this.writePending = writePending;
    this.accepted = accepted;
    this.requestId = requestId;
  }

  async workflow(item, action, parameters = {}) {
    if (!["edit", "upscale"].includes(action)) throw new Error("Choose Edit or Upscale.");
    if (this.readPending()) throw new Error("Resolve the current pending submission first.");
    const pending = { request_id: this.requestId(), action: { action, image_id: item.id, modified: item.modified,
      ...(action === "edit" ? { prompt: parameters.prompt } : { multiplier: parameters.multiplier }) } };
    this.writePending(pending);
    return this.retry();
  }

  async retry() {
    const pending = this.readPending();
    if (!pending?.action || !["edit", "upscale"].includes(pending.action.action))
      throw new Error("No pending image workflow. Use the existing generation retry for normal jobs.");
    let result;
    try {
      result = await this.api(`/api/images/${encodeURIComponent(pending.action.image_id)}/actions`, {
        method: "POST", timeoutMs: 90000,
        body: JSON.stringify({ ...pending.action, request_id: pending.request_id }),
      });
    } catch (error) {
      // Uncertain submissions retain exactly the original UUID and parameters.
      if ([400, 403, 404, 413, 415, 422].includes(error.status)) this.writePending(null);
      throw error;
    }
    if (!result?.job || result.job.id !== pending.request_id)
      throw new Error("Invalid submission response. The pending request is retained for safe retry.");
    await this.accepted(result.job);
    this.writePending(null);
    return result.job;
  }

  wastebin() { return this.api("/api/trash"); }
  restore(token) {
    return this.api(`/api/trash/${encodeURIComponent(token)}/restore`, { method: "POST", body: JSON.stringify({ confirm: true }) });
  }
  deletePermanently(tokens, confirmed) {
    if (confirmed !== true) throw new Error("Explicitly confirm permanent deletion.");
    return this.api("/api/trash/empty", { method: "POST", timeoutMs: 180000, body: JSON.stringify({ tokens, confirm: true }) });
  }
  cleanupVRAM() { return this.api("/api/vram/cleanup", { method: "POST", body: "{}" }); }
};
