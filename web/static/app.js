"use strict";

const POLL_ACTIVE_MS = 1500;
const POLL_IDLE_MS = 5000;
const TOAST_MS = 3500;
const SETTINGS_KEY = "upscale.settings";
const ACTIVE_STATUSES = ["queued", "processing"];
const STATUS_LABELS = { ready: "Ready", queued: "Queued", processing: "Working", done: "Done", error: "Failed", stopped: "Stopped" };
const STOPPING_LABEL = "Stopping";
const QUARTER_TURN_DEGREES = 90;
const QUARTER_TURNS = 4;
// en-CA formats dates as YYYY-MM-DD, used as the day key in the URL
const DAY_KEY_LOCALE = "en-CA";
const DAY_LABEL_FORMAT = { weekday: "short", day: "numeric", month: "short", year: "numeric" };
const MONTH_NAME_FORMAT = { month: "long" };
const DAY_KEY_SEPARATOR = "-";
// A date taken is the camera's own clock ("2014-08-27T11:28:30"), not a moment in any time zone
const DATE_TIME_SEPARATOR = "T";
const TAKEN_LABEL = "taken {date}";
const SETTINGS_PREVIEW_CARDS = 6;
const ROUTE_DAY_PREFIX = "#/day/";
const ROUTE_SETTINGS = "#/settings";
const ROUTE_SEARCH_PREFIX = "#/search/";
const ROUTE_HOME = "#/";
const SETTINGS_MODE_EDIT = "edit";
const SETTINGS_MODE_RERUN = "rerun";
const SETTINGS_TITLE = "Settings for {name}";
const SETTINGS_NOTE_STOPPED = "Saving starts this file over from the beginning; its partial progress is dropped.";
const SETTINGS_NOTE_READY = "Saved settings stay with this file; changes to the global settings no longer affect it.";
const SAVE_BUTTON = "Save";
const RERUN_TITLE = "Re-run {name}";
const RERUN_NOTE = "Runs the same original again as a new entry with these settings.";
const RERUN_BUTTON = "Re-run";
const RERUN_TOAST = "Re-queued {name} at {scale}×, {model}";
const RERUN_FAILED = "Re-run failed: {error}";
const RERUN_OF_LABEL = "re-run of {name}";
const RERUN_LABEL = "re-run";
const DUPLICATE_OF_LABEL = "same photo as {name} (added {date})";
const DUPLICATE_LABEL = "duplicate";
const DUPLICATE_DATE_FORMAT = { day: "numeric", month: "short" };
const SOURCE_INBOX = "inbox";
const SOURCE_INBOX_LABEL = "from inbox";
const UPLOAD_ADDED = "Added {count}. Press Start when ready.";
const UPLOAD_DUPLICATES = "{count} already here: {pairs}.";
const DUPLICATE_PAIR = "{name} = {original}";
const ZIP_URL = "files/all.zip";
const ZIP_ID_SEPARATOR = ",";
const ZIP_LABEL_SEARCH = "search";
const ZIP_TOO_MANY = "more than {max} finished files: narrow it down to zip them";
const COMPARE_ORIGINAL = "Original";
const COMPARE_UPSCALED = "Upscaled";
const STRIP_NOTE = "Click the spot to test, then Run strip: it is upscaled {scale}× with every model, without face restore.";
const STRIP_RUNNING = "Running the strip. While a file is upscaling, it runs between two of that file's tiles.";
const STRIP_FAILED = "Strip failed: {error}";
const STRIP_NOT_STARTED = "Strip not started: {error}";
const STRIP_ORIGINAL_KEY = "original";
const STRIP_ORIGINAL_LABEL = "Original";
const STRIP_CURRENT_LABEL = "{model} · this file's model";
const STRIP_USE_LABEL = "Use {model}";
const STRIP_RERUN_LABEL = "Re-run with {model}";
const STRIP_USED = "{name} now uses {model}";
const STRIP_OPEN_TITLE = "Open at full size";
// Where the marked spot starts, as a share of the photo's width and height
const STRIP_CENTRE = 0.5;
// Date and time, so two versions with the same settings can be told apart
const FINISHED_LABEL_FORMAT = { ...DAY_LABEL_FORMAT, hour: "2-digit", minute: "2-digit" };
const META_SEPARATOR = " · ";
const LOSSLESS_FORMAT = "png";
const FORMAT_QUALITY_LABEL = "{format} {quality}";
const PERCENT = 100;
const FACES_ON = "faces on";
const FACES_OFF = "faces off";
const FACES_AFTER = "faces after";
const FACE_PASS_AFTER = "after";
// "faces on" also finds the files whose faces were restored after upscaling
const FACE_RESTORE_WORDS = "faces on face restore";
const FIDELITY_LABEL = "fidelity {percent}";
const FACES_FOUND = "{count} found";
const FACES_NONE = "none found";
// Search words for the count, so "faces found 2" lists the files with two faces
const FACES_FOUND_WORDS = "faces found {count}";
const FACES_NONE_WORDS = "no faces found";
const FACE_RESTORE_HINT = "Face restore sharpens faces but can subtly change them; raise Face fidelity to keep more of the original face.";
const MEBIBYTE = 1024 * 1024;
const SYSTEM_LABELS = { device: "Device", tile: "Tile size", vram: "GPU memory", ram: "RAM available", disk: "Disk free", library: "Library" };
const CUSTOM_MODEL_SKIPPED = "Skipped: {reason}";
const TILE_FORMAT = "{tile} px";
const TILE_LABEL = "tile {tile}";
const START_ALL_TOAST = "Started {count}. They run one at a time.";
const START_REFUSED = "Not started: {list}";
const PROBLEM_SEPARATOR = "; ";
const VRAM_FORMAT = "{used} of {total} in use";
const LIBRARY_FORMAT = "{size} in {files}";
const FILE_COUNT_ONE = "{count} file";
const FILE_COUNT_MANY = "{count} files";
const DEFAULTS_SAVED = "Saved for everyone: new browsers start with these; others after Reset to defaults.";
const DEFAULTS_SAVE_FAILED = "Defaults not saved: {error}";
const DEFAULTS_RESET = "Back to the shared defaults";
const DEFAULTS_RESET_FAILED = "Reset failed: {error}";
const TEMPLATE_PLACEHOLDER = /\{(\w+)\}/g;
const ESTIMATE_READY = "Ready · about {time} at {scale}×";
const ESTIMATE_BIG_ENOUGH = "Ready · already big enough for {target}";
const TARGET_MODE_SCALE = "scale";
const TARGET_MODE_LONG_EDGE = "long_edge";
const TARGET_MODE_PRINT = "print";
// "Fit to" presets, as long edges in pixels
const TARGET_PRESETS = { "4k": 3840, "8k": 7680 };
// What the value box starts from when a long edge or a print size is picked
const TARGET_DEFAULT_LONG_EDGE = 3840;
const TARGET_DEFAULT_PRINT_CENTIMETRES = 30;
const CENTIMETRES_PER_INCH = 2.54;
const CENTIMETRE_DECIMALS = 1;
const SCALE_DECIMALS = 2;
const TARGET_UNIT_PIXELS = "px";
const TARGET_UNIT_CENTIMETRES = "cm";
const TARGET_PRINT_OPTION = "Print at {dpi} dpi, long edge…";
const FIT_LABEL = "fit {edge} px";
const PRINT_LABEL = "print {centimetres} cm";
// The panel hint: what Start makes of the first few Ready files that follow it, or of an example scan
const TARGET_HINT_FILES = 3;
const TARGET_HINT_EXAMPLE_SIZE = [1000, 750];
const TARGET_HINT_READY = "Ready files: {rows}.";
const TARGET_HINT_EXAMPLE = "A {row}.";
const TARGET_HINT_ROW = "{input} → {output} at {scale}×";
const TARGET_HINT_CAPPED = "{input} → {output} at {scale}×, the most there is";
const TARGET_HINT_BIG_ENOUGH = "{input} is already big enough";
const SCALE_HINT = "Past 4× the model runs twice for real detail.";
const ESTIMATE_QUEUED = "{position} in line · starts in about {wait} · about {time}";
const ESTIMATE_QUEUED_NEXT = "{position} in line · about {time}";
const ESTIMATE_LEFT = " · about {time} left";
const STOPPED_TEXT = "Stopped at {percent} after {time}, about {left} left. Resume continues from here.";
const WAITING_TEXT = "Waiting for the files ahead of it";
const ORDINAL_SUFFIXES = { one: "st", two: "nd", few: "rd", other: "th" };
const ESTIMATE_STEP_SECONDS = 5;
// Past this share of the work a running file's own pace predicts its end better than the history
const EXTRAPOLATE_FROM_PROGRESS = 0.1;
const PIXELS_PER_MEGAPIXEL = 1e6;

const elements = Object.fromEntries(
  ["dropzone", "file-input", "accepted", "scale", "scale-buttons", "face", "format", "target-hint",
   "model", "model-hint", "denoise", "denoise-field", "denoise-value",
   "filters", "jobs", "empty", "download-all", "start-new", "device", "toast", "job-template",
   "compare", "compare-title", "compare-close", "compare-zoom", "compare-frame", "compare-before",
   "compare-before-wrap", "compare-after", "compare-line", "compare-slider", "compare-with", "compare-with-field",
   "compare-tag-left", "compare-tag-right", "strip", "strip-title", "strip-note", "strip-image", "strip-area",
   "strip-status", "strip-grid", "strip-close", "strip-run",
   "rotate", "rotate-title", "rotate-left", "rotate-right", "rotate-image", "rotate-note", "rotate-cancel", "rotate-save",
   "day-links", "day-links-empty", "view-home", "view-day", "view-settings", "day-title", "day-count", "day-grid",
   "day-empty", "card-template", "search", "view-search", "search-title", "search-count", "search-grid",
   "search-empty", "start-all", "file-settings", "file-settings-title", "file-settings-note", "file-scale", "file-face",
   "file-format", "file-model", "file-denoise", "file-denoise-field", "file-denoise-value", "file-model-hint",
   "file-settings-global", "file-settings-cancel", "file-settings-save", "thumb-size", "thumb-size-value", "thumb-preview", "thumb-reset", "thumb-save",
   "defaults-save", "defaults-reset", "quality", "quality-field", "quality-value", "file-quality", "file-quality-field",
   "file-quality-value", "system", "custom-models", "fidelity", "fidelity-field", "fidelity-value", "file-fidelity", "file-fidelity-field",
   "file-fidelity-value", "face-pass", "face-pass-field", "file-face-pass", "file-face-pass-field", "target", "target-value",
   "target-unit", "file-target", "file-target-value", "file-target-unit", "download-day", "download-search"]
    .map((id) => [id, document.getElementById(id)]),
);

const state = { jobs: [], filter: "all", pollTimer: null, rotating: null, editing: null, preferences: null, models: {}, status: null, comparing: null, strip: null };

// ---------- API ----------

async function request(method, url, body) {
  const response = await fetch(url, { method, body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(payload.detail || `${response.status} ${response.statusText}`);
  return payload;
}

// The global settings panel and the per-file Settings dialog share one shape
const GLOBAL_CONTROLS = {
  scale: elements.scale, face: elements.face, format: elements.format, model: elements.model, denoise: elements.denoise,
  hint: elements["model-hint"], denoiseField: elements["denoise-field"], denoiseValue: elements["denoise-value"],
  quality: elements.quality, qualityField: elements["quality-field"], qualityValue: elements["quality-value"],
  fidelity: elements.fidelity, fidelityField: elements["fidelity-field"], fidelityValue: elements["fidelity-value"],
  facePass: elements["face-pass"], facePassField: elements["face-pass-field"],
  target: elements.target, targetValue: elements["target-value"], targetUnit: elements["target-unit"],
  scaleButtons: elements["scale-buttons"],
};
const FILE_CONTROLS = {
  scale: elements["file-scale"], face: elements["file-face"], format: elements["file-format"],
  model: elements["file-model"], denoise: elements["file-denoise"], hint: elements["file-model-hint"],
  denoiseField: elements["file-denoise-field"], denoiseValue: elements["file-denoise-value"],
  quality: elements["file-quality"], qualityField: elements["file-quality-field"],
  qualityValue: elements["file-quality-value"], fidelity: elements["file-fidelity"],
  fidelityField: elements["file-fidelity-field"], fidelityValue: elements["file-fidelity-value"],
  facePass: elements["file-face-pass"], facePassField: elements["file-face-pass-field"],
  target: elements["file-target"], targetValue: elements["file-target-value"], targetUnit: elements["file-target-unit"],
  scaleButtons: null,
};

function readSettings(controls) {
  return {
    scale: Number(controls.scale.value), face_enhance: controls.face.checked, format: controls.format.value,
    model: controls.model.value, denoise: Number(controls.denoise.value), quality: Number(controls.quality.value),
    face_fidelity: Number(controls.fidelity.value), face_pass: controls.facePass.value, ...readTarget(controls),
  };
}

const printCentimetres = (pixels) =>
  Number(((pixels / state.status.print_dpi) * CENTIMETRES_PER_INCH).toFixed(CENTIMETRE_DECIMALS));

// "Fit to" as the server takes it: a mode and a long edge in pixels, a print size being turned into pixels here
function readTarget(controls) {
  const choice = controls.target.value;
  const value = Number(controls.targetValue.value);
  if (Object.hasOwn(TARGET_PRESETS, choice)) return { target_mode: TARGET_MODE_LONG_EDGE, target_long_edge: TARGET_PRESETS[choice] };
  if (choice === TARGET_MODE_PRINT) {
    return { target_mode: TARGET_MODE_PRINT, target_long_edge: Math.round((value / CENTIMETRES_PER_INCH) * state.status.print_dpi) };
  }
  if (choice === TARGET_MODE_LONG_EDGE) return { target_mode: TARGET_MODE_LONG_EDGE, target_long_edge: Math.round(value) };
  return { target_mode: TARGET_MODE_SCALE, target_long_edge: 0 };
}

function writeTarget(controls, settings) {
  const edge = settings.target_long_edge;
  const preset = Object.keys(TARGET_PRESETS).find((key) => TARGET_PRESETS[key] === edge);
  const isLongEdge = settings.target_mode === TARGET_MODE_LONG_EDGE;
  controls.target.value = isLongEdge && preset ? preset : settings.target_mode;
  controls.targetValue.value = settings.target_mode === TARGET_MODE_PRINT ? printCentimetres(edge) : edge;
  renderTargetControls(controls);
}

// A new choice starts its value box from a sensible size, in that choice's unit
function resetTargetValue(controls) {
  const choice = controls.target.value;
  if (choice === TARGET_MODE_LONG_EDGE) controls.targetValue.value = TARGET_DEFAULT_LONG_EDGE;
  if (choice === TARGET_MODE_PRINT) controls.targetValue.value = TARGET_DEFAULT_PRINT_CENTIMETRES;
  renderTargetControls(controls);
}

// A long edge or a print size needs its value box; any target replaces the scale, worked out per file at Start
function renderTargetControls(controls) {
  const choice = controls.target.value;
  const isPrint = choice === TARGET_MODE_PRINT;
  const needsValue = isPrint || choice === TARGET_MODE_LONG_EDGE;
  const { min_target_long_edge: minimum, max_target_long_edge: maximum } = state.status.limits;
  controls.targetValue.hidden = !needsValue;
  controls.targetUnit.hidden = !needsValue;
  controls.targetUnit.textContent = isPrint ? TARGET_UNIT_CENTIMETRES : TARGET_UNIT_PIXELS;
  Object.assign(controls.targetValue, isPrint
    ? { min: printCentimetres(minimum), max: printCentimetres(maximum), step: 1 / 10 ** CENTIMETRE_DECIMALS }
    : { min: minimum, max: maximum, step: 1 });
  const fits = choice !== TARGET_MODE_SCALE;
  controls.scale.disabled = fits;
  controls.scaleButtons?.querySelectorAll("button").forEach((button) => { button.disabled = fits; });
}

function writeSettings(controls, settings) {
  controls.scale.value = settings.scale;
  controls.face.checked = settings.face_enhance;
  controls.fidelity.value = settings.face_fidelity;
  controls.facePass.value = settings.face_pass;
  controls.format.value = settings.format;
  // A model that has left the picker since the job ran falls back to the global one
  controls.model.value = settings.model in state.models ? settings.model : elements.model.value;
  controls.denoise.value = settings.denoise;
  controls.quality.value = settings.quality;
  writeTarget(controls, settings);
  renderModelControls(controls);
  renderFormatControls(controls);
  renderFaceControls(controls);
}

function formFromSettings(settings) {
  const form = new FormData();
  form.append("scale", settings.scale);
  form.append("face_enhance", settings.face_enhance);
  form.append("output_format", settings.format);
  form.append("model", settings.model);
  form.append("denoise", settings.denoise);
  form.append("quality", settings.quality);
  form.append("face_fidelity", settings.face_fidelity);
  form.append("face_pass", settings.face_pass);
  form.append("target_mode", settings.target_mode);
  form.append("target_long_edge", settings.target_long_edge);
  return form;
}

const settingsForm = () => formFromSettings(readSettings(GLOBAL_CONTROLS));

const api = {
  status: () => request("GET", "api/status"),
  jobs: () => request("GET", "api/jobs"),
  upload(files) {
    const form = settingsForm();
    files.forEach((file) => form.append("files", file, file.name));
    return request("POST", "api/jobs", form);
  },
  rerunWith: (id, settings) => request("POST", `api/jobs/${id}/rerun`, formFromSettings(settings)),
  strip(id, x, y, settings) {
    const form = new FormData();
    form.append("x", x);
    form.append("y", y);
    form.append("scale", settings.scale);
    form.append("denoise", settings.denoise);
    return request("POST", `api/jobs/${id}/strip`, form);
  },
  stop: (id) => request("POST", `api/jobs/${id}/stop`),
  resume: (id) => request("POST", `api/jobs/${id}/resume`),
  rotate(id, turns) {
    const form = new FormData();
    form.append("turns", turns);
    return request("POST", `api/jobs/${id}/rotate`, form);
  },
  start: (id) => request("POST", `api/jobs/${id}/start`, settingsForm()),
  setSettings: (id, settings) => request("PUT", `api/jobs/${id}/settings`, formFromSettings(settings)),
  useGlobalSettings: (id) => request("DELETE", `api/jobs/${id}/settings`),
  startAll: () => request("POST", "api/jobs/start", settingsForm()),
  rename(id, name) {
    const form = new FormData();
    form.append("name", name);
    return request("POST", `api/jobs/${id}/rename`, form);
  },
  remove: (id) => request("DELETE", `api/jobs/${id}`),
  clearFinished: () => request("POST", "api/jobs/clear"),
  preferences: () => request("GET", "api/preferences"),
  savePreferences(thumbnailSize) {
    const form = new FormData();
    form.append("thumbnail_size", thumbnailSize);
    return request("PUT", "api/preferences", form);
  },
  saveDefaults: (settings) => request("PUT", "api/preferences", formFromSettings(settings)),
};

// ---------- formatting ----------

function formatBytes(bytes) {
  const units = ["B", "KB", "MB", "GB", "TB"];
  let index = 0;
  while (bytes >= 1024 && index < units.length - 1) { bytes /= 1024; index += 1; }
  return `${bytes.toFixed(index ? 1 : 0)} ${units[index]}`;
}

function formatDuration(seconds) {
  if (seconds < 60) return `${Math.round(seconds)}s`;
  return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
}

const formatSize = (size) => (size ? `${size[0]}×${size[1]}` : "?");
const formatPercent = (fraction) => `${Math.round(fraction * PERCENT)}%`;

// A replacer function keeps "$&"-style sequences in file names literal
const fillTemplate = (template, values) =>
  template.replace(TEMPLATE_PLACEHOLDER, (placeholder, key) => String(values[key] ?? placeholder));
const joinMeta = (...parts) => parts.filter(Boolean).join(META_SEPARATOR);

function modelLabel(job) {
  const model = state.models[job.model];
  if (!model) return job.model;
  return model.has_denoise ? `${model.label} ${formatPercent(job.denoise)}` : model.label;
}

function formatLabel(settings) {
  const format = settings.format.toUpperCase();
  return settings.format === LOSSLESS_FORMAT ? format : fillTemplate(FORMAT_QUALITY_LABEL, { format, quality: settings.quality });
}

// "3 found" on rows, "faces found 3" for search; only finished runs have a count
function facesFoundText(job, foundTemplate, noneText) {
  if (typeof job.faces_found !== "number") return "";
  return job.faces_found ? fillTemplate(foundTemplate, { count: job.faces_found }) : noneText;
}

function facesLabel(settings) {
  if (!settings.face_enhance) return FACES_OFF;
  const restored = settings.face_pass === FACE_PASS_AFTER ? FACES_AFTER : FACES_ON;
  const fidelity = settings.face_fidelity ? fillTemplate(FIDELITY_LABEL, { percent: formatPercent(settings.face_fidelity) }) : "";
  return joinMeta(restored, fidelity, facesFoundText(settings, FACES_FOUND, FACES_NONE));
}

const formatScale = (scale) => Number(scale.toFixed(SCALE_DECIMALS));

// Mirrors fitted_settings in jobs.py: a target long edge becomes the scale that brings this file's long edge there
function fittedScale(job, settings) {
  if (settings.target_mode === TARGET_MODE_SCALE) return settings.scale;
  return Math.min(settings.target_long_edge / Math.max(...job.input_size), state.status.limits.max_scale);
}

// Mirrors result_size in jobs.py
const resultSize = (size, scale) => size.map((edge) => Math.trunc(edge * scale));

function targetLabel(settings) {
  if (settings.target_mode === TARGET_MODE_PRINT) {
    return fillTemplate(PRINT_LABEL, { centimetres: printCentimetres(settings.target_long_edge) });
  }
  if (settings.target_mode === TARGET_MODE_LONG_EDGE) return fillTemplate(FIT_LABEL, { edge: settings.target_long_edge });
  return "";
}

// The scale, or the target it is worked out from; a file that has started shows both
function sizeLabel(settings) {
  const scale = `${formatScale(settings.scale)}×`;
  const target = targetLabel(settings);
  if (!target) return scale;
  const started = Boolean(settings.status) && settings.status !== "ready";
  return started ? joinMeta(scale, target) : target;
}

function settingsSummary(settings) {
  return joinMeta(sizeLabel(settings), modelLabel(settings), facesLabel(settings), formatLabel(settings));
}

// A Ready file without its own settings follows the global panel until it starts
const followsGlobal = (job) => job.status === "ready" && !job.custom_settings;
const effectiveSettings = (job) => (followsGlobal(job) ? readSettings(GLOBAL_CONTROLS) : job);
const isLocked = (job) => ["queued", "processing"].includes(job.status);
const canEditSettings = (job) => ["ready", "stopped"].includes(job.status);

const takenDay = (job) => job.taken?.split(DATE_TIME_SEPARATOR)[0];

// When the photo was taken and with which camera, from its EXIF
function photoLabel(job) {
  const taken = job.taken ? fillTemplate(TAKEN_LABEL, { date: dayLabel(takenDay(job)) }) : "";
  return joinMeta(taken, job.camera);
}

// Shown only when a run used a tile other than the configured one, which means an out-of-memory retry
function tileLabel(job) {
  const configuredTile = state.status?.system.tile;
  const differs = Boolean(job.tile && configuredTile && job.tile !== configuredTile);
  return differs ? fillTemplate(TILE_LABEL, { tile: job.tile }) : "";
}

// An upload found to be the same photo as one already here, which may since have been removed
// ponytail: linear lookup per job (O(n²) per render), here and in rerunLabel; index state.jobs by id if the library
// reaches thousands.
function duplicateLabel(job) {
  if (!job.duplicate_of) return "";
  const original = state.jobs.find((candidate) => candidate.id === job.duplicate_of);
  if (!original) return DUPLICATE_LABEL;
  const date = new Date(original.created * 1000).toLocaleDateString(undefined, DUPLICATE_DATE_FORMAT);
  return fillTemplate(DUPLICATE_OF_LABEL, { name: original.name, date });
}

// Re-runs name the file they came from; that file may since have been removed.
function rerunLabel(job) {
  if (!job.source_id) return "";
  const source = state.jobs.find((candidate) => candidate.id === job.source_id);
  return source ? fillTemplate(RERUN_OF_LABEL, { name: source.name }) : RERUN_LABEL;
}

const sourceLabel = (job) => (job.source === SOURCE_INBOX ? SOURCE_INBOX_LABEL : "");

function jobMeta(job) {
  if (canEditSettings(job)) {
    const source = followsGlobal(job) ? "Global" : "Own settings";
    return `${formatSize(job.input_size)} · ${source}: ${settingsSummary(effectiveSettings(job))}`;
  }
  const settings = `${settingsSummary(job)}${isLocked(job) ? " · locked" : ""}`;
  if (job.status === "done") {
    return `${formatSize(job.input_size)} → ${formatSize(job.output_size)} · ${formatBytes(job.output_bytes)} · ${settings}`;
  }
  return `${formatSize(job.input_size)} · ${settings}`;
}

// Time spent processing, summed across Stop/Resume
function processingSeconds(job) {
  const running = job.status === "processing" ? Date.now() / 1000 - job.started : 0;
  return job.elapsed + running;
}

const ordinalRules = new Intl.PluralRules("en-US", { type: "ordinal" });
const ordinal = (number) => `${number}${ORDINAL_SUFFIXES[ordinalRules.select(number)]}`;
const formatEstimate = (seconds) =>
  formatDuration(Math.max(ESTIMATE_STEP_SECONDS, Math.round(seconds / ESTIMATE_STEP_SECONDS) * ESTIMATE_STEP_SECONDS));

// Mirrors work_megapixels in jobs.py: one pass at the model's scale, plus a second on the enlarged image past it
function workMegapixels(inputSize, scale) {
  const modelScale = state.status.speed.model_scale;
  const passes = modelScale ** 2 + (scale > modelScale ? scale ** 2 : 0);
  return (inputSize[0] * inputSize[1] * passes) / PIXELS_PER_MEGAPIXEL;
}

// From this machine's past runs with the same model and face setting, or all of them when there are too few
function estimateSeconds(job, settings) {
  const { speed } = state.status;
  const match = speed.by_settings.find((entry) => entry.model === settings.model && entry.face_enhance === settings.face_enhance);
  return (match ? match.seconds_per_megapixel : speed.default) * workMegapixels(job.input_size, fittedScale(job, settings));
}

function remainingSeconds(job) {
  const spent = processingSeconds(job);
  if (job.progress >= EXTRAPOLATE_FROM_PROGRESS) return (spent * (1 - job.progress)) / job.progress;
  // A stopped file this early starts nearly from scratch; a running one has its first moments behind it
  const behind = job.status === "processing" ? spent : 0;
  return Math.max(0, estimateSeconds(job, job) - behind);
}

// What is left of the running file plus the queued ones ahead of this one
function startsInSeconds(job) {
  const running = state.jobs.filter((other) => other.status === "processing").map(remainingSeconds);
  const ahead = state.jobs.filter((other) => other.queue_position && other.queue_position < job.queue_position)
    .map((other) => estimateSeconds(other, other));
  return [...running, ...ahead].reduce((total, seconds) => total + seconds, 0);
}

function readyText(job) {
  const settings = effectiveSettings(job);
  const scale = fittedScale(job, settings);
  if (scale < state.status.limits.min_scale) return fillTemplate(ESTIMATE_BIG_ENOUGH, { target: targetLabel(settings) });
  return fillTemplate(ESTIMATE_READY, { time: formatEstimate(estimateSeconds(job, settings)), scale: formatScale(scale) });
}

function queuedText(job) {
  // No place in line means the worker is taking this file right now
  if (!job.queue_position) return WAITING_TEXT;
  const position = ordinal(job.queue_position);
  const time = formatEstimate(estimateSeconds(job, job));
  const wait = startsInSeconds(job);
  if (wait < ESTIMATE_STEP_SECONDS) return fillTemplate(ESTIMATE_QUEUED_NEXT, { position, time });
  return fillTemplate(ESTIMATE_QUEUED, { position, wait: formatEstimate(wait), time });
}

function progressText(job) {
  const percent = `${Math.floor(job.progress * 100)}%`;
  const time = formatDuration(processingSeconds(job));
  const left = formatEstimate(remainingSeconds(job));
  if (job.status === "processing") return `${job.stage} · ${percent} · ${time} so far${fillTemplate(ESTIMATE_LEFT, { time: left })}`;
  if (job.status === "done") return `Finished in ${time}`;
  if (job.status === "stopped") return fillTemplate(STOPPED_TEXT, { percent, time, left });
  if (job.status === "error") return `Failed after ${time}`;
  if (job.status === "ready") return readyText(job);
  return queuedText(job);
}

const previewUrl = (job) => `files/preview/${job.id}?r=${job.rotation}`;
const outputUrl = (job) => `files/output/${job.id}?r=${job.rotation}`;
const resultPreviewUrl = (job) => `files/result-preview/${job.id}?r=${job.rotation}`;
// Finished files show their result; everything else the original
const thumbnailUrl = (job) => (job.status === "done" ? resultPreviewUrl(job) : previewUrl(job));
// View shows light previews of results; "1:1 pixels" loads the full files
const compareResultUrl = (job) => (elements["compare-zoom"].checked ? outputUrl(job) : resultPreviewUrl(job));

function toast(message) {
  elements.toast.textContent = message;
  elements.toast.classList.add("show");
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => elements.toast.classList.remove("show"), TOAST_MS);
}

// ---------- settings ----------

function saveSettings() {
  const settings = {
    scale: elements.scale.value, face: elements.face.checked, format: elements.format.value,
    model: elements.model.value, denoise: elements.denoise.value, quality: elements.quality.value,
    fidelity: elements.fidelity.value, facePass: elements["face-pass"].value, ...readTarget(GLOBAL_CONTROLS),
  };
  try { localStorage.setItem(SETTINGS_KEY, JSON.stringify(settings)); } catch { /* private mode */ }
  renderScaleButtons();
  renderJobs();
}

function loadSettings(defaults) {
  let saved = {};
  try { saved = JSON.parse(localStorage.getItem(SETTINGS_KEY)) || {}; } catch { /* ignore */ }
  elements.scale.value = saved.scale ?? defaults.scale;
  elements.face.checked = saved.face ?? defaults.face_enhance;
  elements.format.value = saved.format ?? defaults.format;
  elements.model.value = saved.model in state.models ? saved.model : defaults.model;
  elements.denoise.value = saved.denoise ?? defaults.denoise;
  elements.quality.value = saved.quality ?? defaults.quality;
  elements.fidelity.value = saved.fidelity ?? defaults.face_fidelity;
  elements["face-pass"].value = saved.facePass ?? defaults.face_pass;
  writeTarget(GLOBAL_CONTROLS, {
    target_mode: saved.target_mode ?? defaults.target_mode, target_long_edge: saved.target_long_edge ?? defaults.target_long_edge,
  });
  renderScaleButtons();
}

// This browser follows the shared defaults again, until someone changes a setting here
function forgetOwnSettings() {
  try { localStorage.removeItem(SETTINGS_KEY); } catch { /* private mode */ }
}

async function saveDefaults() {
  try {
    await api.saveDefaults(readSettings(GLOBAL_CONTROLS));
    forgetOwnSettings();
    toast(DEFAULTS_SAVED);
  } catch (error) {
    toast(fillTemplate(DEFAULTS_SAVE_FAILED, { error: error.message }));
  }
}

async function resetToDefaults() {
  try {
    const { defaults } = await api.preferences();
    forgetOwnSettings();
    loadSettings(defaults);
    renderJobs();
    toast(DEFAULTS_RESET);
  } catch (error) {
    toast(fillTemplate(DEFAULTS_RESET_FAILED, { error: error.message }));
  }
}

function renderScaleButtons() {
  const scale = Number(elements.scale.value);
  elements["scale-buttons"].querySelectorAll("button").forEach((button) => {
    button.classList.toggle("active", Number(button.dataset.scale) === scale);
  });
  renderTargetControls(GLOBAL_CONTROLS);
  renderModelControls(GLOBAL_CONTROLS);
  renderFormatControls(GLOBAL_CONTROLS);
  renderFaceControls(GLOBAL_CONTROLS);
}

function targetHintRow(size, settings) {
  const input = formatSize(size);
  const scale = fittedScale({ input_size: size }, settings);
  const { min_scale: minimum, max_scale: maximum } = state.status.limits;
  if (scale < minimum) return fillTemplate(TARGET_HINT_BIG_ENOUGH, { input });
  const capped = scale === maximum && Math.max(...size) * maximum < settings.target_long_edge;
  const values = { input, output: formatSize(resultSize(size, scale)), scale: formatScale(scale) };
  return fillTemplate(capped ? TARGET_HINT_CAPPED : TARGET_HINT_ROW, values);
}

// What Start would make of the first Ready files that follow the panel, or of an example scan when there are none
function renderTargetHint() {
  const settings = readSettings(GLOBAL_CONTROLS);
  const following = state.jobs.filter(followsGlobal).slice(0, TARGET_HINT_FILES);
  const sizes = following.length
    ? fillTemplate(TARGET_HINT_READY, { rows: following.map((job) => targetHintRow(job.input_size, settings)).join(META_SEPARATOR) })
    : fillTemplate(TARGET_HINT_EXAMPLE, { row: targetHintRow(TARGET_HINT_EXAMPLE_SIZE, settings) });
  elements["target-hint"].textContent = [sizes, SCALE_HINT, FACE_RESTORE_HINT].join(" ");
}

// Quality only means something for the lossy formats, the way Denoise only does for the General v3 model
function renderFormatControls(controls) {
  controls.qualityField.hidden = controls.format.value === LOSSLESS_FORMAT;
  controls.qualityValue.textContent = controls.quality.value;
}

function renderModelControls(controls) {
  const model = state.models[controls.model.value];
  controls.hint.textContent = `${model.label}: ${model.hint} Re-run a photo with another model to compare.`;
  controls.denoiseField.hidden = !model.has_denoise;
  controls.denoiseValue.textContent = formatPercent(controls.denoise.value);
}

// Fidelity and when faces are restored only mean something while face restore is on
function renderFaceControls(controls) {
  controls.fidelityField.hidden = !controls.face.checked;
  controls.facePassField.hidden = !controls.face.checked;
  controls.fidelityValue.textContent = formatPercent(controls.fidelity.value);
}

// ---------- rendering ----------

const isActive = (job) => ACTIVE_STATUSES.includes(job.status);
const FILTERS = {
  all: () => true,
  ready: (job) => job.status === "ready",
  active: isActive,
  stopped: (job) => job.status === "stopped",
  done: (job) => job.status === "done",
  error: (job) => job.status === "error",
};

function renderJob(job) {
  const item = elements["job-template"].content.firstElementChild.cloneNode(true);
  const isDone = job.status === "done";
  const isProcessing = job.status === "processing";
  const isStopping = isProcessing && job.stop_requested;
  item.dataset.id = job.id;
  item.querySelector(".thumb").src = thumbnailUrl(job);
  item.querySelector(".job-name").textContent = job.name;
  item.querySelector(".job-name").title = job.name;
  item.querySelector(".job-meta").textContent =
    joinMeta(jobMeta(job), tileLabel(job), photoLabel(job), sourceLabel(job), rerunLabel(job), duplicateLabel(job));
  item.querySelector(".job-error").textContent = job.error ? `Error: ${job.error}` : "";
  item.querySelector("progress").value = job.progress;
  item.querySelector(".job-progress").dataset.status = job.status;
  item.querySelector(".progress-text").textContent = progressText(job);
  const status = item.querySelector(".status");
  status.textContent = isStopping ? STOPPING_LABEL : STATUS_LABELS[job.status];
  status.className = `status ${job.status}`;
  item.querySelector('[data-action="start"]').hidden = job.status !== "ready";
  item.querySelector('[data-action="compare"]').hidden = !isDone;
  const download = item.querySelector('[data-action="download"]');
  download.hidden = !isDone;
  download.href = `files/output/${job.id}?download=true`;
  item.querySelector('[data-action="settings"]').hidden = !canEditSettings(job);
  item.querySelector('[data-action="rotate"]').hidden = isLocked(job);
  item.querySelector('[data-action="stop"]').hidden = !isActive(job) || isStopping;
  item.querySelector('[data-action="resume"]').hidden = job.status !== "stopped";
  item.querySelector('[data-action="rerun"]').hidden = !["done", "error"].includes(job.status);
  item.querySelector('[data-action="delete"]').hidden = isProcessing;
  return item;
}

function renderJobs() {
  // Start new clears finished files off this list only; they stay in the day pages
  const listed = state.jobs.filter((job) => !job.cleared);
  const visible = listed.filter(FILTERS[state.filter]);
  elements.jobs.replaceChildren(...visible.map(renderJob));
  elements.empty.hidden = visible.length > 0;

  for (const [name, matches] of Object.entries(FILTERS)) {
    elements.filters.querySelector(`[data-count="${name}"]`).textContent = listed.filter(matches).length;
  }
  elements["start-all"].hidden = !listed.some(FILTERS.ready);
  const doneCount = listed.filter(FILTERS.done).length;
  elements["download-all"].setAttribute("aria-disabled", doneCount === 0);
  const activeCount = state.jobs.filter(isActive).length;
  document.title = activeCount ? `(${activeCount}) Upscale` : "Upscale";
  renderTargetHint();
}

// ---------- pages ----------

function currentRoute() {
  const hash = location.hash;
  if (hash.startsWith(ROUTE_DAY_PREFIX)) return { page: "day", day: decodeURIComponent(hash.slice(ROUTE_DAY_PREFIX.length)) };
  if (hash === ROUTE_SETTINGS) return { page: "settings" };
  if (hash.startsWith(ROUTE_SEARCH_PREFIX)) return { page: "search", query: decodeURIComponent(hash.slice(ROUTE_SEARCH_PREFIX.length)) };
  return { page: "home" };
}

const dayKey = (job) => new Date(job.finished * 1000).toLocaleDateString(DAY_KEY_LOCALE);

function dayLabel(key) {
  const [year, month, day] = key.split(DAY_KEY_SEPARATOR).map(Number);
  return new Date(year, month - 1, day).toLocaleDateString(undefined, DAY_LABEL_FORMAT);
}

// Every spelling a person might search a day by: 2014-08-27, Wed 27 Aug 2014, August
function dayWords(key) {
  const [year, month] = key.split(DAY_KEY_SEPARATOR).map(Number);
  return `${key} ${dayLabel(key)} ${new Date(year, month - 1).toLocaleDateString(undefined, MONTH_NAME_FORMAT)}`;
}

// Finished files grouped by the local day they finished, newest day and newest file first
function finishedByDay() {
  const days = new Map();
  const finished = state.jobs.filter(FILTERS.done).sort((first, second) => second.finished - first.finished);
  for (const job of finished) {
    const key = dayKey(job);
    days.set(key, [...(days.get(key) || []), job]);
  }
  return days;
}

function renderSidebar(route, days) {
  const links = [...days].map(([key, jobs]) => {
    const item = document.createElement("li");
    const link = document.createElement("a");
    link.href = `${ROUTE_DAY_PREFIX}${key}`;
    link.className = "nav-link";
    link.classList.toggle("active", route.page === "day" && route.day === key);
    link.append(dayLabel(key), Object.assign(document.createElement("b"), { textContent: jobs.length }));
    item.append(link);
    return item;
  });
  elements["day-links"].replaceChildren(...links);
  elements["day-links-empty"].hidden = links.length > 0;
  document.querySelectorAll("[data-route]").forEach((link) => link.classList.toggle("active", link.dataset.route === route.page));
}

function cardMeta(job) {
  if (job.status !== "done") return `${STATUS_LABELS[job.status]} · ${formatSize(job.input_size)}`;
  const faces = job.face_enhance ? facesLabel(job) : "";
  return joinMeta(formatSize(job.output_size), formatBytes(job.output_bytes), sizeLabel(job), modelLabel(job), faces);
}

function renderCard(job) {
  const card = elements["card-template"].content.firstElementChild.cloneNode(true);
  const isDone = job.status === "done";
  const isProcessing = job.status === "processing";
  card.dataset.id = job.id;
  card.querySelector("img").src = thumbnailUrl(job);
  card.querySelector(".card-image").dataset.action = isDone ? "compare" : "";
  card.querySelector(".card-name").textContent = job.name;
  card.querySelector(".card-name").title = job.name;
  card.querySelector(".card-meta").textContent =
    joinMeta(cardMeta(job), photoLabel(job), sourceLabel(job), rerunLabel(job), duplicateLabel(job));
  card.querySelector('[data-action="compare"]').hidden = !isDone;
  const download = card.querySelector('[data-action="download"]');
  download.hidden = !isDone;
  download.href = `files/output/${job.id}?download=true`;
  card.querySelector('[data-action="rotate"]').hidden = isLocked(job);
  card.querySelector('[data-action="delete"]').hidden = isProcessing;
  return card;
}

// Everything a person might type to find a file: name, dates, sizes, settings, status, camera, where it came from
function searchText(job) {
  const addedAndFinished = [job.created, job.finished].filter(Boolean)
    .map((seconds) => new Date(seconds * 1000).toLocaleDateString(DAY_KEY_LOCALE));
  const days = [...addedAndFinished, takenDay(job)].filter(Boolean).map(dayWords);
  const sizes = [job.input_size, job.output_size].filter(Boolean).map(([width, height]) => `${width}×${height} ${width}x${height}`);
  return [
    job.name, ...days, ...sizes, `${formatScale(job.scale)}× ${formatScale(job.scale)}x`, targetLabel(job), modelLabel(job),
    job.model,
    facesLabel(job), job.face_enhance ? FACE_RESTORE_WORDS : "", facesFoundText(job, FACES_FOUND_WORDS, FACES_NONE_WORDS),
    job.format, STATUS_LABELS[job.status], job.camera,
    job.format === LOSSLESS_FORMAT ? "" : `quality ${job.quality}`, job.tile ? `tile ${job.tile}` : "", sourceLabel(job),
    rerunLabel(job), job.duplicate_of ? DUPLICATE_LABEL : "", duplicateLabel(job),
  ].join(" ").toLowerCase();
}

// Words found together, like "faces found 2" or "quality 85", list only those files; otherwise every word must match
function searchJobs(query) {
  const terms = query.toLowerCase().split(/\s+/).filter(Boolean);
  const phrase = terms.join(" ");
  const texts = state.jobs.map((job) => ({ job, text: searchText(job) }));
  const together = texts.filter(({ text }) => text.includes(phrase));
  const matches = together.length ? together : texts.filter(({ text }) => terms.every((term) => text.includes(term)));
  return matches.map(({ job }) => job);
}

// Points a page's zip button at its finished files, named after the page. Returns why it can't, when there are too
// many for one request.
function renderZipLink(link, label, jobs) {
  const finished = jobs.filter(FILTERS.done);
  const limit = state.status.zip_max_files;
  const tooMany = finished.length > limit;
  const ids = finished.map((job) => job.id).join(ZIP_ID_SEPARATOR);
  link.href = `${ZIP_URL}?label=${encodeURIComponent(label)}&ids=${ids}`;
  link.setAttribute("aria-disabled", finished.length === 0 || tooMany);
  return tooMany ? fillTemplate(ZIP_TOO_MANY, { max: limit }) : "";
}

function renderSearch(query) {
  const results = query.trim() ? searchJobs(query) : [];
  elements["search-title"].textContent = `Search: ${query}`;
  const zipNote = renderZipLink(elements["download-search"], ZIP_LABEL_SEARCH, results);
  elements["search-count"].textContent = joinMeta(`${results.length} file${results.length === 1 ? "" : "s"}`, zipNote);
  elements["search-grid"].replaceChildren(...results.map(renderCard));
  elements["search-empty"].hidden = results.length > 0;
}

function renderPlaceholderCard() {
  const card = elements["card-template"].content.firstElementChild.cloneNode(true);
  card.querySelector("img").remove();
  card.querySelector(".card-name").textContent = "photo.jpg";
  card.querySelector(".card-meta").textContent = "Your finished files look like this";
  card.querySelectorAll(".card-actions > *").forEach((control) => { control.inert = true; });
  return card;
}

function renderDay(day, days) {
  const jobs = days.get(day) || [];
  elements["day-title"].textContent = dayLabel(day);
  const zipNote = renderZipLink(elements["download-day"], day, jobs);
  elements["day-count"].textContent = joinMeta(`${jobs.length} file${jobs.length === 1 ? "" : "s"}`, zipNote);
  elements["day-grid"].replaceChildren(...jobs.map(renderCard));
  elements["day-empty"].hidden = jobs.length > 0;
}

function renderSettingsPreview() {
  const latest = state.jobs.filter(FILTERS.done).slice(0, SETTINGS_PREVIEW_CARDS);
  const cards = latest.length ? latest.map(renderCard) : Array.from({ length: SETTINGS_PREVIEW_CARDS }, renderPlaceholderCard);
  elements["thumb-preview"].replaceChildren(...cards);
}

function setThumbnailSize(target, size) {
  target.style.setProperty("--thumb-size", `${size}px`);
}

function previewThumbnailSize(size) {
  elements["thumb-size"].value = size;
  elements["thumb-size-value"].textContent = `${size} px`;
  setThumbnailSize(elements["thumb-preview"], size);
}

function applyPreferences(preferences) {
  state.preferences = preferences;
  const { min, max, step } = preferences.limits;
  Object.assign(elements["thumb-size"], { min, max, step });
  setThumbnailSize(document.documentElement, preferences.thumbnail_size);
  previewThumbnailSize(preferences.thumbnail_size);
}

function renderPage() {
  const route = currentRoute();
  const days = finishedByDay();
  renderSidebar(route, days);
  elements["view-home"].hidden = route.page !== "home";
  elements["view-day"].hidden = route.page !== "day";
  elements["view-settings"].hidden = route.page !== "settings";
  elements["view-search"].hidden = route.page !== "search";
  if (route.page !== "search") elements.search.value = "";
  if (route.page === "search" && document.activeElement !== elements.search) elements.search.value = route.query;
  if (route.page === "search") renderSearch(route.query);
  if (route.page === "day") renderDay(route.day, days);
  if (route.page === "settings") renderSettingsPreview();
  if (route.page === "settings" && state.status) renderSystem(state.status);
  if (route.page === "settings" && state.status) renderCustomModels(state.status);
}

// Label and value for each System line; a value the server could not read, like GPU memory on a CPU, is left out
function systemRows(status) {
  const { system } = status;
  const size = (mebibytes) => (mebibytes === null ? "" : formatBytes(mebibytes * MEBIBYTE));
  const vram = system.vram_total_mb === null ? ""
    : fillTemplate(VRAM_FORMAT, { used: size(system.vram_used_mb), total: size(system.vram_total_mb) });
  const files = fillTemplate(system.jobs === 1 ? FILE_COUNT_ONE : FILE_COUNT_MANY, { count: system.jobs });
  return [
    [SYSTEM_LABELS.device, status.device],
    [SYSTEM_LABELS.tile, fillTemplate(TILE_FORMAT, { tile: system.tile })],
    [SYSTEM_LABELS.vram, vram],
    [SYSTEM_LABELS.ram, size(system.ram_available_mb)],
    [SYSTEM_LABELS.disk, size(system.disk_free_mb)],
    [SYSTEM_LABELS.library, fillTemplate(LIBRARY_FORMAT, { size: size(system.library_mb), files })],
  ].filter(([, value]) => value);
}

const definitionItems = (rows) => rows.flatMap(([label, value]) => [
  Object.assign(document.createElement("dt"), { textContent: label }),
  Object.assign(document.createElement("dd"), { textContent: value }),
]);

function renderSystem(status) {
  elements.system.replaceChildren(...definitionItems(systemRows(status)));
}

// What the last start found in data/models: the models it added, then the files it left out and why
function renderCustomModels(status) {
  const added = status.models.filter((model) => model.custom).map((model) => [model.label, model.hint]);
  const skipped = status.custom_models_skipped.map(({ file, reason }) => [file, fillTemplate(CUSTOM_MODEL_SKIPPED, { reason })]);
  elements["custom-models"].replaceChildren(...definitionItems([...added, ...skipped]));
}

function renderDevice(status) {
  const device = elements.device;
  device.className = "device";
  device.title = systemRows(status).map(([label, value]) => `${label}: ${value}`).join(META_SEPARATOR);
  if (status.error) {
    device.textContent = `engine failed: ${status.error}`;
    device.classList.add("failed");
    return;
  }
  device.textContent = status.ready ? status.device : `${status.device} · loading models…`;
  device.classList.toggle("gpu", status.device.startsWith("GPU"));
  device.classList.toggle("loading", !status.ready);
}

// ---------- polling ----------

async function refresh() {
  clearTimeout(state.pollTimer);
  try {
    const [status, jobs] = await Promise.all([api.status(), api.jobs()]);
    const endedNow = state.jobs.filter(isActive)
      .map((old) => jobs.find((job) => job.id === old.id))
      .filter((current) => current && ["done", "error"].includes(current.status));
    const failedNow = endedNow.filter((job) => job.status === "error");
    const finishedNow = endedNow.filter((job) => job.status === "done");
    if (finishedNow.length) toast(`Finished: ${finishedNow.map((job) => job.name).join(", ")}`);
    if (failedNow.length) toast(`Failed: ${failedNow.map((job) => `${job.name}: ${job.error}`).join("; ")}`);
    state.jobs = jobs;
    state.status = status;
    renderDevice(status);
    renderJobs();
    renderPage();
    if (elements.strip.open) renderStrip();
  } catch (error) {
    elements.device.textContent = "server unreachable";
    elements.device.className = "device failed";
    elements.device.title = "";
  }
  const busy = state.jobs.some(isActive) || state.jobs.some(stripPending);
  state.pollTimer = setTimeout(refresh, busy ? POLL_ACTIVE_MS : POLL_IDLE_MS);
}

// ---------- actions ----------

async function uploadFiles(fileList) {
  const files = [...fileList];
  if (!files.length) return;
  toast(`Uploading ${files.length} file${files.length > 1 ? "s" : ""}…`);
  try {
    const result = await api.upload(files);
    const rejected = result.rejected.map((item) => `${item.name}: ${item.error}`);
    // The photo a duplicate matches may have come in this same upload
    const known = [...result.created, ...state.jobs];
    const pairs = result.created.filter((job) => job.duplicate_of).map((job) => fillTemplate(DUPLICATE_PAIR, {
      name: job.name, original: known.find((other) => other.id === job.duplicate_of)?.name ?? DUPLICATE_LABEL,
    }));
    const duplicates = pairs.length ? fillTemplate(UPLOAD_DUPLICATES, { count: pairs.length, pairs: pairs.join(PROBLEM_SEPARATOR) }) : "";
    const added = [fillTemplate(UPLOAD_ADDED, { count: result.created.length }), duplicates].filter(Boolean).join(" ");
    toast(rejected.length ? `Skipped ${rejected.join("; ")}` : added);
  } catch (error) {
    toast(`Upload failed: ${error.message}`);
  }
  refresh();
}

async function runAction(action, id) {
  const job = state.jobs.find((candidate) => candidate.id === id);
  if (action === "compare") return openCompare(job);
  if (action === "rotate") return openRotate(job);
  if (action === "strip") return openStrip(job);
  if (action === "download" || !action) return;
  if (action === "rename") return renameJob(job);
  if (action === "settings") return openFileSettings(job, SETTINGS_MODE_EDIT);
  if (action === "rerun") return openFileSettings(job, SETTINGS_MODE_RERUN);
  if (action === "delete" && !confirm(`Remove ${job.name}? The original and the result are deleted for good.`)) return;
  try {
    if (action === "start") await api.start(id);
    if (action === "stop") await api.stop(id);
    if (action === "resume") await api.resume(id);
    if (action === "delete") await api.remove(id);
  } catch (error) {
    toast(error.message);
  }
  refresh();
}

const settingsNote = (job) => (job.status === "stopped" ? SETTINGS_NOTE_STOPPED : SETTINGS_NOTE_READY);

// One dialog for both: editing a file's own settings, and choosing the settings of a re-run
function openFileSettings(job, mode) {
  const isRerun = mode === SETTINGS_MODE_RERUN;
  state.editing = { job, mode };
  elements["file-settings-title"].textContent = fillTemplate(isRerun ? RERUN_TITLE : SETTINGS_TITLE, { name: job.name });
  elements["file-settings-note"].textContent = isRerun ? RERUN_NOTE : settingsNote(job);
  elements["file-settings-save"].textContent = isRerun ? RERUN_BUTTON : SAVE_BUTTON;
  elements["file-settings-global"].hidden = isRerun || !job.custom_settings;
  // A re-run starts from what the file ran with; editing starts from what it would run with
  writeSettings(FILE_CONTROLS, isRerun ? job : effectiveSettings(job));
  elements["file-settings"].showModal();
}

async function saveFileSettings(useGlobal) {
  const { job, mode } = state.editing;
  const settings = readSettings(FILE_CONTROLS);
  elements["file-settings"].close();
  if (mode === SETTINGS_MODE_RERUN) return rerunJob(job, settings);
  try {
    await (useGlobal ? api.useGlobalSettings(job.id) : api.setSettings(job.id, settings));
    toast(useGlobal ? `${job.name} follows the global settings again` : `Saved settings for ${job.name}`);
  } catch (error) {
    toast(`Settings not saved: ${error.message}`);
  }
  refresh();
}

// ---------- test strip ----------

const stripPending = (job) => job.strip?.status === "pending";
const stripImageUrl = (job, key) => `files/strip/${job.id}/${encodeURIComponent(key)}?v=${job.strip.requested}`;
const stripJob = () => state.jobs.find((candidate) => candidate.id === state.strip.jobId);
// The file's own scale, a target worked out for its size; at least 1×, even for one already big enough
const stripScale = (job) => Math.max(state.status.limits.min_scale, fittedScale(job, effectiveSettings(job)));

// Mirrors strip_crop in upscaler.py: the part of the photo a strip upscales, as shares of its width and height
function stripArea(job, x, y, scale) {
  const [width, height] = job.input_size;
  const edge = Math.min(state.status.system.tile, Math.round(state.status.strip_output_edge / scale));
  const cropWidth = Math.min(edge, width);
  const cropHeight = Math.min(edge, height);
  const left = Math.min(Math.max(Math.round(x * width - cropWidth / 2), 0), width - cropWidth);
  const top = Math.min(Math.max(Math.round(y * height - cropHeight / 2), 0), height - cropHeight);
  return { left: left / width, top: top / height, width: cropWidth / width, height: cropHeight / height };
}

function placeStripArea(job) {
  const area = stripArea(job, state.strip.x, state.strip.y, stripScale(job));
  Object.assign(elements["strip-area"].style, {
    left: `${area.left * PERCENT}%`, top: `${area.top * PERCENT}%`,
    width: `${area.width * PERCENT}%`, height: `${area.height * PERCENT}%`,
  });
}

function stripStatusText(job) {
  if (stripPending(job)) return STRIP_RUNNING;
  if (job.strip?.status === "error") return fillTemplate(STRIP_FAILED, { error: job.strip.error });
  return "";
}

// Ready and stopped files take the model as their own setting; finished and failed ones re-run with it
function stripAction(job, key, label, currentModel) {
  const canRerun = ["done", "error"].includes(job.status);
  const canUse = canRerun || canEditSettings(job);
  if (key === STRIP_ORIGINAL_KEY || key === currentModel || !canUse) return null;
  const button = Object.assign(document.createElement("button"), {
    type: "button", className: "button subtle",
    textContent: fillTemplate(canRerun ? STRIP_RERUN_LABEL : STRIP_USE_LABEL, { model: label }),
  });
  button.dataset.model = key;
  return button;
}

function stripCard(job, key, currentModel) {
  const isOriginal = key === STRIP_ORIGINAL_KEY;
  const label = isOriginal ? STRIP_ORIGINAL_LABEL : state.models[key]?.label ?? key;
  const card = Object.assign(document.createElement("li"), { className: isOriginal ? "strip-card strip-original" : "strip-card" });
  const link = Object.assign(document.createElement("a"), {
    href: stripImageUrl(job, key), target: "_blank", rel: "noopener", title: STRIP_OPEN_TITLE,
  });
  link.append(Object.assign(document.createElement("img"), { src: stripImageUrl(job, key), alt: label }));
  const caption = key === currentModel ? fillTemplate(STRIP_CURRENT_LABEL, { model: label }) : label;
  card.append(link, Object.assign(document.createElement("div"), { className: "strip-label", textContent: caption }));
  const action = stripAction(job, key, label, currentModel);
  if (action) card.append(action);
  return card;
}

// Follows the file as the page polls: the spot to test, the strip's state, and its images once done
function renderStrip() {
  const job = stripJob();
  if (!job) {
    elements.strip.close();
    return;
  }
  const settings = effectiveSettings(job);
  elements["strip-note"].textContent = fillTemplate(STRIP_NOTE, { scale: formatScale(stripScale(job)) });
  placeStripArea(job);
  elements["strip-status"].textContent = stripStatusText(job);
  elements["strip-run"].disabled = stripPending(job);
  // Rebuilt only when something shown changed, so the images don't reload on every poll
  const shown = [job.strip?.requested, job.strip?.status, job.status, settings.model].join();
  if (shown === state.strip.shown) return;
  state.strip.shown = shown;
  const done = job.strip?.status === "done";
  elements["strip-grid"].replaceChildren(...(done ? job.strip.keys.map((key) => stripCard(job, key, settings.model)) : []));
}

function openStrip(job) {
  state.strip = { jobId: job.id, x: job.strip?.x ?? STRIP_CENTRE, y: job.strip?.y ?? STRIP_CENTRE, shown: null };
  elements["strip-title"].textContent = job.name;
  elements["strip-image"].src = previewUrl(job);
  renderStrip();
  elements.strip.showModal();
}

function pickStripSpot(event) {
  const image = elements["strip-image"];
  state.strip.x = Math.min(1, Math.max(0, event.offsetX / image.clientWidth));
  state.strip.y = Math.min(1, Math.max(0, event.offsetY / image.clientHeight));
  placeStripArea(stripJob());
}

async function runStrip() {
  const job = stripJob();
  try {
    await api.strip(job.id, state.strip.x, state.strip.y, { ...effectiveSettings(job), scale: stripScale(job) });
  } catch (error) {
    toast(fillTemplate(STRIP_NOT_STARTED, { error: error.message }));
  }
  refresh();
}

async function useStripModel(key) {
  const job = stripJob();
  const settings = { ...effectiveSettings(job), model: key };
  if (["done", "error"].includes(job.status)) return rerunJob(job, settings);
  // New settings send a stopped file back to the start, as they do from its Settings
  if (job.status === "stopped" && !confirm(SETTINGS_NOTE_STOPPED)) return;
  try {
    await api.setSettings(job.id, settings);
    toast(fillTemplate(STRIP_USED, { name: job.name, model: state.models[key].label }));
  } catch (error) {
    toast(`Settings not saved: ${error.message}`);
  }
  refresh();
}

async function rerunJob(job, settings) {
  try {
    await api.rerunWith(job.id, settings);
    toast(fillTemplate(RERUN_TOAST, { name: job.name, scale: formatScale(fittedScale(job, settings)), model: modelLabel(settings) }));
  } catch (error) {
    toast(fillTemplate(RERUN_FAILED, { error: error.message }));
  }
  refresh();
}

async function renameJob(job) {
  const name = prompt("New name", job.name);
  if (name === null || name.trim() === job.name) return;
  try {
    await api.rename(job.id, name);
    toast(`Renamed to ${name.trim()}`);
  } catch (error) {
    toast(`Rename failed: ${error.message}`);
  }
  refresh();
}

// The first file of a chain of re-runs; re-runs of a file since removed group under that file's id
function versionRoot(job, jobsById) {
  const seen = new Set();
  let current = job;
  while (jobsById.has(current.source_id) && !seen.has(current.id)) {
    seen.add(current.id);
    current = jobsById.get(current.source_id);
  }
  return current.source_id || current.id;
}

// Other finished versions of the same original, oldest first; only those turned the same way line up in View.
// Re-runs and duplicates share the original's content hash, which holds them together even when a re-run in the
// middle of a chain is removed; the chain of re-runs covers originals that could not be hashed.
function versionsOf(job) {
  const jobsById = new Map(state.jobs.map((candidate) => [candidate.id, candidate]));
  const root = versionRoot(job, jobsById);
  const sameOriginal = (candidate) =>
    Boolean(job.content_hash && candidate.content_hash === job.content_hash) || versionRoot(candidate, jobsById) === root;
  return state.jobs
    .filter((candidate) => candidate.id !== job.id && FILTERS.done(candidate) && candidate.rotation === job.rotation)
    .filter(sameOriginal)
    .sort((first, second) => first.finished - second.finished);
}

const versionLabel = (job) =>
  joinMeta(settingsSummary(job), new Date(job.finished * 1000).toLocaleString(undefined, FINISHED_LABEL_FORMAT));

// The left side shows the original, or the version picked in "Compare with"
function applyCompareSelection() {
  const job = state.comparing;
  const version = state.jobs.find((candidate) => candidate.id === elements["compare-with"].value);
  const labels = version ? [settingsSummary(version), settingsSummary(job)] : [COMPARE_ORIGINAL, COMPARE_UPSCALED];
  elements["compare-before"].src = version ? compareResultUrl(version) : previewUrl(job);
  elements["compare-after"].src = compareResultUrl(job);
  [elements["compare-tag-left"].textContent, elements["compare-tag-right"].textContent] = labels;
  [elements["compare-before"].alt, elements["compare-after"].alt] = labels;
}

function openCompare(job) {
  elements["compare-title"].textContent = `${job.name} — ${formatSize(job.input_size)} → ${formatSize(job.output_size)}`;
  state.comparing = job;
  const versions = versionsOf(job);
  elements["compare-with"].replaceChildren(new Option(COMPARE_ORIGINAL, ""),
    ...versions.map((version) => new Option(versionLabel(version), version.id)));
  elements["compare-with-field"].hidden = !versions.length;
  applyCompareSelection();
  elements["compare-slider"].value = 50;
  setSplit(50);
  elements.compare.showModal();
}

function setSplit(percent) {
  elements["compare-before-wrap"].style.clipPath = `inset(0 ${100 - percent}% 0 0)`;
  elements["compare-line"].style.left = `${percent}%`;
}

function openRotate(job) {
  state.rotating = { job, turns: 0 };
  elements["rotate-title"].textContent = job.name;
  elements["rotate-image"].src = previewUrl(job);
  elements["rotate-note"].textContent = job.status === "done"
    ? "Save turns both the original and the upscaled result."
    : "Save turns the original; the upscale uses the new position.";
  renderRotation();
  elements.rotate.showModal();
}

function renderRotation() {
  elements["rotate-image"].style.transform = `rotate(${state.rotating.turns * QUARTER_TURN_DEGREES}deg)`;
}

async function saveRotation() {
  const { job, turns } = state.rotating;
  const quarterTurns = ((turns % QUARTER_TURNS) + QUARTER_TURNS) % QUARTER_TURNS;
  elements.rotate.close();
  if (quarterTurns === 0) return;
  toast(`Rotating ${job.name}…`);
  try {
    await api.rotate(job.id, quarterTurns);
    toast(`Saved ${job.name} in the new position`);
  } catch (error) {
    toast(`Rotate failed: ${error.message}`);
  }
  refresh();
}

// ---------- wiring ----------

function wireDropzone() {
  const zone = elements.dropzone;
  ["dragenter", "dragover"].forEach((type) => zone.addEventListener(type, (event) => {
    event.preventDefault();
    zone.classList.add("over");
  }));
  ["dragleave", "drop"].forEach((type) => zone.addEventListener(type, () => zone.classList.remove("over")));
  zone.addEventListener("drop", (event) => {
    event.preventDefault();
    uploadFiles(event.dataTransfer.files);
  });
  zone.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") elements["file-input"].click();
  });
  elements["file-input"].addEventListener("change", (event) => {
    uploadFiles(event.target.files);
    event.target.value = "";
  });
  // Dropping outside the zone would otherwise open the image in the tab
  window.addEventListener("dragover", (event) => event.preventDefault());
  window.addEventListener("drop", (event) => event.preventDefault());
  document.addEventListener("paste", (event) => {
    const files = [...event.clipboardData.files];
    if (files.length) uploadFiles(files);
  });
}

function wireSettings() {
  elements["scale-buttons"].addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    elements.scale.value = button.dataset.scale;
    saveSettings();
  });
  [elements.scale, elements.face, elements.format, elements.model, elements["face-pass"], elements["target-value"]]
    .forEach((input) => input.addEventListener("change", saveSettings));
  elements.target.addEventListener("change", () => {
    resetTargetValue(GLOBAL_CONTROLS);
    saveSettings();
  });
  [elements.denoise, elements.quality, elements.fidelity].forEach((input) => input.addEventListener("input", saveSettings));
  elements["defaults-save"].addEventListener("click", saveDefaults);
  elements["defaults-reset"].addEventListener("click", resetToDefaults);
}

function wireFileSettings() {
  [FILE_CONTROLS.model, FILE_CONTROLS.denoise].forEach((input) => {
    input.addEventListener("input", () => renderModelControls(FILE_CONTROLS));
  });
  [FILE_CONTROLS.format, FILE_CONTROLS.quality].forEach((input) => {
    input.addEventListener("input", () => renderFormatControls(FILE_CONTROLS));
  });
  [FILE_CONTROLS.face, FILE_CONTROLS.fidelity].forEach((input) => {
    input.addEventListener("input", () => renderFaceControls(FILE_CONTROLS));
  });
  FILE_CONTROLS.target.addEventListener("change", () => resetTargetValue(FILE_CONTROLS));
  elements["file-settings-save"].addEventListener("click", () => saveFileSettings(false));
  elements["file-settings-global"].addEventListener("click", () => saveFileSettings(true));
  elements["file-settings-cancel"].addEventListener("click", () => elements["file-settings"].close());
}

function wireList() {
  elements.filters.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    state.filter = button.dataset.filter;
    elements.filters.querySelectorAll("button").forEach((other) => other.classList.toggle("active", other === button));
    renderJobs();
  });
  elements.jobs.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    if (!control) return;
    runAction(control.dataset.action, control.closest(".job").dataset.id);
  });
  elements["start-all"].addEventListener("click", async () => {
    try {
      const result = await api.startAll();
      const refused = result.refused.map((item) => `${item.name}: ${item.problems.join(PROBLEM_SEPARATOR)}`);
      // "Started 0" only reads well when nothing was refused either
      const startedText = result.started || !refused.length ? fillTemplate(START_ALL_TOAST, { count: result.started }) : "";
      const refusedText = refused.length ? fillTemplate(START_REFUSED, { list: refused.join(META_SEPARATOR) }) : "";
      toast([startedText, refusedText].filter(Boolean).join(" "));
    } catch (error) {
      toast(`Start failed: ${error.message}`);
    }
    refresh();
  });
  elements["start-new"].addEventListener("click", async () => {
    try {
      await api.clearFinished();
    } catch (error) {
      toast(error.message);
      return;
    }
    location.reload();
  });
}

function wireStrip() {
  elements["strip-image"].addEventListener("click", pickStripSpot);
  elements["strip-run"].addEventListener("click", runStrip);
  elements["strip-close"].addEventListener("click", () => elements.strip.close());
  elements["strip-grid"].addEventListener("click", (event) => {
    const button = event.target.closest("button[data-model]");
    if (button) useStripModel(button.dataset.model);
  });
}

function wireRotate() {
  elements["rotate-left"].addEventListener("click", () => { state.rotating.turns -= 1; renderRotation(); });
  elements["rotate-right"].addEventListener("click", () => { state.rotating.turns += 1; renderRotation(); });
  elements["rotate-cancel"].addEventListener("click", () => elements.rotate.close());
  elements["rotate-save"].addEventListener("click", saveRotation);
}

function wirePages() {
  window.addEventListener("hashchange", () => {
    // Unsaved slider changes are dropped when leaving Settings
    previewThumbnailSize(state.preferences.thumbnail_size);
    renderPage();
    window.scrollTo(0, 0);
  });
  elements.search.addEventListener("input", () => {
    const query = elements.search.value;
    const target = query.trim() ? `${ROUTE_SEARCH_PREFIX}${encodeURIComponent(query)}` : ROUTE_HOME;
    // The first keystroke adds a history entry (Back leaves the search); the rest update it in place
    if (currentRoute().page !== "search") {
      location.hash = target;
      return;
    }
    history.replaceState(null, "", target);
    renderPage();
  });
  [elements["day-grid"], elements["thumb-preview"], elements["search-grid"]].forEach((grid) => grid.addEventListener("click", (event) => {
    const control = event.target.closest("[data-action]");
    const card = event.target.closest(".card[data-id]");
    if (!control || !card) return;
    runAction(control.dataset.action, card.dataset.id);
  }));
  elements["thumb-size"].addEventListener("input", (event) => previewThumbnailSize(event.target.value));
  elements["thumb-reset"].addEventListener("click", () => previewThumbnailSize(state.preferences.limits.default));
  elements["thumb-save"].addEventListener("click", async () => {
    try {
      applyPreferences(await api.savePreferences(elements["thumb-size"].value));
      toast("Thumbnail size saved for every page and device");
    } catch (error) {
      toast(`Save failed: ${error.message}`);
    }
  });
}

function wireCompare() {
  elements["compare-slider"].addEventListener("input", (event) => setSplit(event.target.value));
  elements["compare-close"].addEventListener("click", () => elements.compare.close());
  elements["compare-with"].addEventListener("change", applyCompareSelection);
  elements["compare-zoom"].addEventListener("change", (event) => {
    elements["compare-frame"].classList.toggle("actual", event.target.checked);
    applyCompareSelection();
  });
  elements["compare-frame"].addEventListener("pointermove", (event) => {
    if (!event.buttons) return;
    const box = elements["compare-frame"].getBoundingClientRect();
    const percent = Math.min(100, Math.max(0, ((event.clientX - box.left) / box.width) * 100));
    elements["compare-slider"].value = percent;
    setSplit(percent);
  });
}

async function init() {
  wireDropzone();
  wireSettings();
  wireList();
  wireCompare();
  wireRotate();
  wireStrip();
  wirePages();
  wireFileSettings();
  const [status, preferences] = await Promise.all([api.status(), api.preferences()]);
  // Estimates read the speed table, so rows can render before the first poll
  state.status = status;
  applyPreferences(preferences);
  state.models = Object.fromEntries(status.models.map((model) => [model.key, model]));
  for (const controls of [GLOBAL_CONTROLS, FILE_CONTROLS]) {
    Object.assign(controls.scale, { min: status.limits.min_scale, max: status.limits.max_scale });
    controls.format.replaceChildren(...status.formats.map((format) => new Option(format.toUpperCase(), format)));
    controls.model.replaceChildren(...status.models.map((model) => new Option(model.label, model.key)));
    Object.assign(controls.denoise, { min: status.limits.min_denoise, max: status.limits.max_denoise });
    Object.assign(controls.quality, { min: status.limits.min_quality, max: status.limits.max_quality });
    Object.assign(controls.fidelity, { min: status.limits.min_face_fidelity, max: status.limits.max_face_fidelity });
    controls.target.querySelector(`[value="${TARGET_MODE_PRINT}"]`).textContent = fillTemplate(TARGET_PRINT_OPTION, { dpi: status.print_dpi });
  }
  elements["file-input"].accept = status.extensions.join(",");
  elements.accepted.textContent = status.extensions.join(" ");
  loadSettings(status.defaults);
  refresh();
}

init();
