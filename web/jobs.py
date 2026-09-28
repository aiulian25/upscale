"""Persistent job list plus a single worker thread that runs the upscaler."""
import io
import json
import os
import queue
import re
import shutil
import statistics
import string
import threading
import time
import traceback
import uuid
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

import config
from custom_models import UnusableModelError, all_models
from heif import heif_to_png
from images import (QUARTER_TURNS, content_hash, eight_bit_grey, exif_transform, read_image, read_metadata,
                    read_photo_info, rotate_file, write_result_preview)

# Also fills fields that jobs saved by older versions don't have
JOB_DEFAULTS = {"rotation": 0, "mirrored": False, "elapsed": 0.0, "progress": 0.0, "stage": None, "stop_requested": False,
                "model": config.DEFAULT_MODEL, "denoise": config.DEFAULT_DENOISE, "quality": config.DEFAULT_QUALITY,
                "face_fidelity": config.DEFAULT_FACE_FIDELITY, "face_pass": config.DEFAULT_FACE_PASS, "cleared": False,
                # Fit to: a long edge the scale is worked out from at Start; 0 while the scale is set directly
                "target_mode": config.DEFAULT_TARGET_MODE, "target_long_edge": 0,
                # Faces a finished run restored; None with face restore off, or for runs from before they were counted
                "faces_found": None,
                # False: the file follows the global settings until it starts
                "custom_settings": False,
                # Re-runs: the job they were re-run from, kept even after that job is removed
                "source_id": None,
                # Tile size of the current or last run: the configured TILE, halved on each out-of-memory retry
                "tile": None,
                # "gpu" or "cpu", for the time estimates; None for runs from before it was recorded
                "device": None,
                # The last test strip asked for: its spot, scale and status, and the images it made; None before any
                "strip": None,
                # SHA-256 of the original: an upload with the same bytes is the same photo
                "content_hash": None,
                # The job an upload turned out to be the same photo as; its original is then a hardlink to that one's
                "duplicate_of": None}
# Once a file is waiting in line or running, its settings and orientation are fixed
LOCKED_STATUSES = (config.STATUS_QUEUED, config.STATUS_PROCESSING)
# Queued next to the job ids so an idle worker wakes up for a test strip; no job has this id
STRIP_WAKE_UP = None


def check_name_template(template):
    """Refuses a download-name template that could make more than one plain file name.

    Only bare placeholders from OUTPUT_NAME_FIELDS are allowed: no attribute or index lookups (which could put the
    app's internals into a name), no format specs, and no path separators.
    """
    try:
        parts = list(string.Formatter().parse(template))
    except ValueError:
        parts = None
    plain = parts is not None and all(field in config.OUTPUT_NAME_FIELDS and not spec and not conversion
                                      for _, field, spec, conversion in parts if field is not None)
    has_separator = any(character in template for character in config.FORBIDDEN_NAME_CHARACTERS)
    if not plain or has_separator or not template.strip():
        placeholders = " ".join(f"{{{field}}}" for field in config.OUTPUT_NAME_FIELDS)
        raise ValueError(config.ERROR_BAD_NAME_TEMPLATE.format(template=template, fields=placeholders))


# Checked once at start-up: a bad OUTPUT_NAME_TEMPLATE in the compose file stops the app with a clear message
check_name_template(config.OUTPUT_NAME_TEMPLATE)


def safe_file_name(name):
    """One plain file name wherever it is saved or unzipped: path separators and control characters are replaced.

    Uploaded names are not checked, and a backslash is no separator on Linux but is one to some Windows unzippers.
    """
    return "".join(character if character.isprintable() and character not in config.FORBIDDEN_NAME_CHARACTERS
                   else config.FILE_NAME_REPLACEMENT for character in name)


def output_name(job):
    """Download name: OUTPUT_NAME_TEMPLATE filled from the job as one plain file name, plus the format's extension.

    {name} is the (possibly renamed) name without its image extension.
    """
    path = Path(job["name"])
    stem = path.stem if path.suffix.lower() in config.ALLOWED_INPUT_EXTENSIONS else path.name
    scale = config.SCALE_TOKEN_FORMAT.format(scale=round(job["scale"], config.SCALE_TOKEN_DECIMALS))
    faces = config.FACES_TOKEN_ON if job["face_enhance"] else config.FACES_TOKEN_OFF
    finished = time.strftime(config.DATE_TOKEN_FORMAT, time.gmtime(job["finished"] or job["created"]))
    name = config.OUTPUT_NAME_TEMPLATE.format(name=stem, scale=scale, model=job["model"], faces=faces, date=finished)
    return safe_file_name(name) + config.OUTPUT_FORMATS[job["format"]]


def validate_name(name):
    name = name.strip()
    has_forbidden = any(character in name for character in config.FORBIDDEN_NAME_CHARACTERS)
    if not name or has_forbidden or len(name) > config.NAME_MAX_LENGTH or not name.isprintable():
        raise ValueError(config.ERROR_BAD_NAME.format(max_length=config.NAME_MAX_LENGTH))
    return name


def validate_settings(scale, face_enhance, output_format, model=config.DEFAULT_MODEL, denoise=config.DEFAULT_DENOISE,
                      quality=config.DEFAULT_QUALITY, face_fidelity=config.DEFAULT_FACE_FIDELITY,
                      face_pass=config.DEFAULT_FACE_PASS, target_mode=config.DEFAULT_TARGET_MODE, target_long_edge=0):
    if not config.MIN_SCALE <= scale <= config.MAX_SCALE:
        raise ValueError(f"Scale must be between {config.MIN_SCALE:g} and {config.MAX_SCALE:g}")
    if output_format not in config.OUTPUT_FORMATS:
        raise ValueError(f"Format must be one of {', '.join(config.OUTPUT_FORMATS)}")
    models = all_models()
    if model not in models:
        raise ValueError(f"Model must be one of {', '.join(models)}")
    if not config.MIN_DENOISE <= denoise <= config.MAX_DENOISE:
        raise ValueError(f"Denoise must be between {config.MIN_DENOISE:g} and {config.MAX_DENOISE:g}")
    # Whole numbers only: Pillow's JPEG encoder rejects fractions
    if not isinstance(quality, int) or not config.MIN_QUALITY <= quality <= config.MAX_QUALITY:
        raise ValueError(f"Quality must be a whole number between {config.MIN_QUALITY} and {config.MAX_QUALITY}")
    if not config.MIN_FACE_FIDELITY <= face_fidelity <= config.MAX_FACE_FIDELITY:
        raise ValueError(f"Face fidelity must be between {config.MIN_FACE_FIDELITY:g} and {config.MAX_FACE_FIDELITY:g}")
    if face_pass not in config.FACE_PASSES:
        raise ValueError(f"Face pass must be one of {', '.join(config.FACE_PASSES)}")
    if target_mode not in config.TARGET_MODES:
        raise ValueError(f"Fit to must be one of {', '.join(config.TARGET_MODES)}")
    fits_to_edge = target_mode != config.TARGET_MODE_SCALE
    edge_in_range = (isinstance(target_long_edge, int)
                     and config.MIN_TARGET_LONG_EDGE <= target_long_edge <= config.MAX_TARGET_LONG_EDGE)
    if fits_to_edge and not edge_in_range:
        raise ValueError(f"The long edge must be a whole number of pixels between {config.MIN_TARGET_LONG_EDGE} "
                         f"and {config.MAX_TARGET_LONG_EDGE}")
    return {"scale": scale, "face_enhance": bool(face_enhance), "format": output_format, "model": model,
            "denoise": denoise, "quality": quality, "face_fidelity": face_fidelity, "face_pass": face_pass,
            "target_mode": target_mode, "target_long_edge": target_long_edge if fits_to_edge else 0}


def fitted_settings(input_size, settings):
    """The settings a file runs with: a target long edge becomes the scale that brings this file's long edge there.

    The scale is capped at MAX_SCALE; below MIN_SCALE the file is already big enough, which the pre-flight refuses.
    """
    if settings["target_mode"] == config.TARGET_MODE_SCALE:
        return settings
    return {**settings, "scale": min(settings["target_long_edge"] / max(input_size), config.MAX_SCALE)}


def print_dpi(job):
    """The DPI a print target writes into the result; None otherwise."""
    return config.PRINT_DPI if job["target_mode"] == config.TARGET_MODE_PRINT else None


def _meminfo_available_bytes():
    """RAM the kernel can hand out without swapping; None where /proc/meminfo is missing."""
    try:
        lines = Path(config.MEMINFO_PATH).read_text().splitlines()
    except OSError:
        return None
    values = [line.split()[1] for line in lines if line.startswith(config.MEMINFO_AVAILABLE_KEY)]
    return int(values[0]) * config.KIBIBYTE if values else None


def _cgroup_headroom_bytes():
    """What is left under the container's memory limit; None when it has none (the default)."""
    try:
        limit = Path(config.CGROUP_MEMORY_MAX_PATH).read_text().strip()
        current = int(Path(config.CGROUP_MEMORY_CURRENT_PATH).read_text())
    except (OSError, ValueError):
        return None
    return None if limit == config.CGROUP_NO_LIMIT else int(limit) - current


def available_ram_bytes():
    """RAM a job can still use: MemAvailable, capped by the container's own memory limit when it has one."""
    known = [value for value in (_meminfo_available_bytes(), _cgroup_headroom_bytes()) if value is not None]
    return min(known) if known else None


def free_disk_bytes(path):
    return shutil.disk_usage(path).free


def result_size(input_size, scale):
    """The result's width and height, truncated the way the upscaler sizes it."""
    return int(input_size[0] * scale), int(input_size[1] * scale)


def work_megapixels(input_size, scale):
    """Megapixels the model produces for a result: one pass at its scale, plus a second on the enlarged image past it.

    Below 4× the model still does a full 4× pass and shrinks the result, so time follows this, not the result size.
    """
    passes = config.MODEL_SCALE ** 2 + (scale ** 2 if scale > config.MODEL_SCALE else 0)
    return input_size[0] * input_size[1] * passes / config.PIXELS_PER_MEGAPIXEL


def gigabytes(size):
    return f"{size / config.GIBIBYTE:.1f}"


def disk_needed(input_size, settings):
    width, height = result_size(input_size, settings["scale"])
    return width * height * config.DISK_BYTES_PER_OUTPUT_PIXEL[settings["format"]]


def preflight_problems(name, input_size, settings, output_dir, disk_claimed=0):
    """Why a file would fail with these fitted settings, empty when it can run.

    disk_claimed is what results already waiting to be written will take from the same disk.
    """
    # A file's own settings can name a custom model taken out of data/models since
    if settings["model"] not in all_models():
        return [config.ERROR_UNUSABLE_MODEL.format(model=settings["model"], reason=config.MODEL_GONE)]
    if settings["scale"] < config.MIN_SCALE:
        return [config.ERROR_ALREADY_BIG_ENOUGH.format(name=name, edge=max(input_size),
                                                       target=settings["target_long_edge"])]
    width, height = result_size(input_size, settings["scale"])
    problems = []
    edge_limit = config.MAX_EDGE_BY_FORMAT.get(settings["format"])
    if edge_limit and max(width, height) > edge_limit:
        problems.append(config.ERROR_TOO_WIDE_FOR_FORMAT.format(
            width=width, height=height, format=settings["format"].upper(), limit=edge_limit))
    faces = settings["face_enhance"]
    per_pixel = config.RAM_BYTES_PER_OUTPUT_PIXEL_WITH_FACES if faces else config.RAM_BYTES_PER_OUTPUT_PIXEL
    ram_needed, ram_free = width * height * per_pixel, available_ram_bytes()
    advice = config.ADVICE_SMALLER_SCALE_OR_NO_FACES if faces else config.ADVICE_SMALLER_SCALE
    if ram_free is not None and ram_needed > ram_free:
        problems.append(config.ERROR_NOT_ENOUGH_RAM.format(
            needed=gigabytes(ram_needed), width=width, height=height, available=gigabytes(ram_free), advice=advice))
    needed, free = disk_claimed + disk_needed(input_size, settings), free_disk_bytes(output_dir)
    if needed > free:
        problems.append(config.ERROR_NOT_ENOUGH_DISK.format(needed=gigabytes(needed), free=gigabytes(free)))
    return problems


def tile_progress(span_start, span_end, next_tile, total):
    """Share of the whole run done after next_tile tiles of a model pass covering span_start to span_end."""
    return (span_start + (span_end - span_start) * next_tile / total) * config.TILES_PROGRESS_SHARE


def too_many_pixels(name, error):
    """Pillow's decompression-bomb refusal, told with the image's real size."""
    match = re.search(config.DECOMPRESSION_BOMB_PIXELS_PATTERN, str(error))
    megapixels = round(int(match.group(1)) / config.PIXELS_PER_MEGAPIXEL) if match else "?"
    return config.ERROR_TOO_MANY_PIXELS.format(name=name, megapixels=megapixels, limit=config.MAX_INPUT_MEGAPIXELS)


def _file_stat(path):
    """None for a file removed between listing its folder and reading it."""
    try:
        return path.stat()
    except FileNotFoundError:
        return None


def _hash_or_none(path):
    """The file's content hash, or None when it can't be read (an original removed by hand, for one)."""
    try:
        return content_hash(path)
    except OSError:
        return None


def is_gpu_out_of_memory(error):
    return "out of memory" in str(error).lower() and not isinstance(error, MemoryError)


def smaller_tile(tile):
    """The tile size to retry with after running out of GPU memory, or None once it would drop below MIN_TILE."""
    smaller = tile // config.TILE_RETRY_DIVISOR
    return smaller if smaller >= config.MIN_TILE else None


def strip_pending(job):
    return (job["strip"] or {}).get("status") == config.STRIP_STATUS_PENDING


def describe_error(error, tile=config.TILE):
    message = str(error) or type(error).__name__
    if isinstance(error, MemoryError):
        return config.ERROR_OUT_OF_RAM
    if is_gpu_out_of_memory(error):
        return config.ERROR_OUT_OF_GPU_MEMORY.format(tile=tile)
    return message


class ZipBuffer(io.RawIOBase):
    """Collects what zipfile writes, so a zip can be sent while it is made instead of from a file on disk.

    It can't seek, so zipfile writes each entry's sizes after its data.
    """

    def __init__(self):
        super().__init__()
        self.pending = bytearray()

    def writable(self):
        return True

    def write(self, data):
        self.pending += data
        return len(data)

    def take(self):
        data, self.pending = bytes(self.pending), bytearray()
        return data


class JobStopped(Exception):
    def __init__(self, checkpoint):
        super().__init__("stopped")
        self.checkpoint = checkpoint


class JobProgress:
    """Handed to the upscaler for one run: reports progress, stops between tiles, resumes from a checkpoint."""

    def __init__(self, store, job, checkpoint, upscaler):
        self.store = store
        self.job = job
        self.checkpoint = checkpoint
        self.upscaler = upscaler
        # After an out-of-memory retry the row says so for the whole run, not just while it restarts
        tile = job["tile"]
        self.upscaling_stage = config.STAGE_UPSCALING if tile == config.TILE else config.STAGE_RETRYING.format(tile=tile)

    span_start, span_end = 0.0, 1.0

    def span(self, start, end):
        """Share of the tile progress the next model pass covers (results past 4× take two passes)."""
        self.span_start, self.span_end = start, end

    def stage(self, name):
        progress = config.TILES_PROGRESS_SHARE if name == config.STAGE_SAVING else self.job["progress"]
        self.store.report(self.job, stage=name, progress=progress)

    def resume(self, output_shape):
        if self.checkpoint is None or tuple(self.checkpoint["output"].shape) != tuple(output_shape):
            return None
        return self.checkpoint["next_tile"], self.checkpoint["output"]

    def tile(self, next_tile, total, output):
        if self.job["stop_requested"]:
            raise JobStopped({"next_tile": next_tile, "output": output})
        # A test strip asked for meanwhile runs here, between two tiles, instead of after the whole job
        self.store.run_strips(self.upscaler)
        self.store.report(self.job, stage=self.upscaling_stage,
                          progress=tile_progress(self.span_start, self.span_end, next_tile, total))


class JobStore:
    def __init__(self, jobs_file, input_dir, output_dir, preview_dir, checkpoint_dir):
        self.jobs_file = jobs_file
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.preview_dir = preview_dir
        self.checkpoint_dir = checkpoint_dir
        self.lock = threading.Lock()
        self.pending = queue.Queue()
        self.strips = queue.Queue()
        self.engine_ready = False
        self.engine_error = None
        self.worker = None
        self.jobs = self._load()
        self._add_missing_photo_info()
        self._add_missing_hashes()
        # A stopped job keeps its place only while its partial result is on disk
        for job in self.jobs.values():
            if job["status"] == config.STATUS_STOPPED and not self.checkpoint_path(job["id"]).exists():
                job.update(progress=0.0, stage=None)
        interrupted = [job for job in self.jobs.values()
                       if job["status"] in (config.STATUS_QUEUED, config.STATUS_PROCESSING)]
        for job in sorted(interrupted, key=lambda job: job["created"]):
            job.update(status=config.STATUS_QUEUED, progress=0.0, stage=None, stop_requested=False)
            self.pending.put(job["id"])
        # Test strips asked for before a restart still run
        for job in self.jobs.values():
            if strip_pending(job):
                self._queue_strip(job["id"])
        self._remove_orphan_files()

    def _load(self):
        if not self.jobs_file.exists():
            return {}
        jobs = [{**JOB_DEFAULTS, **job} for job in json.loads(self.jobs_file.read_text())]
        for job in jobs:
            # Older jobs took the extension from the name, which renaming can now change
            job.setdefault("input_ext", Path(job["name"]).suffix.lower())
            # Jobs from before the source was recorded: a re-run is the one with a source_id
            job.setdefault("source", config.SOURCE_RERUN if job["source_id"] else config.SOURCE_UPLOAD)
        return {job["id"]: job for job in jobs}

    def _add_missing_photo_info(self):
        """Jobs saved before the date taken and camera were recorded read them from their original, once.

        The two keys are deliberately not in JOB_DEFAULTS: a missing key is what marks a job for this.
        """
        # ponytail: blocks start-up once, and Pillow fully decodes PNG originals to look for EXIF;
        # move this to the worker thread if a large PNG library makes that first start slow.
        missing = [job for job in self.jobs.values() if "taken" not in job]
        for job in missing:
            job.update(read_photo_info(self.input_path(job)))
        if missing:
            self._save()

    def _add_missing_hashes(self):
        """Jobs saved before content hashes existed get one from their original, once."""
        # ponytail: blocks the first start after the upgrade, reading every original once; move this to the worker
        # thread if a large library makes that start slow.
        missing = [job for job in self.jobs.values() if job["content_hash"] is None]
        for job in missing:
            job["content_hash"] = _hash_or_none(self.input_path(job))
        if any(job["content_hash"] for job in missing):
            self._save()

    def _save(self):
        temporary = self.jobs_file.with_suffix(".tmp")
        temporary.write_text(json.dumps(list(self.jobs.values()), indent=1))
        temporary.replace(self.jobs_file)

    def _remove_orphan_files(self):
        """Deletes any file no job owns (e.g. left by a crash mid-delete), so nothing piles up."""
        for folder in (self.input_dir, self.output_dir, self.preview_dir, self.checkpoint_dir):
            for path in folder.iterdir():
                if path.stem.split(config.JOB_FILE_SEPARATOR, 1)[0] not in self.jobs:
                    path.unlink(missing_ok=True)

    def input_path(self, job):
        return self.input_dir / f"{job['id']}{job['input_ext']}"

    def preview_path(self, job):
        return self.preview_dir / f"{job['id']}.jpg"

    def result_preview_path(self, job):
        return self.preview_dir / f"{job['id']}{config.RESULT_PREVIEW_SUFFIX}.jpg"

    def result_preview(self, job):
        """The result's light JPEG; files finished before previews existed get theirs made on first request."""
        path = self.result_preview_path(job)
        if not path.exists():
            write_result_preview(path, read_image(self.output_path(job)), read_metadata(self.input_path(job)))
        return path

    def output_path(self, job):
        return self.output_dir / f"{job['id']}{config.OUTPUT_FORMATS[job['format']]}"

    def all_jobs(self):
        """Every job, newest first; queued ones carry queue_position, 1 being the next to run."""
        with self.pending.mutex:
            waiting = list(self.pending.queue)
        with self.lock:
            jobs = [dict(job) for job in self.jobs.values()]
        queued = {job["id"] for job in jobs if job["status"] == config.STATUS_QUEUED}
        # The worker takes each job at its first live entry, so a file stopped and resumed while waiting keeps its place
        positions = {job_id: place for place, job_id in enumerate(dict.fromkeys(
            job_id for job_id in waiting if job_id in queued), start=1)}
        for job in jobs:
            job["queue_position"] = positions.get(job["id"])
        return sorted(jobs, key=lambda job: job["created"], reverse=True)

    def finished_jobs(self, job_ids=None):
        """Finished jobs, newest first: the ones with these ids, skipping unknown or unfinished ones, or else those
        still on the queue list (Start new clears the others off it, but their day pages still list them)."""
        with self.lock:
            finished = [dict(job) for job in self.jobs.values() if job["status"] == config.STATUS_DONE]
        if job_ids is None:
            finished = [job for job in finished if not job["cleared"]]
        else:
            finished = [job for job in finished if job["id"] in job_ids]
        return sorted(finished, key=lambda job: job["created"], reverse=True)

    def outputs_zip(self, jobs):
        """The jobs' results as one zip, yielded as it is made: nothing waits on disk and the download starts at once.

        Stored rather than compressed: results are compressed images already. A download name used twice gets the
        start of the job id.
        """
        buffer, used_names = ZipBuffer(), set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as bundle:
            for job in jobs:
                path, name = self.output_path(job), output_name(job)
                if name in used_names:
                    name = config.ZIP_CLASH_NAME.format(stem=Path(name).stem, suffix=Path(name).suffix,
                                                        id=job["id"][:config.ZIP_ID_SUFFIX_LENGTH])
                used_names.add(name)
                with path.open("rb") as source, bundle.open(zipfile.ZipInfo.from_file(path, name), "w") as target:
                    for chunk in iter(lambda: source.read(config.ZIP_CHUNK_BYTES), b""):
                        target.write(chunk)
                        yield buffer.take()
        yield buffer.take()

    def speed_table(self, device):
        """Median seconds per work megapixel of past runs on this device, for each model and face setting.

        Runs from before devices were recorded count as this device's. A setting needs ESTIMATE_MIN_SAMPLES runs
        of its own; "default" is the median of every run, or a fallback constant before there are any.
        """
        with self.lock:
            runs = [job for job in self.jobs.values() if job["status"] == config.STATUS_DONE and job["elapsed"] > 0
                    and job["device"] in (device, None)]
        rates = {}
        for job in runs:
            rate = job["elapsed"] / work_megapixels(job["input_size"], job["scale"])
            rates.setdefault((job["model"], job["face_enhance"]), []).append(rate)
        everything = [rate for values in rates.values() for rate in values]
        default = statistics.median(everything) if everything else config.ESTIMATE_FALLBACK_SECONDS_PER_MEGAPIXEL[device]
        by_settings = [{"model": model, "face_enhance": faces, "seconds_per_megapixel": statistics.median(values),
                        "runs": len(values)}
                       for (model, faces), values in rates.items() if len(values) >= config.ESTIMATE_MIN_SAMPLES]
        return {"device": device, "model_scale": config.MODEL_SCALE, "default": default, "by_settings": by_settings}

    def checkpoint_path(self, job_id):
        return self.checkpoint_dir / f"{job_id}{config.CHECKPOINT_SUFFIX}"

    def library_bytes(self):
        """Disk space the originals, results, previews and stopped files' partial results take.

        An original shared through hardlinks, by re-runs and duplicates, counts once.
        """
        # ponytail: stats every file on each status poll (0.2 ms for 84 files); cache it if libraries reach thousands
        folders = (self.input_dir, self.output_dir, self.preview_dir, self.checkpoint_dir)
        stats = [_file_stat(path) for folder in folders for path in folder.iterdir()]
        return sum({(stat.st_dev, stat.st_ino): stat.st_size for stat in stats if stat}.values())

    def get(self, job_id):
        with self.lock:
            return self.jobs.get(job_id)

    def add(self, name, settings, write_input=None, source_job=None, start=False, source=config.SOURCE_UPLOAD):
        """Adds a file as Ready; it only runs once started (Re-run starts right away via start=True)."""
        job = {**JOB_DEFAULTS, "id": uuid.uuid4().hex, "name": name, **settings,
               "input_ext": source_job["input_ext"] if source_job else Path(name).suffix.lower(),
               "source_id": source_job["id"] if source_job else None,
               "source": config.SOURCE_RERUN if source_job else source,
               "status": config.STATUS_QUEUED if start else config.STATUS_READY, "created": time.time(),
               "started": None, "finished": None, "error": None,
               "input_size": None, "output_size": None, "output_bytes": None}
        input_file = self.input_path(job)
        try:
            if source_job:
                input_file.hardlink_to(self.input_path(source_job))
            else:
                write_input(input_file)
        except OSError:
            # A copy cut short (a full disk) would otherwise stay behind until the next start
            input_file.unlink(missing_ok=True)
            raise
        try:
            job["content_hash"] = source_job["content_hash"] if source_job else content_hash(input_file)
            # Hashed as it came: the same phone photo uploaded again matches, even if a newer decoder writes other PNG
            if job["input_ext"] in config.HEIF_EXTENSIONS:
                input_file = heif_to_png(input_file)
                job["input_ext"] = input_file.suffix
            job["mirrored"], job["rotation"] = ((source_job["mirrored"], source_job["rotation"]) if source_job
                                                else exif_transform(input_file))
            job.update(read_photo_info(input_file))
            job["input_size"] = self._write_preview(input_file, self.preview_path(job), job["rotation"],
                                                    job["mirrored"])
        except Image.DecompressionBombError as error:
            input_file.unlink(missing_ok=True)
            raise ValueError(too_many_pixels(name, error))
        except OSError:
            input_file.unlink(missing_ok=True)
            raise ValueError(f"{name} is not a readable image")
        if not source_job:
            self._share_original(job, input_file)
        with self.lock:
            self.jobs[job["id"]] = job
            self._save()
        if start:
            self.pending.put(job["id"])
        return job

    def _share_original(self, job, source):
        """An upload with the same bytes as a photo already here is marked as that photo, and its original becomes a
        hardlink to that one's, so it is stored once.

        The link is made aside and then swapped in: if that photo is removed meanwhile, the upload keeps its own copy.
        """
        with self.lock:
            same = [other for other in self.jobs.values() if other["content_hash"] == job["content_hash"]]
        if not same:
            return
        original = min(same, key=lambda other: other["created"])
        link = source.with_name(source.name + config.TEMPORARY_SUFFIX)
        try:
            link.hardlink_to(self.input_path(original))
        except OSError:
            return
        link.replace(source)
        job["duplicate_of"] = original["id"]

    @staticmethod
    def _write_preview(source, target, rotation, mirrored):
        """Browser-safe JPEG of the original (TIFF/BMP don't display), also used by View."""
        with Image.open(source) as image:
            upright = eight_bit_grey(image).convert("RGB")
            if mirrored:
                upright = upright.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
            rotated = upright.rotate(-90 * rotation, expand=True)
            icc_profile = {"icc_profile": image.info["icc_profile"]} if image.info.get("icc_profile") else {}
            rotated.save(target, "JPEG", quality=config.PREVIEW_QUALITY, **icc_profile)
            return list(rotated.size)

    def delete(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] == config.STATUS_PROCESSING:
                return False
            del self.jobs[job_id]
            self._save()
        for path in (self.input_path(job), self.preview_path(job), self.result_preview_path(job), self.output_path(job),
                     self.checkpoint_path(job_id)):
            path.unlink(missing_ok=True)
        self._remove_strip_files(job_id)
        return True

    def clear_finished(self):
        """Takes finished files off the queue list; they stay in the day pages until deleted."""
        with self.lock:
            finished = [job for job in self.jobs.values()
                        if job["status"] == config.STATUS_DONE and not job["cleared"]]
            for job in finished:
                job["cleared"] = True
            self._save()
        return len(finished)

    def _disk_claimed(self):
        """Disk the results of files already waiting or running will take; the caller holds the lock."""
        waiting = [job for job in self.jobs.values() if job["status"] in LOCKED_STATUSES]
        return sum(disk_needed(job["input_size"], job) for job in waiting)

    def preflight(self, job, settings):
        """Why a file (a re-run, for one) would fail if it started now with these fitted settings; empty when it can."""
        with self.lock:
            return preflight_problems(job["name"], job["input_size"], settings, self.output_dir, self._disk_claimed())

    def start(self, job_ids, global_settings):
        """Queues Ready files, oldest first, with their own settings if set, otherwise the global ones.

        A target long edge becomes each file's own scale here. A file that would fail anyway (too wide for its format,
        short of RAM or disk, or already big enough for its target) stays Ready with the reason.
        Returns the started jobs and the refused ones as {"id", "name", "problems"}.
        """
        with self.lock:
            ready = [self.jobs[job_id] for job_id in job_ids
                     if job_id in self.jobs and self.jobs[job_id]["status"] == config.STATUS_READY]
            ready.sort(key=lambda job: job["created"])
            # Results still to be written, including those started in this same batch, share the free disk
            disk_claimed = self._disk_claimed()
            started, refused = [], []
            for job in ready:
                settings = fitted_settings(job["input_size"], job if job["custom_settings"] else global_settings)
                problems = preflight_problems(job["name"], job["input_size"], settings, self.output_dir, disk_claimed)
                if problems:
                    job["error"] = config.PROBLEM_SEPARATOR.join(problems)
                    refused.append({"id": job["id"], "name": job["name"], "problems": problems})
                    continue
                disk_claimed += disk_needed(job["input_size"], settings)
                job.update({} if job["custom_settings"] else global_settings, scale=settings["scale"],
                           status=config.STATUS_QUEUED, error=None)
                started.append(job)
            self._save()
        for job in started:
            self.pending.put(job["id"])
        return started, refused

    def set_settings(self, job_id, settings):
        """Gives a file its own settings, or None to follow the global ones again.

        Only before it starts; a stopped file goes back to Ready and starts over, since its partial result
        was made with the old settings.
        """
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] not in (config.STATUS_READY, config.STATUS_STOPPED):
                return None
            self._drop_checkpoint(job_id)
            job.update(settings or {}, custom_settings=settings is not None, status=config.STATUS_READY,
                       progress=0.0, stage=None, elapsed=0.0, error=None)
            self._save()
            return dict(job)

    def ready_ids(self):
        with self.lock:
            return [job_id for job_id, job in self.jobs.items() if job["status"] == config.STATUS_READY]

    def rename(self, job_id, name):
        name = validate_name(name)
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job["name"] = name
            self._save()
            return dict(job)

    def stop(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return False
            if job["status"] == config.STATUS_PROCESSING:
                job["stop_requested"] = True
                return True
            if job["status"] != config.STATUS_QUEUED:
                return False
            job["status"] = config.STATUS_STOPPED
            self._save()
            return True

    def resume(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] != config.STATUS_STOPPED:
                return False
            job.update(status=config.STATUS_QUEUED, error=None)
            self._save()
        self.pending.put(job_id)
        return True

    def rotate(self, job_id, turns):
        """Turns the job clockwise: the original (applied at processing time), its preview and any result."""
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None or job["status"] in LOCKED_STATUSES:
                return None
            # A partial result and a test strip's spot no longer match the new orientation
            self._drop_checkpoint(job_id)
            job["strip"] = None
            self._remove_strip_files(job_id)
            job["rotation"] = (job["rotation"] + turns) % QUARTER_TURNS
            job["input_size"] = self._write_preview(self.input_path(job), self.preview_path(job), job["rotation"],
                                                    job["mirrored"])
            if job["status"] == config.STATUS_STOPPED:
                job["progress"] = 0.0
            if job["status"] == config.STATUS_DONE:
                metadata = read_metadata(self.input_path(job), job["scale"], print_dpi(job))
                rotated = rotate_file(self.output_path(job), turns, metadata, job["quality"])
                self._refresh_result_preview(job, rotated, metadata)
                job["output_size"] = job["output_size"][::-1] if turns % 2 else job["output_size"]
                job["output_bytes"] = self.output_path(job).stat().st_size
            self._save()
            return dict(job)

    def _refresh_result_preview(self, job, image, metadata):
        """Remakes the result's preview after a rotation; if that fails the stale one goes, and a request remakes it."""
        try:
            write_result_preview(self.result_preview_path(job), image, metadata)
        except Exception:
            traceback.print_exc()
            self.result_preview_path(job).unlink(missing_ok=True)

    def report(self, job, **changes):
        """In-memory progress update; persisted with the next status change."""
        with self.lock:
            job.update(changes)

    def _update(self, job, **changes):
        with self.lock:
            job.update(changes)
            self._save()

    def _finish(self, job, **changes):
        now = time.time()
        self._update(job, finished=now, elapsed=job["elapsed"] + now - job["started"], stop_requested=False,
                     **changes)

    def _save_checkpoint(self, job, checkpoint):
        """Keeps a Stop's partial result on disk, so Resume survives a restart and the RAM is freed.

        Returns why it could not be written (a full disk, for one), or None.
        """
        path = self.checkpoint_path(job["id"])
        temporary = path.with_name(path.name + config.TEMPORARY_SUFFIX)
        try:
            with temporary.open("wb") as file:
                np.savez(file, output=np.asarray(checkpoint["output"]), next_tile=checkpoint["next_tile"],
                         tile=job["tile"])
            temporary.replace(path)
        except OSError as error:
            temporary.unlink(missing_ok=True)
            return str(error)
        return None

    def _load_checkpoint(self, job):
        """A Stop's partial result, or None if there is none or it was cut with another tile size."""
        path = self.checkpoint_path(job["id"])
        if not path.exists():
            return None
        try:
            with np.load(path, allow_pickle=False) as saved:
                checkpoint = {"next_tile": int(saved["next_tile"]), "output": saved["output"], "tile": int(saved["tile"])}
        # A damaged file, from a crash mid-write for one, just means starting over
        except Exception:
            traceback.print_exc()
            return None
        return checkpoint if checkpoint["tile"] == job["tile"] else None

    def _drop_checkpoint(self, job_id):
        self.checkpoint_path(job_id).unlink(missing_ok=True)

    def _process(self, upscaler, job):
        # A run from the start uses the configured tile; a resumed one keeps the tile its checkpoint was cut with
        tile = job["tile"] if self.checkpoint_path(job["id"]).exists() else config.TILE
        self._update(job, status=config.STATUS_PROCESSING, started=time.time(), error=None,
                     stage=config.STAGE_STARTING, tile=tile, device=upscaler.device)
        # Out of GPU memory: start over with half the tile size, freeing the card between attempts
        while self._attempt(upscaler, job):
            upscaler.release_memory()

    def _attempt(self, upscaler, job):
        """One run of the job; True when it ran out of GPU memory and should start over with smaller tiles."""
        progress = JobProgress(self, job, self._load_checkpoint(job), upscaler)
        try:
            width, height, faces_found = upscaler.run(
                self.input_path(job), self.output_path(job), progress, scale=job["scale"],
                face_enhance=job["face_enhance"], face_fidelity=job["face_fidelity"], face_pass=job["face_pass"],
                rotation=job["rotation"], mirrored=job["mirrored"], model=job["model"], denoise=job["denoise"], quality=job["quality"],
                tile=job["tile"], preview_path=self.result_preview_path(job), print_dpi=print_dpi(job))
        except JobStopped as stopped:
            unsaved = self._save_checkpoint(job, stopped.checkpoint)
            lost_place = {"progress": 0.0, "error": config.ERROR_CHECKPOINT_NOT_SAVED.format(reason=unsaved)}
            self._finish(job, status=config.STATUS_STOPPED, stage=None, **(lost_place if unsaved else {}))
            return False
        except Exception as error:
            # A model the app can't run is explained on the file; anything else leaves its traceback in the log
            if not isinstance(error, UnusableModelError):
                traceback.print_exc()
            self._drop_checkpoint(job["id"])
            retry_tile = smaller_tile(job["tile"]) if is_gpu_out_of_memory(error) else None
            if retry_tile is None:
                self._finish(job, status=config.STATUS_ERROR, error=describe_error(error, job["tile"]))
                return False
            self._update(job, tile=retry_tile, stage=config.STAGE_RETRYING.format(tile=retry_tile), progress=0.0)
            return True
        self._drop_checkpoint(job["id"])
        self._finish(job, status=config.STATUS_DONE, progress=1.0, stage=None, output_size=[width, height],
                     output_bytes=self.output_path(job).stat().st_size, faces_found=faces_found)
        return False

    def engine_problem(self):
        """Why nothing can run: the models failed to load, or the worker died since (a full disk, for one)."""
        if self.engine_error:
            return self.engine_error
        if self.engine_ready and not self.worker.is_alive():
            return config.ERROR_WORKER_STOPPED
        return None

    def strip_path(self, job_id, key):
        return self.preview_dir / f"{job_id}{config.STRIP_FILE_INFIX}{key}.jpg"

    def _remove_strip_files(self, job_id):
        for path in self.preview_dir.glob(f"{job_id}{config.STRIP_FILE_INFIX}*"):
            path.unlink(missing_ok=True)

    def _queue_strip(self, job_id):
        self.strips.put(job_id)
        self.pending.put(STRIP_WAKE_UP)

    def request_strip(self, job_id, x, y, scale, denoise):
        """Asks for a test strip around the spot (x, y), given as shares of the photo's width and height.

        Returns the job, or None if there is no such job.
        """
        if not (0 <= x <= 1 and 0 <= y <= 1):
            raise ValueError(config.ERROR_BAD_STRIP_POINT)
        # Only the scale and the denoise matter here; the rest are the defaults, known to be valid
        validate_settings(scale, False, config.DEFAULT_FORMAT, config.DEFAULT_MODEL, denoise)
        strip = {"status": config.STRIP_STATUS_PENDING, "x": x, "y": y, "scale": scale, "denoise": denoise,
                 "requested": time.time(), "crop": None, "keys": [], "error": None}
        with self.lock:
            job = self.jobs.get(job_id)
            if job is None:
                return None
            job["strip"] = strip
            self._save()
        self._queue_strip(job_id)
        return dict(job)

    def run_strips(self, upscaler):
        """Runs the test strips asked for so far: between jobs, and between two tiles of a running one."""
        while not self.strips.empty():
            self._run_strip(upscaler, self.strips.get())

    def _run_strip(self, upscaler, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            strip = job["strip"] if job else None
        if not strip or strip["status"] != config.STRIP_STATUS_PENDING:
            return
        try:
            crop, keys = upscaler.run_strip(self.input_path(job), job["rotation"], job["mirrored"], strip,
                                            lambda key: self.strip_path(job_id, key))
            outcome = {"status": config.STRIP_STATUS_DONE, "crop": crop, "keys": keys}
        except Exception as error:
            if not isinstance(error, UnusableModelError):
                traceback.print_exc()
            self._remove_strip_files(job_id)
            outcome = {"status": config.STRIP_STATUS_ERROR, "error": describe_error(error)}
        with self.lock:
            if self.jobs.get(job_id) is job and job["strip"] is strip:
                job["strip"] = {**strip, **outcome}
                self._save()
                return
        # Removed, rotated or asked again while this ran: its images are stale
        self._remove_strip_files(job_id)

    def work_forever(self, upscaler):
        while True:
            job = self.get(self.pending.get())
            self.run_strips(upscaler)
            if job is None or job["status"] != config.STATUS_QUEUED:
                continue
            self._process(upscaler, job)

    def start_worker(self, upscaler_factory):
        def run():
            # Lower priority (inherited by the torch threads) keeps the desktop usable during long runs
            os.nice(config.WORKER_NICENESS)
            try:
                upscaler = upscaler_factory()
            except Exception as error:
                traceback.print_exc()
                self.engine_error = str(error)
                return
            self.engine_ready = True
            self.work_forever(upscaler)
        self.worker = threading.Thread(target=run, daemon=True, name="upscale-worker")
        self.worker.start()
