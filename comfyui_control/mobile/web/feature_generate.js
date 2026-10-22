"use strict";
/* Generate feedback only: the existing controller supplies job/state updates.
   No DOM lookup, listeners, polling, requests or application state store. */
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

  rejected(requestId) {
    this.observed.delete(requestId);
    this.feedback = { kind: "failed", label: "Submission failed", expires: this.now() + this.duration };
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
        const sampling = !job.phase || job.phase === "sampling";
        if (job.status === "running" && sampling && Number.isFinite(value) && Number.isFinite(max) && max > 0) {
          const fraction = Math.max(0, Math.min(1, value / max));
          result.kind = "determinate";
          result.progress = this.lastProgress = fraction;
          result.label = `Sampling · ${Math.floor(fraction * 100)}%`;
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
