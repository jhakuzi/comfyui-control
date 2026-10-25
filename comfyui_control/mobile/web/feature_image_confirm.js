"use strict";

/* One themed, keyboard-accessible confirmation above the current viewer/dialog. */
window.ComfyImageConfirmation = class ImageConfirmation {
  constructor() {
    this.dialog = document.createElement("dialog");
    this.dialog.id = "image-confirm-dialog";
    this.dialog.setAttribute("role", "alertdialog");
    this.dialog.setAttribute("aria-labelledby", "image-confirm-title");
    this.dialog.setAttribute("aria-describedby", "image-confirm-message");
    this.dialog.innerHTML = '<h2 id="image-confirm-title"></h2><p id="image-confirm-message"></p><div class="actions"><button id="cancel-image-confirm" type="button" autofocus>Cancel</button><button id="accept-image-confirm" type="button" class="danger"></button></div>';
    document.body.append(this.dialog);
    this.title = this.dialog.querySelector("h2");
    this.message = this.dialog.querySelector("p");
    this.accept = this.dialog.querySelector("#accept-image-confirm");
    this.cancelButton = this.dialog.querySelector("#cancel-image-confirm");
    this.cancelButton.addEventListener("click", () => this.cancel());
    this.accept.addEventListener("click", () => this.finish(!this.current || this.current()));
    this.dialog.addEventListener("cancel", (event) => { event.preventDefault(); this.cancel(); });
    this.dialog.addEventListener("close", () => { if (!this.dialog.open) this.finish(false); });
  }

  ask({ title, message, accept, current }) {
    if (this.resolve) return Promise.resolve(false);
    this.title.textContent = title;
    this.message.textContent = message;
    this.accept.textContent = accept;
    this.current = current;
    const result = new Promise((resolve) => { this.resolve = resolve; });
    this.dialog.showModal();
    this.cancelButton.focus();
    return result;
  }

  finish(accepted) {
    const resolve = this.resolve;
    this.resolve = null;
    this.current = null;
    if (this.dialog.open) this.dialog.close();
    resolve?.(accepted === true);
  }

  cancel() { this.finish(false); }
};
