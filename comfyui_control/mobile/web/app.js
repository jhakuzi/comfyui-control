"use strict";
const $ = (id) => document.getElementById(id);
const activeStatuses = new Set([
  "submitting",
  "queued",
  "running",
  "cancelling",
  "unknown",
]);
let preset = null,
  draft = {},
  disabledLoras = new Set(),
  randomSeed = true;
let state = { jobs: [], online: false },
  selectedJob = null,
  events = null,
  busy = false;
let submitting = false;
let galleryRevision = "", galleryPromise = null, galleryTimer = null, galleryEpoch = 0;
let mappingDraft = new Map(),
  gallery = [],
  viewerItems = [],
  viewerIndex = 0;
let fullStatePending = false;
let fullStateAgain = false;
let presetEpoch = 0;
let connected = false,
  recovering = false,
  initialized = false;
let recoveryPromise = null,
  recoveryEpoch = 0,
  retryTimer,
  retryDelay = 500,
  heartbeatTimer;
const requests = new Set();
let uiReady = false,
  uiState = readStore("ui", {});
let noticeTimer,
  pendingSubmission = readStore("pending", null);

function readStore(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem("comfy-mobile-" + key)) ?? fallback;
  } catch {
    return fallback;
  }
}
function writeStore(key, value) {
  try {
    localStorage.setItem("comfy-mobile-" + key, JSON.stringify(value));
  } catch {}
}
function node(tag, text, className) {
  const el = document.createElement(tag);
  if (text !== undefined) el.textContent = text;
  if (className) el.className = className;
  return el;
}
function notice(message) {
  $("notice").textContent = message;
  $("notice").hidden = false;
  clearTimeout(noticeTimer);
  noticeTimer = setTimeout(() => {
    $("notice").hidden = true;
  }, 10000);
}
async function api(path, options = {}) {
  const controller = new AbortController();
  requests.add(controller);
  const timeout = setTimeout(() => controller.abort(), 8000);
  let response, text;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      ...options,
      signal: controller.signal,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
    text = await response.text();
  } catch {
    throw new Error(
      "Connection lost. Your settings are kept; reconnect and try again.",
    );
  } finally {
    clearTimeout(timeout);
    requests.delete(controller);
  }
  let body;
  try {
    body = JSON.parse(text);
  } catch {
    body = { error: text || "Request failed." };
  }
  if (!response.ok) {
    if (response.status === 401) showLogin();
    const error = new Error(body.error || "Request failed.");
    error.status = response.status;
    throw error;
  }
  return body;
}
function showLogin() {
  stopGallerySync();
  galleryRevision = "";
  comparison.clearImages();
  if ($("image-dialog").open) $("image-dialog").close();
  if ($("prompt-history-dialog").open) $("prompt-history-dialog").close();
  if ($("compare-dialog").open) $("compare-dialog").close();
  $("offline").hidden = true;
  if (events) events.close();
  events = null;
  clearTimeout(retryTimer);
  clearTimeout(heartbeatTimer);
  connected = false;
  $("login").hidden = false;
  $("workspace").hidden = true;
  $("connection").textContent = "Sign in";
  $("connection").classList.remove("online");
}
function saveDraft() {
  if (preset)
    writeStore("draft-" + preset.id, {
      revision: preset.revision,
      graphRevision: preset.graph_revision,
      fields: preset.fields.map(({ key, node, input, role, kind }) => ({ key, node, input, role, kind })),
      values: draft,
      randomSeed,
      seedPreferenceVersion: 2,
      disabledLoras: [...disabledLoras],
      mappings: [...mappingDraft.values()],
    });
}
function saveUI() {
  if (!uiReady) return;
  uiState = {
    tab: $("gallery-page").hidden ? "create" : "gallery",
    details: Object.fromEntries(
      [...document.querySelectorAll("details[id]")].map((el) => [
        el.id,
        el.open,
      ]),
    ),
    search: $("mapping-search").value,
    importName: $("import-name").value,
    expandedPrompts: uiState.expandedPrompts || {},
    scroll: window.scrollY,
  };
  writeStore("ui", uiState);
}
function restoreUI() {
  uiReady = false;
  for (const [id, open] of Object.entries(uiState.details || {})) {
    if ($(id)?.tagName === "DETAILS") $(id).open = !!open;
  }
  $("mapping-search").value = uiState.search || "";
  $("import-name").value = uiState.importName || "";
  renderMappings();
  selectTab(uiState.tab === "gallery" ? "gallery" : "create");
  const scroll = uiState.scroll || 0;
  requestAnimationFrame(() => window.scrollTo(0, scroll));
  uiReady = true;
}
function selectTab(name) {
  $("create-page").hidden = name !== "create";
  $("gallery-page").hidden = name !== "gallery";
  $("create-tab").classList.toggle("selected", name === "create");
  $("gallery-tab").classList.toggle("selected", name === "gallery");
  syncGenerationDock();
  saveUI();
  if (name === "gallery") loadGallery(true);
  else stopGallerySync();
}
function currentJob() {
  return selectedJob === "new"
    ? null
    : state.jobs.find((item) => item.id === selectedJob) || state.jobs.at(-1);
}
function syncGenerationDock() {
  const job = currentJob(),
    active = !!job && activeStatuses.has(job.status),
    dock = $("generation-dock"),
    card = $("job-card"),
    destination = active ? dock : $("job-output");
  renderGenerationStats(job);
  if (card.parentElement !== destination) {
    if (active) destination.prepend(card);
    else destination.append(card);
  }
  $("dock-submitting").hidden = !submitting || active;
  const images = !active && !submitting ? job?.images || [] : [];
  $("dock-result").hidden = !images.length;
  if (images.length) {
    const src = images[0].thumbnail || images[0].url;
    if ($("dock-result-image").getAttribute("src") !== src) {
      $("dock-result-image").hidden = false;
      $("dock-result-image").src = src;
    }
    $("dock-result").querySelector("span").textContent = images.length === 1
      ? "Image ready · View result"
      : `${images.length} images ready · View results`;
  }
  dock.hidden = !active && !submitting && !$("gallery-page").hidden;
}
function renderGenerationStats(job) {
  $("generation-stats").hidden = !job || !activeStatuses.has(job.status);
  const numeric = (value) => typeof value === "number" && Number.isFinite(value);
  const timing = connected && state.online && job?.status === "running" ? job.seconds_per_iteration : null;
  const hardware = connected && state.online ? state.hardware || {} : {};
  $("stat-iteration").textContent = numeric(timing) ? timing.toFixed(2) : "--";
  $("stat-vram").textContent = numeric(hardware.vram_used) ? (hardware.vram_used / 2 ** 30).toFixed(1) + " GiB" : "--";
  $("stat-gpu").textContent = numeric(hardware.utilization) ? Math.round(hardware.utilization) + "%" : "--";
}
function updateGenerate() {
  const job = state.jobs.find((item) => item.id === selectedJob);
  $("generate").disabled =
    busy ||
    !connected ||
    recovering ||
    !preset ||
    !state.online ||
    preset.missing_nodes.length > 0 ||
    !!(job && activeStatuses.has(job.status));
  $("generate").textContent = busy
    ? "Submitting…"
    : pendingSubmission
      ? "Retry submission"
      : "✦ Generate";
  syncGenerationDock();
}
async function loadPresets(selectId) {
  const items = await api("/api/presets");
  $("preset").replaceChildren(new Option("Choose a workflow…", ""));
  for (const item of items) $("preset").add(new Option(item.name, item.id));
  $("empty-presets").hidden = items.length > 0;
  const stored = [
    selectId,
    readStore("preset", ""),
    items.find((item) => item.default)?.id,
    items.length === 1 ? items[0].id : "",
  ].find((id) => items.some((item) => item.id === id));
  if (stored) {
    $("preset").value = stored;
    await choosePreset(stored);
  }
  await loadSavedWorkflows();
}
async function loadSavedWorkflows() {
  $("preset").querySelector("optgroup")?.remove();
  $("refresh-workflows").disabled = true;
  try {
    const names = await api("/api/workflows/saved");
    if (names.length) {
      const group = node("optgroup");
      group.label = "Saved in ComfyUI";
      for (const name of names)
        group.append(new Option(name.replace(/\.json$/i, ""), "saved:" + name));
      $("preset").append(group);
    }
    $("workflow-source-note").hidden = !!names.length;
    $("workflow-source-note").textContent =
      "Save a workflow in ComfyUI to select it here, or choose one from the desktop app.";
  } catch {
    $("workflow-source-note").hidden = false;
    $("workflow-source-note").textContent =
      "Saved ComfyUI workflows are unavailable. Start ComfyUI, then refresh this list. Your mobile presets remain available.";
  } finally {
    $("refresh-workflows").disabled = false;
  }
}
async function selectWorkflow(id) {
  if (!id.startsWith("saved:")) return choosePreset(id);
  const previous = preset;
  busy = true;
  updateGenerate();
  try {
    const item = await api("/api/workflows/saved", {
      method: "POST",
      body: JSON.stringify({ name: id.slice(6) }),
    });
    await loadPresets(item.id);
  } catch (error) {
    $("preset").value = previous?.id || "";
    throw error;
  } finally {
    busy = false;
    updateGenerate();
  }
}
async function choosePreset(id, reuse) {
  const epoch = ++presetEpoch;
  preset = null;
  $("refresh-models").hidden = !id;
  updateGenerate();
  for (const target of [
    "prompt-controls",
    "model-controls",
    "lora-controls",
    "basic-controls",
    "resolution-controls",
    "advanced-controls",
    "mapping-controls",
  ])
    $(target).replaceChildren();
  for (const target of [
    "lora-card",
    "settings-card",
    "resolution-card",
    "delete-preset",
  ])
    $(target).hidden = true;
  if (!id) return;
  writeStore("preset", id);
  const loaded = await api("/api/presets/" + encodeURIComponent(id));
  if (epoch !== presetEpoch) return;
  preset = loaded;
  const stored = reuse || readStore("draft-" + id, {});
  const same = stored.revision === preset.revision;
  // Model discovery adds controls without changing the graph. Keep drafts only
  // when both the graph and each existing control's target/type still match.
  const upgraded = !!stored.revision && stored.revision === preset.model_upgrade_revision;
  const compatible = same || upgraded || (stored.graphRevision && stored.graphRevision === preset.graph_revision);
  const oldFields = stored.fields || (upgraded ? stored.mappings : []) || [];
  const canReuse = (field) => same || (compatible && oldFields.some(
    (old) => ["key", "node", "input", "role"].every((key) => old[key] === field[key]) && (!old.kind || old.kind === field.kind),
  ));
  draft = Object.fromEntries(
    preset.fields.map((field) => [
      field.key,
      canReuse(field) && Object.hasOwn(stored.values || {}, field.key)
        ? stored.values[field.key]
        : field.default,
    ]),
  );
  // Reset older saved defaults once, without losing prompts or fixed seed values.
  // Keep new checkbox choices and explicit Same seed reuse across refreshes.
  randomSeed = compatible && (reuse || stored.seedPreferenceVersion === 2) && typeof stored.randomSeed === "boolean"
    ? stored.randomSeed : true;
  disabledLoras = new Set(compatible ? stored.disabledLoras || [] : []);
  mappingDraft = new Map(
    (same && Array.isArray(stored.mappings)
      ? stored.mappings
      : preset.fields
    ).map((field) => [
      field.node + "\0" + field.input,
      {
        key: field.key,
        node: field.node,
        input: field.input,
        role: field.role,
        label: field.label,
        group: field.group,
      },
    ]),
  );
  if (!same && compatible && Array.isArray(stored.mappings)) {
    const oldTargets = new Set(oldFields.map((field) => field.node + "\0" + field.input));
    for (const target of oldTargets) mappingDraft.delete(target);
    for (const field of stored.mappings) {
      if (preset.candidates.some((candidate) => candidate.node === field.node && candidate.input === field.input))
        mappingDraft.set(field.node + "\0" + field.input, field);
    }
  }
  $("delete-preset").hidden = false;
  if (preset.missing_nodes.length)
    notice("Missing ComfyUI nodes: " + preset.missing_nodes.join(", "));
  if (!preset.fields.length) {
    $("advanced").open = true;
    $("mapping").open = true;
  }
  renderFields();
  renderMappings();
  writeStore("preset", id);
  saveDraft();
  updateGenerate();
}
function control(field, container, hideLabel = false) {
  const wrap = node("div", undefined, "control");
  if ((field.kind === "text" && !field.options) || field.role === "seed")
    wrap.classList.add("wide");
  const label = node("label", field.label);
  if (hideLabel) label.classList.add("visually-hidden");
  const inputId = "control-" + field.key;
  label.htmlFor = inputId;
  let input;
  if (field.kind === "bool") {
    input = node("input");
    input.type = "checkbox";
    input.checked = !!draft[field.key];
    label.classList.add("check-label");
    label.prepend(input);
    wrap.append(label);
  } else {
    if (field.options) {
      input = node("select");
      for (const option of field.options)
        input.add(new Option(String(option), String(option)));
    } else if (["positive", "negative"].includes(field.role)) {
      input = node("textarea");
      if (field.role === "negative") input.classList.add("negative");
      input.maxLength = 20000;
      input.placeholder =
        field.role === "positive"
          ? "Describe your image…"
          : "What should stay out of the image?";
    } else {
      input = node("input");
      input.type =
        field.kind === "text" || field.role === "seed" ? "text" : "number";
      if (field.kind !== "text") {
        input.inputMode = field.kind === "float" ? "decimal" : "numeric";
        if (field.min !== null) input.min = String(field.min);
        if (field.max !== null) input.max = String(field.max);
        input.step = field.step || (field.kind === "float" ? "any" : "1");
      }
    }
    input.value = draft[field.key] ?? "";
    wrap.append(label, input);
  }
  if (input.tagName === "TEXTAREA" && field.role === "positive") {
    input.classList.add("positive");
    wrap.classList.add("prompt-editor");
    const heading = node("div", undefined, "prompt-editor-heading");
    const toggle = node("button", undefined, "small prompt-editor-toggle");
    toggle.type = "button";
    toggle.setAttribute("aria-controls", inputId);
    const editorKey = preset.id + ":" + field.key;
    const resize = (expanded) => {
      input.style.removeProperty("height");
      wrap.classList.toggle("expanded", expanded);
      toggle.textContent = expanded ? "Collapse" : "Expand";
      toggle.setAttribute("aria-expanded", String(expanded));
      toggle.setAttribute("aria-label", `${expanded ? "Collapse" : "Expand"} ${field.label} editor`);
    };
    resize(uiState.expandedPrompts?.[editorKey] === true);
    toggle.addEventListener("click", () => {
      const expanded = !wrap.classList.contains("expanded");
      uiState.expandedPrompts = { ...uiState.expandedPrompts, [editorKey]: expanded };
      resize(expanded);
      saveUI();
    });
    label.replaceWith(heading);
    heading.append(label, toggle);
  }
  input.id = inputId;
  input.dataset.role = field.role;
  if (field.role === "seed") input.disabled = randomSeed;
  input.addEventListener("input", () => {
    draft[field.key] =
      field.kind === "bool"
        ? input.checked
        : field.kind === "float"
          ? Number(input.value)
          : input.value;
    saveDraft();
  });
  if (
    ["steps", "cfg", "resolution_mp", "lora_strength"].includes(field.role) &&
    ["int", "float"].includes(field.kind) &&
    !field.options
  ) {
    const slider = node("input");
    slider.type = "range";
    slider.setAttribute("aria-label", field.label + " slider");
    slider.min = field.min ?? (field.role === "steps" ? 1 : 0);
    const practical =
      field.role === "steps"
        ? 100
        : field.role === "cfg"
          ? 30
          : field.role === "resolution_mp"
            ? 8
            : 2;
    slider.max = Math.min(
      field.max ?? Infinity,
      Math.max(practical, Number(input.value), Number(slider.min) + 1),
    );
    slider.step = field.step || (field.kind === "int" ? 1 : 0.05);
    slider.value = input.value;
    slider.addEventListener("input", () => {
      input.value = slider.value;
      input.dispatchEvent(new Event("input", { bubbles: true }));
    });
    input.addEventListener("input", () => {
      slider.value = input.value;
    });
    wrap.insertBefore(slider, input);
  }
  container.append(wrap);
  return input;
}
function renderFields() {
  const roles = (role) => preset.fields.filter((field) => field.role === role);
  for (const field of roles("positive")) control(field, $("prompt-controls"));
  if (roles("negative").length) {
    const details = node("details");
    details.id = "negative-controls";
    details.append(node("summary", "Negative prompt"));
    for (const field of roles("negative"))
      control(field, details, roles("negative").length === 1);
    $("prompt-controls").append(details);
  }
  // Keep the three loaders together even when an older mapping placed the
  // diffusion filename under Advanced. The stored mapping/key stays unchanged.
  for (const role of ["diffusion_model", "model", "vae", "text_encoder"]) {
    const fields = preset.fields.filter((field) => (field.model_role || field.role) === role);
    for (const field of fields) {
      const label = role === "diffusion_model"
        ? "Diffusion model" + (fields.length > 1 ? " · " + field.label : "")
        : field.label;
      control({ ...field, role, label }, $("model-controls"));
    }
  }
  const loras = preset.fields.filter((field) => field.role.startsWith("lora_"));
  const groups = [...new Set(loras.map((field) => field.group))];
  for (const group of groups) {
    const fields = loras.filter((field) => field.group === group),
      box = node("div", undefined, "lora-group");
    if (
      fields.some((field) => field.role === "lora_strength") &&
      !fields.some((field) => field.role === "lora_enabled")
    ) {
      const label = node(
        "label",
        fields.find((field) => field.role === "lora_model")?.default ||
          fields[0].label,
        "check-label",
      );
      const toggle = node("input");
      toggle.type = "checkbox";
      toggle.checked = !disabledLoras.has(group);
      toggle.addEventListener("change", () => {
        toggle.checked ? disabledLoras.delete(group) : disabledLoras.add(group);
        saveDraft();
      });
      label.prepend(toggle);
      box.append(label);
    }
    const grid = node("div", undefined, "control-grid");
    for (const field of fields) control(field, grid);
    box.append(grid);
    $("lora-controls").append(box);
  }
  $("lora-card").hidden = !groups.length;
  $("lora-count").textContent = `· ${groups.length} configured`;
  const basics = preset.fields.filter((field) =>
    ["sampler", "scheduler", "steps", "cfg", "seed", "batch"].includes(
      field.role,
    ),
  );
  for (const field of basics) control(field, $("basic-controls"));
  if (roles("seed").length) {
    const label = node(
        "label",
        "Randomize seed for each generation",
        "check-label wide",
      ),
      toggle = node("input");
    const hint = node("p", "With a fixed seed, unchanged settings may reuse the previous image.", "hint wide");
    hint.hidden = randomSeed;
    toggle.type = "checkbox";
    toggle.id = "random-seed";
    toggle.checked = randomSeed;
    toggle.addEventListener("change", () => {
      randomSeed = toggle.checked;
      hint.hidden = randomSeed;
      document.querySelectorAll('[data-role="seed"]').forEach((input) => {
        input.disabled = randomSeed;
      });
      saveDraft();
    });
    label.prepend(toggle);
    $("basic-controls").append(label, hint);
  }
  $("settings-card").hidden = !basics.length;
  const resolution = preset.fields.filter((field) =>
    [
      "width",
      "height",
      "resolution_mp",
      "aspect_ratio",
      "alignment",
      "custom_ratio",
      "custom_aspect_ratio",
    ].includes(field.role),
  );
  for (const field of resolution) control(field, $("resolution-controls"));
  $("resolution-card").hidden = !resolution.length;
  for (const field of roles("advanced").filter((field) => !field.model_role)) control(field, $("advanced-controls"));
  $("reuse-last").hidden = !state.jobs.some((job) => job.preset === preset.id);
}
const roleNames = {
  positive: "Positive prompt",
  negative: "Negative prompt",
  model: "Model / checkpoint",
  diffusion_model: "Diffusion model",
  vae: "VAE",
  text_encoder: "Text encoder",
  sampler: "Sampler",
  scheduler: "Scheduler",
  resolution_mp: "Resolution · megapixels",
  aspect_ratio: "Resolution · aspect ratio",
  alignment: "Resolution · divisible by",
  custom_ratio: "Resolution · custom ratio",
  custom_aspect_ratio: "Resolution · custom aspect ratio",
  lora_model: "LoRA model",
  lora_strength: "LoRA strength",
  lora_enabled: "LoRA enabled",
  width: "Width",
  height: "Height",
  steps: "Steps",
  cfg: "CFG",
  seed: "Seed",
  batch: "Batch size",
  advanced: "Other advanced control",
};
function renderMappings() {
  $("mapping-controls").replaceChildren();
  if (!preset) return;
  const query = $("mapping-search").value.toLowerCase();
  const matches = preset.candidates
    .map((candidate, index) => ({ ...candidate, index }))
    .filter((candidate) => candidate.label.toLowerCase().includes(query));
  for (const candidate of matches.slice(0, 100)) {
    const target = candidate.node + "\0" + candidate.input,
      row = node("div", undefined, "mapping-row");
    row.append(node("p", candidate.label, "hint"));
    const select = node("select");
    select.setAttribute("aria-label", "Control for " + candidate.label);
    select.add(new Option("Keep saved value · no mobile control", ""));
    for (const [role, label] of Object.entries(roleNames)) {
      const compatible = [
        "positive",
        "negative",
        "model",
        "lora_model",
        "diffusion_model",
        "vae",
        "text_encoder",
        "sampler",
        "scheduler",
        "aspect_ratio",
        "custom_aspect_ratio",
      ].includes(role)
        ? candidate.kind === "text"
        : ["width", "height", "steps", "seed", "batch", "alignment"].includes(
              role,
            )
          ? candidate.kind === "int"
          : ["cfg", "lora_strength", "resolution_mp"].includes(role)
            ? ["int", "float"].includes(candidate.kind)
            : role === "lora_enabled"
              ? candidate.kind === "bool"
              : true;
      if (compatible) select.add(new Option(label, role));
    }
    select.value = mappingDraft.get(target)?.role || "";
    const labelInput = node("input");
    labelInput.placeholder = "Control label";
    labelInput.setAttribute("aria-label", "Control label");
    labelInput.value = mappingDraft.get(target)?.label || "";
    const group = node("input");
    group.placeholder = "LoRA group (same group shares its strength switch)";
    group.setAttribute("aria-label", "LoRA group");
    group.value = mappingDraft.get(target)?.group || candidate.node;
    function update() {
      if (!select.value) mappingDraft.delete(target);
      else
        mappingDraft.set(target, {
          key: mappingDraft.get(target)?.key || "m-" + candidate.index,
          node: candidate.node,
          input: candidate.input,
          role: select.value,
          label: labelInput.value || roleNames[select.value],
          group: group.value || candidate.node,
        });
      labelInput.hidden = !select.value;
      group.hidden = !select.value.startsWith("lora_");
      saveDraft();
    }
    select.addEventListener("change", update);
    labelInput.addEventListener("input", update);
    group.addEventListener("input", update);
    labelInput.hidden = !select.value;
    group.hidden = !select.value.startsWith("lora_");
    row.append(select, labelInput, group);
    $("mapping-controls").append(row);
  }
  $("mapping-count").textContent =
    `Showing ${Math.min(matches.length, 100)} of ${matches.length} matching inputs. Search to find others.`;
  $("save-mapping").disabled = !preset;
}
function requestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 15) | 64;
  bytes[8] = (bytes[8] & 63) | 128;
  const hex = [...bytes]
    .map((value) => value.toString(16).padStart(2, "0"))
    .join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`;
}
async function generate(event) {
  event.preventDefault();
  if (busy || !preset || !connected || recovering) return;
  busy = true;
  submitting = true;
  updateGenerate();
  const body = pendingSubmission || {
    request_id: requestId(),
    preset: preset.id,
    revision: preset.revision,
    values: draft,
    random_seed: randomSeed,
    disabled_loras: [...disabledLoras],
  };
  pendingSubmission = JSON.parse(JSON.stringify(body));
  writeStore("pending", pendingSubmission);
  try {
    const job = await api("/api/generate", {
      method: "POST",
      body: JSON.stringify(body),
    });
    if (job.prompt_history_notice) notice(job.prompt_history_notice);
    pendingSubmission = null;
    writeStore("pending", null);
    selectedJob = job.id;
    writeStore("job", job.id);
    state = await api("/api/state");
    applyState(state);
  } catch (error) {
    if ([400, 403, 404, 413, 415, 422].includes(error.status)) {
      pendingSubmission = null;
      writeStore("pending", null);
      notice(error.message);
    } else
      notice(
        error.message +
          " Tap Retry submission to check the same request safely.",
      );
  } finally {
    busy = false;
    submitting = false;
    updateGenerate();
  }
}
function refreshFullState() {
  if (fullStatePending) return;
  fullStateAgain = false;
  fullStatePending = true;
  api("/api/state")
    .then(applyState)
    .catch(connectionFailure)
    .finally(() => {
      fullStatePending = false;
      if (fullStateAgain) refreshFullState();
    });
}
function applyState(value) {
  if (value.instance === state.instance && value.version < state.version)
    return;
  if (value.instance !== state.instance && value.partial) {
    refreshFullState();
    return;
  }
  if (value.partial) {
    let needsDetails = false;
    value.jobs = value.jobs.map((summary) => {
      const previous = state.jobs.find((job) => job.id === summary.id);
      if (!previous || summary.image_count !== (previous.images || []).length)
        needsDetails = true;
      return { ...previous, ...summary };
    });
    if (needsDetails) {
      fullStateAgain = true;
      refreshFullState();
    }
  }
  state = value;
  const output = state.output_status || {};
  $("output-warning").hidden = !["warning", "error"].includes(output.level);
  $("output-warning-title").textContent = output.title || "";
  $("output-warning-error").textContent = output.error
    ? "Network mount failed: " + output.error : output.connection || "";
  $("output-warning-message").textContent = output.message || "";
  $("comfy-offline").hidden = state.online;
  $("comfy-offline").textContent = state.online
    ? ""
    : state.connection +
      " Check the desktop app; this page will reconnect automatically.";
  if (pendingSubmission) {
    const acknowledged = state.jobs.find(
      (job) => job.id === pendingSubmission.request_id,
    );
    if (acknowledged) {
      selectedJob = acknowledged.id;
      writeStore("job", acknowledged.id);
      if (acknowledged.status !== "submitting") {
        pendingSubmission = null;
        writeStore("pending", null);
      }
    }
  }
  $("connection").textContent = value.online
    ? "ComfyUI online"
    : "ComfyUI offline";
  $("connection").classList.toggle("online", value.online);
  if (!selectedJob && state.jobs.length)
    selectedJob = readStore("job", null) || state.jobs.at(-1).id;
  const job = currentJob();
  $("job-card").hidden = !job;
  if (job) {
    selectedJob = job.id;
    writeStore("job", job.id);
    writeStore("active", { id: job.id, prompt_id: job.prompt_id });
    const titles = {
      submitting: "Sending your idea…",
      queued: "In the queue",
      running: job.progress ? "Creating your image"
        : job.phase === "processing" ? "Processing workflow…"
        : "Preparing / loading models…",
      complete: "Your image is ready",
      failed: "Generation stopped",
      cancelled: "Generation cancelled",
      cancelling: "Stopping generation…",
      unknown: "Checking submission status",
    };
    $("job-title").textContent = titles[job.status] || job.status;
    $("job-detail").textContent =
      job.error ||
      (job.status === "queued"
        ? `Queue position ${job.position || "—"} · ${job.preset_name}`
        : job.status === "unknown"
          ? "The submission response was lost. Reconnecting will check ComfyUI before another request is sent."
          : job.status === "running" && job.progress
            ? `${job.progress.value} / ${job.progress.max} steps · ${job.preset_name}`
            : job.status === "running"
              ? job.phase === "processing"
                ? `Preparing another stage or saving results · ${job.preset_name}`
                : `Preparing the workflow; models may take a while to load · ${job.preset_name}`
              : job.preset_name);
    $("progress").hidden = !["submitting", "queued", "running", "cancelling"].includes(job.status);
    $("progress").setAttribute("aria-label", $("job-title").textContent);
    if (job.status === "running" && job.progress) {
      $("progress").max = job.progress.max || 1;
      $("progress").value = job.progress.value || 0;
    } else {
      $("progress").removeAttribute("value"); // Indeterminate: never invent a loading percentage.
    }
    $("cancel").hidden = !["queued", "running"].includes(job.status);
    $("new-request").hidden = job.status !== "unknown";
    $("same-seed").hidden = !["complete", "failed", "cancelled"].includes(
      job.status,
    );
    $("variation").hidden = $("same-seed").hidden;
    const preview =
      state.preview_job === job.id && job.status === "running"
        ? state.preview
        : null;
    $("preview").hidden = !preview;
    $("job-card").classList.toggle("has-preview", !!preview);
    if (preview && !$("preview").src.endsWith(preview))
      $("preview").src = preview;
    renderImages($("job-images"), job.images || []);
  }
  $("reuse-last").hidden =
    !preset || !state.jobs.some((job) => job.preset === preset.id);
  updateGenerate();
}
function renderImages(container, items) {
  container.imageItems = items;
  const signature = JSON.stringify(items.map((item) => [item.id, item.url, item.thumbnail]));
  if (container.dataset.signature === signature) return;
  container.dataset.signature = signature;
  const existing = new Map([...container.children].map((button) => [button.dataset.imageId, button]));
  for (const [id, button] of existing) {
    if (!items.some((item) => item.id === id)) button.remove();
  }
  items.forEach((item, index) => {
    const source = item.thumbnail || item.url;
    const previous = existing.get(item.id);
    if (previous?.dataset.source === source && previous.querySelector("img")) {
      if (container.children[index] !== previous) container.insertBefore(previous, container.children[index] || null);
      return;
    }
    const button = node("button");
    button.type = "button";
    button.dataset.imageId = item.id;
    button.dataset.source = source;
    button.setAttribute("aria-label", "View " + item.filename);
    const image = node("img");
    image.src = source;
    image.alt = item.filename;
    image.loading = "lazy";
    image.decoding = "async";
    image.addEventListener("error", () => {
      if (image.dataset.fallback !== "1" && item.thumbnail) {
        image.dataset.fallback = "1";
        image.src = item.url;
        return;
      }
      button.replaceChildren(node("span", "Image unavailable", "missing"));
      container.dataset.signature = "";
    });
    button.append(image);
    button.addEventListener("click", () => {
      const currentItems = container.imageItems;
      const currentIndex = currentItems.findIndex((entry) => entry.id === item.id);
      if (currentIndex < 0) return;
      if (container.id === "gallery-grid" && comparison.choose(currentItems[currentIndex])) return;
      openImage(currentItems, currentIndex);
    });
    if (previous) previous.replaceWith(button);
    if (container.children[index] !== button) container.insertBefore(button, container.children[index] || null);
  });
}
function stopGallerySync() {
  clearTimeout(galleryTimer);
  galleryEpoch++;
  galleryPromise = null;
}
function loadGallery(force = false) {
  if (document.hidden || $("gallery-page").hidden || $("workspace").hidden) return;
  if (galleryPromise) return galleryPromise;
  clearTimeout(galleryTimer);
  const epoch = galleryEpoch;
  $("refresh-gallery").disabled = true;
  galleryPromise = (async () => {
    try {
      const result = await api(`/api/gallery?since=${encodeURIComponent(galleryRevision)}${force ? "&refresh=1" : ""}`);
      if (epoch !== galleryEpoch) return;
      galleryRevision = result.revision;
      if (result.images) {
        const oldGallery = gallery;
        gallery = result.images;
        if ($("image-dialog").open && viewerItems === oldGallery) {
          const previous = viewerItems[viewerIndex];
          const index = gallery.findIndex((item) => item.id === previous.id);
          if (index < 0) {
            $("image-dialog").close();
            notice("This image was removed from the output folder.");
          } else if (gallery[index].url !== previous.url) {
            openImage(gallery, index);
          } else {
            viewerItems = gallery;
            viewerIndex = index;
            $("previous-image").disabled = $("next-image").disabled = gallery.length < 2;
          }
        }
      }
      renderImages($("gallery-grid"), gallery);
      comparison.gallery(gallery);
      $("gallery-empty").hidden = !!gallery.length;
    } catch (error) {
      if (force && epoch === galleryEpoch) notice(error.message);
    } finally {
      if (epoch === galleryEpoch) {
        galleryPromise = null;
        $("refresh-gallery").disabled = false;
        if (connected && !document.hidden && !$("gallery-page").hidden && !$("workspace").hidden)
          galleryTimer = setTimeout(() => loadGallery(), 5000);
      }
    }
  })();
  return galleryPromise;
}
function openImage(items, index) {
  viewerItems = items;
  viewerIndex = (index + items.length) % items.length;
  const item = items[viewerIndex],
    job = state.jobs.find((entry) => entry.id === item.job);
  $("full-image").src = item.url;
  $("image-caption").textContent = item.filename;
  $("download-image").href = item.download;
  $("previous-image").disabled = $("next-image").disabled = items.length < 2;
  $("reuse-image").disabled = $("vary-image").disabled = !job;
  imageDetails.select(item);
  if (!$("image-dialog").open) $("image-dialog").showModal();
}
async function reuseJob(job, variation = false) {
  if (!job) return;
  const loaded = await api("/api/presets/" + encodeURIComponent(job.preset));
  if (loaded.revision !== job.revision)
    throw new Error(
      "This preset’s mappings changed. Choose it again and review the settings before generating.",
    );
  selectedJob = "new";
  writeStore("job", "new");
  await loadPresets(job.preset);
  await choosePreset(job.preset, {
    revision: job.revision,
    values: job.values,
    randomSeed: variation,
    disabledLoras: job.disabled_loras,
  });
  $("preset").value = job.preset;
  $("image-dialog").close();
  selectTab("create");
  $("job-card").hidden = true;
  updateGenerate();
  window.scrollTo({ top: 0, behavior: "smooth" });
}
function guarded(action) {
  return async (event) => {
    try {
      await action(event);
    } catch (error) {
      notice(error.message);
    }
  };
}
function closeEvents() {
  if (events) events.close();
  events = null;
  clearTimeout(heartbeatTimer);
}
function liveContact() {
  clearTimeout(heartbeatTimer);
  heartbeatTimer = setTimeout(() => {
    closeEvents();
    connectionFailure(
      new Error("Connection paused; reconnecting automatically."),
    );
  }, 45000);
}
function connectEvents() {
  closeEvents();
  const source = new EventSource("/api/events");
  events = source;
  source.onopen = () => {
    if (events === source) liveContact();
  };
  source.addEventListener("ping", () => {
    if (events === source) liveContact();
  });
  source.onmessage = (event) => {
    if (events !== source) return;
    liveContact();
    try {
      applyState(JSON.parse(event.data));
    } catch {
      scheduleRecovery();
    }
  };
  source.onerror = () => {
    if (events !== source) return;
    closeEvents();
    connectionFailure(
      new Error("Connection paused; reconnecting automatically."),
    );
  };
}
function scheduleRecovery() {
  if (document.hidden || !$("login").hidden || retryTimer) return;
  retryTimer = setTimeout(() => {
    retryTimer = null;
    bootstrap().catch(connectionFailure);
  }, retryDelay);
  retryDelay = Math.min(retryDelay * 2, 15000);
}
async function bootstrap() {
  if (document.hidden) return;
  if (recoveryPromise) return recoveryPromise;
  clearTimeout(retryTimer);
  retryTimer = null;
  const epoch = recoveryEpoch;
  recovering = true;
  updateGenerate();
  recoveryPromise = (async () => {
    const session = await api("/api/session");
    if (epoch !== recoveryEpoch) return;
    $("logout").hidden = !session.authentication_required;
    if (!session.authenticated) {
      showLogin();
      return;
    }
    $("login").hidden = true;
    $("workspace").hidden = false;
    connectEvents();
    // First show the backend's latest cached sampling progress, then reconcile
    // queue/history. Neither operation resubmits a prompt or replaces draft edits.
    const snapshot = api("/api/state").then((value) => {
      if (epoch === recoveryEpoch) applyState(value);
    });
    const reconciled = api("/api/resume", { method: "POST", body: "{}" }).then(
      (value) => {
        if (epoch === recoveryEpoch) applyState(value);
      },
    );
    await Promise.all([snapshot, reconciled]);
    if (epoch !== recoveryEpoch) return;
    if (!initialized || !preset) {
      await loadPresets();
      if (epoch !== recoveryEpoch) return;
      restoreUI();
      initialized = true;
    }
    connected = true;
    retryDelay = 500;
    $("offline").hidden = true;
    if (!$("gallery-page").hidden) loadGallery(true);
  })();
  try {
    await recoveryPromise;
  } finally {
    if (epoch === recoveryEpoch) {
      recovering = false;
      recoveryPromise = null;
      updateGenerate();
    }
  }
}
function pauseConnection() {
  stopGallerySync();
  saveDraft();
  saveUI();
  recoveryEpoch++;
  presetEpoch++;
  closeEvents();
  clearTimeout(retryTimer);
  retryTimer = null;
  for (const controller of requests) controller.abort();
  fullStatePending = false;
  fullStateAgain = false;
  recoveryPromise = null;
  connected = false;
  recovering = false;
  updateGenerate();
}
function foreground() {
  if (document.hidden || !$("login").hidden) return;
  bootstrap().catch(connectionFailure);
}
$("login-form").addEventListener(
  "submit",
  guarded(async (event) => {
    event.preventDefault();
    await api("/api/login", {
      method: "POST",
      body: JSON.stringify({ password: $("password").value }),
    });
    $("password").value = "";
    await bootstrap();
  }),
);
$("preset").addEventListener(
  "change",
  guarded(() => selectWorkflow($("preset").value)),
);
$("refresh-workflows").addEventListener("click", loadSavedWorkflows);
$("refresh-models").addEventListener(
  "click",
  guarded(async () => {
    if (!preset || busy) return;
    const id = preset.id;
    saveDraft();
    busy = true;
    $("refresh-models").disabled = true;
    updateGenerate();
    try {
      await api("/api/presets/" + id + "/models", { method: "POST", body: "{}" });
      if (preset?.id === id) await choosePreset(id);
      notice("Model choices refreshed.");
    } finally {
      busy = false;
      $("refresh-models").disabled = false;
      updateGenerate();
    }
  }),
);
$("generate-form").addEventListener("submit", generate);
$("dock-result").addEventListener("click", () => {
  const images = currentJob()?.images || [];
  if (images.length) openImage(images, 0);
});
$("dock-result-image").addEventListener("error", () => {
  $("dock-result-image").hidden = true;
});
new ResizeObserver(() => {
  const height = $("generation-dock").getBoundingClientRect().height;
  document.documentElement.style.setProperty("--generation-dock-height", `${height}px`);
}).observe($("generation-dock"));
$("mapping-search").addEventListener("input", renderMappings);
$("save-mapping").addEventListener(
  "click",
  guarded(async () => {
    if (!preset) return;
    const id = preset.id;
    await api("/api/presets/" + id, {
      method: "PUT",
      body: JSON.stringify({ mappings: [...mappingDraft.values()] }),
    });
    await choosePreset(id);
    notice("Input mapping saved.");
  }),
);
$("import-button").addEventListener(
  "click",
  guarded(async () => {
    const file = $("import-file").files[0];
    if (!file) throw new Error("Choose an API-format workflow JSON file.");
    if (file.size > 4 * 1024 * 1024)
      throw new Error("Workflow import is limited to 4 MB.");
    const item = await api("/api/presets", {
      method: "POST",
      body: JSON.stringify({
        name: $("import-name").value || file.name.replace(/\.json$/i, ""),
        workflow: await file.text(),
      }),
    });
    await loadPresets(item.id);
    $("advanced").open = true;
    $("mapping").open = true;
    notice("Workflow imported. Map the inputs you want to control.");
  }),
);
$("delete-preset").addEventListener(
  "click",
  guarded(async () => {
    if (
      !preset ||
      !confirm(
        "Remove this saved mobile preset? The original workflow file stays unchanged.",
      )
    )
      return;
    await api("/api/presets/" + preset.id, { method: "DELETE", body: "{}" });
    await choosePreset("");
    writeStore("preset", "");
    await loadPresets();
  }),
);
$("cancel").addEventListener(
  "click",
  guarded(async () => {
    if (
      !selectedJob ||
      !confirm(
        "Cancel this job? Running work is interrupted only when your ComfyUI supports safe per-job cancellation.",
      )
    )
      return;
    await api("/api/jobs/" + selectedJob + "/cancel", {
      method: "POST",
      body: JSON.stringify({ confirm_interrupt: true }),
    });
    applyState(await api("/api/state"));
  }),
);
$("new-request").addEventListener("click", () => {
  if (
    confirm(
      "The previous request may already be in ComfyUI. Check its queue before starting another. Continue?",
    )
  ) {
    selectedJob = "new";
    writeStore("job", "new");
    $("job-card").hidden = true;
    updateGenerate();
  }
});
$("same-seed").addEventListener(
  "click",
  guarded(() =>
    reuseJob(
      state.jobs.find((job) => job.id === selectedJob),
      false,
    ),
  ),
);
$("variation").addEventListener(
  "click",
  guarded(() =>
    reuseJob(
      state.jobs.find((job) => job.id === selectedJob),
      true,
    ),
  ),
);
$("reuse-last").addEventListener(
  "click",
  guarded(() =>
    reuseJob(
      [...state.jobs].reverse().find((job) => job.preset === preset?.id),
      false,
    ),
  ),
);
$("create-tab").addEventListener("click", () => selectTab("create"));
$("gallery-tab").addEventListener("click", () => {
  selectTab("gallery");
});
$("refresh-gallery").addEventListener("click", () => loadGallery(true));
$("close-image").addEventListener("click", () => $("image-dialog").close());
$("previous-image").addEventListener("click", () =>
  openImage(viewerItems, viewerIndex - 1),
);
$("next-image").addEventListener("click", () =>
  openImage(viewerItems, viewerIndex + 1),
);
$("reuse-image").addEventListener(
  "click",
  guarded(() =>
    reuseJob(
      state.jobs.find((job) => job.id === viewerItems[viewerIndex].job),
      false,
    ),
  ),
);
$("vary-image").addEventListener(
  "click",
  guarded(() =>
    reuseJob(
      state.jobs.find((job) => job.id === viewerItems[viewerIndex].job),
      true,
    ),
  ),
);
let touchStart = null;
$("full-image").addEventListener(
  "touchstart",
  (event) => {
    touchStart = event.changedTouches[0].clientX;
  },
  { passive: true },
);
$("full-image").addEventListener(
  "touchend",
  (event) => {
    if (
      touchStart !== null &&
      Math.abs(event.changedTouches[0].clientX - touchStart) > 55 &&
      viewerItems.length > 1
    )
      openImage(
        viewerItems,
        viewerIndex + (event.changedTouches[0].clientX < touchStart ? 1 : -1),
      );
    touchStart = null;
  },
  { passive: true },
);
$("logout").addEventListener(
  "click",
  guarded(async () => {
    await api("/api/logout", { method: "POST", body: "{}" });
    comparison.selected = [];
    comparison.selecting = false;
    comparison.update();
    pauseConnection();
    try {
      for (const key of Object.keys(localStorage))
        if (key.startsWith("comfy-mobile-")) localStorage.removeItem(key);
    } catch {}
    pendingSubmission = null;
    initialized = false;
    preset = null;
    selectedJob = null;
    state = { jobs: [], online: false };
    uiReady = false;
    uiState = {};
    showLogin();
  }),
);
document.addEventListener("visibilitychange", () => {
  document.hidden ? pauseConnection() : foreground();
});
window.addEventListener("pagehide", pauseConnection);
window.addEventListener("pageshow", foreground);
window.addEventListener("focus", foreground);
window.addEventListener("offline", () => {
  pauseConnection();
  connectionFailure(new Error("Offline. Reconnect to your LAN or VPN."));
});
window.addEventListener("online", foreground);
document.addEventListener(
  "toggle",
  (event) => {
    if (event.target.matches("details[id]")) saveUI();
  },
  true,
);
let scrollTimer;
window.addEventListener(
  "scroll",
  () => {
    if (!scrollTimer)
      scrollTimer = setTimeout(() => {
        scrollTimer = null;
        saveUI();
      }, 200);
  },
  { passive: true },
);
$("mapping-search").addEventListener("input", saveUI);
$("import-name").addEventListener("input", saveUI);
if ("serviceWorker" in navigator && window.isSecureContext)
  navigator.serviceWorker.register("/sw.js").catch(() => {});
function connectionFailure(error) {
  if (document.hidden || !$("login").hidden) return;
  connected = false;
  $("offline").hidden = false;
  $("connection").textContent = "Reconnecting…";
  $("connection").classList.remove("online");
  updateGenerate();
  scheduleRecovery();
}
const comparison = new ImageComparison({ api, notice, read: readStore, write: writeStore, unauthorized: showLogin });
const imageDetails = new ImageDetails({ api });
const promptHistory = new PromptHistoryView({ api, reuse: (entry) => {
  if (!preset) throw new Error("Choose a workflow before reusing a prompt.");
  const changes = [];
  for (const role of ["positive", "negative"]) {
    const fields = preset.fields.filter((field) => field.role === role);
    const saved = entry[role] || [];
    if (saved.length && saved.length !== fields.length)
      throw new Error("This prompt uses a different number of text inputs. Choose a matching workflow before reusing it.");
    fields.forEach((field, index) => changes.push([field.key, saved[index]?.value || ""]));
  }
  for (const [key, value] of changes) {
    draft[key] = value;
    $("control-" + key).value = value;
  }
  saveDraft();
  notice("Prompt restored. Review it, then Generate when ready.");
} });
$("reconnect").addEventListener("click", foreground);
bootstrap().catch(connectionFailure);
