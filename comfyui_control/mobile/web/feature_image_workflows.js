"use strict";

/* The existing Edit/Upscale forms, independent of either presentation. Opening
   or cancelling never changes the generation form or submits a workflow. */
window.ComfyImageWorkflowDialogs = class ImageWorkflowDialogs {
  constructor({ read, write }) {
    this.read = read;
    this.write = write;
    for (const action of ["edit", "upscale"])
      document.getElementById(`cancel-${action}-image`).addEventListener("click", () =>
        document.getElementById(`${action}-image-dialog`).close());
  }

  close() {
    for (const action of ["edit", "upscale"]) {
      const dialog = document.getElementById(`${action}-image-dialog`);
      if (dialog.open) dialog.close();
    }
  }

  options(item, action) {
    const $ = (suffix) => document.getElementById(`${action}-image-${suffix}`);
    const dialog = $("dialog"), form = $("form"), input = $(action === "edit" ? "prompt" : "multiplier");
    const key = action === "edit" ? "edit-instruction-" + item.id : "upscale-multiplier";
    input.value = this.read(key, "");
    input.setCustomValidity("");
    $("source").textContent = item.filename;
    return new Promise((resolve) => {
      let result = null;
      const save = () => { input.setCustomValidity(""); this.write(key, input.value); };
      const submit = (event) => {
        event.preventDefault();
        if (action === "edit") {
          if (!input.value.trim()) { input.focus(); return; }
          result = { prompt: input.value };
        } else {
          const multiplier = input.value === "" ? null : input.valueAsNumber;
          if (multiplier !== null && (!Number.isFinite(multiplier) || multiplier <= 0)) {
            input.setCustomValidity("Enter a positive multiplier or leave blank for the workflow default.");
            input.reportValidity();
            return;
          }
          result = multiplier === null ? {} : { multiplier };
        }
        dialog.close();
      };
      const close = () => {
        save();
        input.removeEventListener("input", save);
        form.removeEventListener("submit", submit);
        resolve(result);
      };
      input.addEventListener("input", save);
      form.addEventListener("submit", submit);
      dialog.addEventListener("close", close, { once: true });
      dialog.showModal();
      input.focus();
    });
  }
};
