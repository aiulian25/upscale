import re
import shutil
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.datastructures import Headers

import config
import custom_models
import preferences
from cross_site import is_cross_site
from inbox import InboxWatcher
from jobs import JobStore, available_ram_bytes, fitted_settings, output_name, validate_settings

for directory in (config.INPUT_DIR, config.OUTPUT_DIR, config.PREVIEW_DIR, config.CHECKPOINT_DIR,
                  config.CUSTOM_MODELS_DIR):
    directory.mkdir(parents=True, exist_ok=True)

# Job ids are never reused, so their previews can be cached forever
IMMUTABLE = {"Cache-Control": "max-age=31536000, immutable"}
# The page, script and stylesheet: browsers check for a newer copy on every load (a cheap 304 when unchanged)
REVALIDATE = {"Cache-Control": "no-cache"}

store = JobStore(config.JOBS_FILE, config.INPUT_DIR, config.OUTPUT_DIR, config.PREVIEW_DIR, config.CHECKPOINT_DIR)


def start_background_threads():
    from upscaler import Upscaler
    # Before the worker starts, so every job and test strip sees the same list
    custom_models.scan()
    if custom_models.found:
        print(config.CUSTOM_MODELS_FOUND_LOG.format(names=", ".join(custom_models.found)), flush=True)
    for name, reason in custom_models.skipped.items():
        print(config.CUSTOM_MODEL_SKIPPED_LOG.format(file=name, reason=reason), flush=True)
    store.start_worker(Upscaler)
    # The shared defaults are read again for each file, so a change made on the page applies to the next one
    InboxWatcher(store, lambda: preferences.load()["defaults"]).start()


@asynccontextmanager
async def lifespan(application):
    start_background_threads()
    yield


app = FastAPI(title="Upscale", lifespan=lifespan)


class RefuseCrossSiteRequests:
    """Answers 403 to a request another site's page made the browser send, before any route sees it.

    Plain ASGI rather than @app.middleware, which would pass every download through an extra buffer.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http" and is_cross_site(scope["method"], scope["path"], Headers(scope=scope)):
            response = JSONResponse({"detail": config.ERROR_CROSS_SITE}, status_code=config.CROSS_SITE_STATUS)
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


app.add_middleware(RefuseCrossSiteRequests)


def settings_or_400(*values):
    try:
        return validate_settings(*values)
    except ValueError as error:
        raise HTTPException(400, str(error))


def settings_form(scale: float = Form(...), face_enhance: bool = Form(...), output_format: str = Form(...),
                  model: str = Form(config.DEFAULT_MODEL), denoise: float = Form(config.DEFAULT_DENOISE),
                  quality: int = Form(config.DEFAULT_QUALITY),
                  face_fidelity: float = Form(config.DEFAULT_FACE_FIDELITY),
                  face_pass: str = Form(config.DEFAULT_FACE_PASS),
                  target_mode: str = Form(config.DEFAULT_TARGET_MODE), target_long_edge: int = Form(0)):
    """The settings a file's form sends, validated; a bad one answers 400 and says which."""
    return settings_or_400(scale, face_enhance, output_format, model, denoise, quality, face_fidelity, face_pass,
                           target_mode, target_long_edge)


def mebibytes(size):
    return None if size is None else round(size / config.MEBIBYTE, 1)


def job_or_404(job_id):
    job = store.get(job_id)
    if job is None:
        raise HTTPException(404, config.ERROR_NO_SUCH_JOB)
    return job


@app.get("/api/status")
def status():
    from upscaler import DEVICE, device_name, gpu_memory
    vram_used, vram_total = gpu_memory()
    return {"device": device_name(), "ready": store.engine_ready, "error": store.engine_problem(),
            "defaults": preferences.load()["defaults"],
            "speed": store.speed_table(DEVICE),
            "limits": {"min_scale": config.MIN_SCALE, "max_scale": config.MAX_SCALE,
                       "min_denoise": config.MIN_DENOISE, "max_denoise": config.MAX_DENOISE,
                       "min_quality": config.MIN_QUALITY, "max_quality": config.MAX_QUALITY,
                       "min_face_fidelity": config.MIN_FACE_FIDELITY, "max_face_fidelity": config.MAX_FACE_FIDELITY,
                       "min_target_long_edge": config.MIN_TARGET_LONG_EDGE,
                       "max_target_long_edge": config.MAX_TARGET_LONG_EDGE},
            "print_dpi": config.PRINT_DPI,
            "models": [{"key": key, "label": model["label"], "hint": model["hint"],
                        "has_denoise": len(model["urls"]) > 1, "custom": key in custom_models.found}
                       for key, model in custom_models.all_models().items()],
            "custom_models_skipped": [{"file": name, "reason": reason}
                                      for name, reason in custom_models.skipped.items()],
            "formats": list(config.OUTPUT_FORMATS),
            "strip_output_edge": config.STRIP_OUTPUT_EDGE,
            "zip_max_files": config.ZIP_MAX_FILES,
            "extensions": sorted(config.ALLOWED_INPUT_EXTENSIONS),
            "system": {"tile": config.TILE, "tile_pad": config.TILE_PAD,
                       "vram_used_mb": mebibytes(vram_used), "vram_total_mb": mebibytes(vram_total),
                       "ram_available_mb": mebibytes(available_ram_bytes()),
                       "disk_free_mb": mebibytes(shutil.disk_usage(config.DATA_DIR).free),
                       "library_mb": mebibytes(store.library_bytes()), "jobs": len(store.jobs)}}


@app.get("/api/jobs")
def list_jobs():
    return store.all_jobs()


@app.post("/api/jobs")
def create_jobs(files: list[UploadFile] = File(...), settings: dict = Depends(settings_form)):
    created, rejected = [], []
    for upload in files:
        name = Path(upload.filename or "image").name
        if Path(name).suffix.lower() not in config.ALLOWED_INPUT_EXTENSIONS:
            rejected.append({"name": name, "error": "Unsupported file type"})
            continue

        def write_input(path, upload=upload):
            with path.open("wb") as target:
                shutil.copyfileobj(upload.file, target)

        try:
            created.append(store.add(name, settings, write_input=write_input))
        except ValueError as error:
            rejected.append({"name": name, "error": str(error)})
    return {"created": created, "rejected": rejected}


@app.post("/api/jobs/{job_id}/rerun")
def rerun_job(job_id: str, settings: dict = Depends(settings_form)):
    source = job_or_404(job_id)
    settings = fitted_settings(source["input_size"], settings)
    problems = store.preflight(source, settings)
    if problems:
        raise HTTPException(409, config.PROBLEM_SEPARATOR.join(problems))
    return store.add(source["name"], settings, source_job=source, start=True)


@app.post("/api/jobs/start")
def start_all_jobs(settings: dict = Depends(settings_form)):
    started, refused = store.start(store.ready_ids(), settings)
    # "started" stays a count, as before; "refused" lists what stayed Ready and why
    return {"started": len(started), "refused": refused}


@app.post("/api/jobs/{job_id}/start")
def start_job(job_id: str, settings: dict = Depends(settings_form)):
    job_or_404(job_id)
    started, refused = store.start([job_id], settings)
    if refused:
        raise HTTPException(409, config.PROBLEM_SEPARATOR.join(refused[0]["problems"]))
    if not started:
        raise HTTPException(409, config.ERROR_CANNOT_START)
    return store.get(job_id)


@app.put("/api/jobs/{job_id}/settings")
def set_job_settings(job_id: str, settings: dict = Depends(settings_form)):
    job_or_404(job_id)
    job = store.set_settings(job_id, settings)
    if job is None:
        raise HTTPException(409, config.ERROR_SETTINGS_LOCKED)
    return job


@app.delete("/api/jobs/{job_id}/settings")
def use_global_settings(job_id: str):
    job_or_404(job_id)
    job = store.set_settings(job_id, None)
    if job is None:
        raise HTTPException(409, config.ERROR_SETTINGS_LOCKED)
    return job


@app.post("/api/jobs/{job_id}/rename")
def rename_job(job_id: str, name: str = Form(...)):
    job_or_404(job_id)
    try:
        return store.rename(job_id, name)
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job_or_404(job_id)
    if not store.delete(job_id):
        raise HTTPException(409, config.ERROR_PROCESSING)
    return {"deleted": 1}


@app.post("/api/jobs/{job_id}/stop")
def stop_job(job_id: str):
    job_or_404(job_id)
    if not store.stop(job_id):
        raise HTTPException(409, config.ERROR_CANNOT_STOP)
    return store.get(job_id)


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    job_or_404(job_id)
    if not store.resume(job_id):
        raise HTTPException(409, config.ERROR_CANNOT_RESUME)
    return store.get(job_id)


@app.post("/api/jobs/{job_id}/rotate")
def rotate_job(job_id: str, turns: int = Form(...)):
    job_or_404(job_id)
    job = store.rotate(job_id, turns)
    if job is None:
        raise HTTPException(409, config.ERROR_SETTINGS_LOCKED)
    return job


@app.post("/api/jobs/{job_id}/strip")
def request_test_strip(job_id: str, x: float = Form(...), y: float = Form(...), scale: float = Form(...),
                       denoise: float = Form(config.DEFAULT_DENOISE)):
    job_or_404(job_id)
    try:
        job = store.request_strip(job_id, x, y, scale, denoise)
    except ValueError as error:
        raise HTTPException(400, str(error))
    if job is None:
        raise HTTPException(404, config.ERROR_NO_SUCH_JOB)
    return job


@app.post("/api/jobs/clear")
def clear_finished_jobs():
    return {"cleared": store.clear_finished()}


@app.get("/api/preferences")
def get_preferences():
    return preferences.load()


@app.put("/api/preferences")
def put_preferences(thumbnail_size: int | None = Form(None), scale: float | None = Form(None),
                    face_enhance: bool | None = Form(None), output_format: str | None = Form(None),
                    model: str = Form(config.DEFAULT_MODEL), denoise: float = Form(config.DEFAULT_DENOISE),
                    quality: int = Form(config.DEFAULT_QUALITY),
                    face_fidelity: float = Form(config.DEFAULT_FACE_FIDELITY),
                    face_pass: str = Form(config.DEFAULT_FACE_PASS),
                    target_mode: str = Form(config.DEFAULT_TARGET_MODE), target_long_edge: int = Form(0)):
    # The shared defaults are only ever saved as a complete set
    sent_settings = (scale, face_enhance, output_format)
    saves_defaults = any(value is not None for value in sent_settings)
    if saves_defaults and None in sent_settings:
        raise HTTPException(400, preferences.ERROR_INCOMPLETE_DEFAULTS)
    defaults = (settings_or_400(scale, face_enhance, output_format, model, denoise, quality, face_fidelity, face_pass,
                                target_mode, target_long_edge)
                if saves_defaults else None)
    try:
        return preferences.save(thumbnail_size, defaults)
    except ValueError as error:
        raise HTTPException(400, str(error))


@app.get("/files/preview/{job_id}")
def preview_file(job_id: str):
    return FileResponse(store.preview_path(job_or_404(job_id)), headers=IMMUTABLE)


@app.get("/files/output/{job_id}")
def output_file(job_id: str, download: bool = False):
    job = job_or_404(job_id)
    if job["status"] != config.STATUS_DONE:
        raise HTTPException(404, config.ERROR_NOT_FINISHED)
    disposition = "attachment" if download else "inline"
    return FileResponse(store.output_path(job), filename=output_name(job),
                        content_disposition_type=disposition)


@app.get("/files/result-preview/{job_id}")
def result_preview_file(job_id: str):
    job = job_or_404(job_id)
    if job["status"] != config.STATUS_DONE:
        raise HTTPException(404, config.ERROR_NOT_FINISHED)
    try:
        path = store.result_preview(job)
    except OSError as error:
        raise HTTPException(404, str(error))
    return FileResponse(path, headers=IMMUTABLE)


@app.get("/files/strip/{job_id}/{key}")
def strip_image(job_id: str, key: str):
    """One image of the last test strip; only keys it wrote are served, so no other path can be named."""
    job = job_or_404(job_id)
    if key not in (job["strip"] or {}).get("keys", []):
        raise HTTPException(404, config.ERROR_NO_SUCH_STRIP_IMAGE)
    return FileResponse(store.strip_path(job_id, key), headers=IMMUTABLE)


@app.get(config.ALL_OUTPUTS_ZIP_PATH)
def outputs_zip(ids: str | None = None, label: str = config.ZIP_LABEL_ALL):
    """The finished files on the queue list, or those listed in ids (a day page or a search), as one zip."""
    if not re.fullmatch(config.ZIP_LABEL_PATTERN, label):
        raise HTTPException(400, config.ERROR_BAD_ZIP_LABEL)
    listed = None if ids is None else [job_id for job_id in ids.split(config.ZIP_ID_SEPARATOR) if job_id]
    if listed is not None and len(listed) > config.ZIP_MAX_FILES:
        raise HTTPException(400, config.ERROR_TOO_MANY_FOR_ZIP.format(max=config.ZIP_MAX_FILES))
    finished = store.finished_jobs(None if listed is None else set(listed))
    if not finished:
        raise HTTPException(404, config.ERROR_NOTHING_TO_ZIP)
    disposition = config.ZIP_DISPOSITION.format(name=config.ZIP_NAME_FORMAT.format(label=label))
    return StreamingResponse(store.outputs_zip(finished), media_type=config.ZIP_MEDIA_TYPE,
                             headers={"Content-Disposition": disposition})


@app.get("/health")
def health():
    """Docker's health check: failing while nothing can run makes `docker ps` show the container unhealthy."""
    problem = store.engine_problem()
    if problem:
        raise HTTPException(config.HEALTH_ERROR_STATUS, problem)
    return {"ok": True, "ready": store.engine_ready}


class RevalidatedStaticFiles(StaticFiles):
    """Without this, browsers keep an old app.js or style.css for hours after a deploy and pair it with new HTML."""

    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers.update(REVALIDATE)
        return response


app.mount("/", RevalidatedStaticFiles(directory=config.STATIC_DIR, html=True), name="static")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=config.PORT)
