"use strict";
/* Staged feature: no DOM lookup, listeners, timers or application state store.
   A future adapter supplies main's current job/state and explicitly paints its
   existing button. Main does not load this file. */
window.ComfyGenerateFeedback = class GenerateFeedback {
  constructor({ now = () => Date.now(), duration = 1400 } = {}) {
    this.now = now;
    this.duration = duration;
    this.reset();
  }

  reset() {
    this.observed = new Set();
    this.progressId = null;
    this.lastProgress = 0;
    this.feedback = null;
  }

  update({ jobs = [], selectedJob = null, busy = false, submitting = false,
    pending = false, connected = true, online = true, recovering = false } = {}) {
    const activeStatuses = new Set(["submitting", "queued", "running", "cancelling", "unknown"]);
    const progressJob = jobs.find((item) => item.status === "running") ||
      (selectedJob && activeStatuses.has(selectedJob.status) ? selectedJob : jobs.find((item) => activeStatuses.has(item.status)));
    const active = !!progressJob;
    if (progressJob && progressJob.id !== this.progressId) {
      this.progressId = progressJob.id;
      this.lastProgress = 0;
    }
    let finished = null;
    for (const job of jobs) {
      if (activeStatuses.has(job.status)) this.observed.add(job.id);
      else if (!busy && !submitting && this.observed.delete(job.id)) finished = job;
    }
    if (busy || submitting || active) this.feedback = null;
    else if (finished) {
      const kind = finished.status === "failed" ? "failed" : finished.status === "cancelled" ? "cancelled" : "success";
      this.feedback = { kind, label: { failed: "Generation failed", cancelled: "Cancelled", success: "✓ Complete" }[kind],
        expires: this.now() + this.duration };
    }
    const result = { kind: "idle", label: busy || submitting ? "Submitting" : pending ? "Retry submission" : "✦ Generate",
      progress: 0, finishFrom: this.lastProgress, busy: busy || submitting || active };
    if (result.busy) {
      result.kind = "indeterminate";
      if (!connected || recovering || !online) {
        result.kind = "paused";
        result.label = "Reconnecting";
      } else if (!busy && !submitting && progressJob) {
        const job = progressJob;
        result.label = { submitting: "Submitting", queued: "Queued", cancelling: "Stopping", unknown: "Checking submission" }[job.status] ||
          (job.phase === "processing" ? "Processing" : "Loading models");
        if (job.status === "running" && job.phase === "processing") result.progress = this.lastProgress;
        const value = job.progress?.value, max = job.progress?.max;
        if (job.status === "running" && Number.isFinite(value) && Number.isFinite(max) && max > 0) {
          const fraction = Math.max(0, Math.min(1, value / max));
          result.kind = fraction < 1 ? "determinate" : "indeterminate";
          result.progress = this.lastProgress = Math.min(fraction, 0.98);
          result.label = fraction < 1 ? `Sampling · ${Math.floor(fraction * 100)}%` : "Processing";
        }
      }
    } else if (this.feedback && this.now() < this.feedback.expires) {
      Object.assign(result, { kind: this.feedback.kind, label: this.feedback.label,
        progress: this.feedback.kind === "success" ? 1 : 0 });
    } else this.feedback = null;
    return result;
  }

  static paint(button, label, feedback) {
    button.dataset.progress = feedback.kind;
    button.style.setProperty("--generation-progress", feedback.progress);
    button.style.setProperty("--generation-finish-from", feedback.finishFrom);
    button.setAttribute("aria-busy", String(feedback.busy));
    label.textContent = feedback.label;
  }
};
