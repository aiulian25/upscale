"""Batch mode: upscales every image in a folder with the page's own engine, settings and metadata handling.

run.sh runs it: docker compose run --rm -v ./input:/input:ro -v ./output:/output --entrypoint run.sh upscaler --help
"""
import argparse
import shutil
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image

import config
import custom_models
import preferences
from heif import heif_to_png
from images import exif_transform
from jobs import (describe_error, fitted_settings, is_gpu_out_of_memory, output_name, preflight_problems, print_dpi,
                  smaller_tile, tile_progress, too_many_pixels, validate_settings)


class PrintProgress:
    """Shows a file's stage and share done on stderr, the way the page's bar does."""

    def __init__(self, name, upscaling_stage):
        self.name = name
        self.upscaling_stage = upscaling_stage
        self.span_start, self.span_end = 0.0, 1.0
        self.done = 0.0

    def span(self, start, end):
        self.span_start, self.span_end = start, end

    def stage(self, name):
        if name == config.STAGE_SAVING:
            self.done = config.TILES_PROGRESS_SHARE
        self._show(name)

    def resume(self, output_shape):
        return None

    def tile(self, next_tile, total, output):
        self.done = tile_progress(self.span_start, self.span_end, next_tile, total)
        self._show(self.upscaling_stage)

    def end(self):
        print(file=sys.stderr, flush=True)

    def _show(self, stage):
        line = config.BATCH_PROGRESS_FORMAT.format(name=self.name, stage=stage, percent=round(self.done * 100))
        print(line, end="", file=sys.stderr, flush=True)


def parse_options(argv, defaults):
    """The command line, and the settings it asks for on top of the page's shared defaults."""
    parser = argparse.ArgumentParser(description="Upscales every image in a folder the way the page does.",
                                     formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    parser.add_argument("--input", type=Path, default=config.BATCH_INPUT_DIR, help="an image, or a folder of them")
    parser.add_argument("--output", type=Path, default=config.BATCH_OUTPUT_DIR, help="the folder results go to")
    size = parser.add_mutually_exclusive_group()
    size.add_argument("--scale", type=float, help="upscale factor; without it or --long-edge, the shared default")
    size.add_argument("--long-edge", type=int, help="fit each file to this many pixels on its long edge instead")
    parser.add_argument("--model", choices=list(custom_models.all_models()), default=defaults["model"],
                        help="the Model picker's choices, custom models in data/models included")
    parser.add_argument("--denoise", type=float, default=defaults["denoise"], help="General v3 only: 0 keeps all grain")
    parser.add_argument("--format", choices=list(config.OUTPUT_FORMATS), default=defaults["format"],
                        help="the results' file format")
    parser.add_argument("--quality", type=int, default=defaults["quality"], help="JPG and WebP only")
    parser.add_argument("--faces", action=argparse.BooleanOptionalAction, default=defaults["face_enhance"],
                        help="restore faces with GFPGAN")
    parser.add_argument("--face-fidelity", type=float, default=defaults["face_fidelity"],
                        help="how much of the plain upscale is mixed back into restored faces, 0 to 1")
    parser.add_argument("--face-pass", choices=config.FACE_PASSES, default=defaults["face_pass"],
                        help="look for faces before upscaling, or after it (finds smaller faces)")
    parser.add_argument("--tile", type=int, default=config.TILE, help="tile size in px; halved by itself if the GPU "
                        "runs out of memory")
    options = parser.parse_args(argv)
    target = {"scale": defaults["scale"], "target_mode": defaults["target_mode"],
              "target_long_edge": defaults["target_long_edge"]}
    if options.scale is not None:
        target = {"scale": options.scale, "target_mode": config.TARGET_MODE_SCALE, "target_long_edge": 0}
    if options.long_edge is not None:
        target = {**target, "target_mode": config.TARGET_MODE_LONG_EDGE, "target_long_edge": options.long_edge}
    try:
        settings = validate_settings(target["scale"], options.faces, options.format, options.model, options.denoise,
                                     options.quality, options.face_fidelity, options.face_pass, target["target_mode"],
                                     target["target_long_edge"])
    except ValueError as error:
        parser.error(str(error))
    return options, settings


def images_in(path):
    """The images to upscale: the one named, or those directly in the folder, by name; hidden files are left out."""
    candidates = [path] if path.is_file() else sorted(path.iterdir())
    return [candidate for candidate in candidates
            if candidate.is_file() and not candidate.name.startswith(config.HIDDEN_FILE_PREFIX)
            and candidate.suffix.lower() in config.ALLOWED_INPUT_EXTENSIONS]


def readable_copy(source, folder):
    """The file the engine reads: a phone's HEIC turned into a PNG in folder, as uploads are; others as they are."""
    if source.suffix.lower() not in config.HEIF_EXTENSIONS:
        return source
    copy = folder / source.name
    shutil.copyfile(source, copy)
    return heif_to_png(copy)


def unused_path(path, written):
    """Where a result goes; a name another file of this run already took gets a counter."""
    candidate, count = path, 1
    while candidate in written:
        count += 1
        candidate = path.with_name(config.BATCH_CLASH_NAME.format(stem=path.stem, count=count, suffix=path.suffix))
    written.add(candidate)
    return candidate


def upscale_file(upscaler, source, name, settings, tile, output_dir, written):
    """Upscales one file as a started job would; returns the result's path, width and height."""
    mirrored, rotation = exif_transform(source)
    with Image.open(source) as image:
        width, height = image.size
    input_size = [height, width] if rotation % 2 else [width, height]
    fitted = fitted_settings(input_size, settings)
    problems = preflight_problems(name, input_size, fitted, output_dir)
    if problems:
        raise ValueError(config.PROBLEM_SEPARATOR.join(problems))
    now = time.time()
    target = unused_path(output_dir / output_name({"name": name, **fitted, "created": now, "finished": now}), written)
    stage = config.STAGE_UPSCALING
    # Out of GPU memory: start over with half the tile size, as a job on the page does
    while True:
        progress = PrintProgress(name, stage)
        try:
            width, height, _ = upscaler.run(
                source, target, progress, scale=fitted["scale"], face_enhance=fitted["face_enhance"],
                face_fidelity=fitted["face_fidelity"], face_pass=fitted["face_pass"], rotation=rotation,
                mirrored=mirrored, model=fitted["model"], denoise=fitted["denoise"], quality=fitted["quality"],
                tile=tile, print_dpi=print_dpi(fitted))
            progress.end()
            return target, width, height
        except Exception as error:
            progress.end()
            retry_tile = smaller_tile(tile) if is_gpu_out_of_memory(error) else None
            if retry_tile is None:
                raise
            upscaler.release_memory()
            tile, stage = retry_tile, config.STAGE_RETRYING.format(tile=retry_tile)


def reason_for(name, error, tile):
    if isinstance(error, Image.DecompressionBombError):
        return too_many_pixels(name, error)
    return describe_error(error, tile)


def run_batch(sources, output_dir, settings, tile, upscaler):
    """Upscales each source into output_dir, going on past any that fail; returns the exit code: 1 if any failed."""
    output_dir.mkdir(parents=True, exist_ok=True)
    written = set()
    failures = 0
    for source in sources:
        started = time.time()
        try:
            with tempfile.TemporaryDirectory() as folder:
                target, width, height = upscale_file(upscaler, readable_copy(source, Path(folder)), source.name,
                                                     settings, tile, output_dir, written)
        except Exception as error:
            failures += 1
            print(config.BATCH_SKIPPED_FORMAT.format(name=source.name, reason=reason_for(source.name, error, tile)),
                  flush=True)
            continue
        print(config.BATCH_DONE_FORMAT.format(name=source.name, output=target, width=width, height=height,
                                              seconds=time.time() - started), flush=True)
    return 1 if failures else 0


def main(argv=None):
    custom_models.scan()
    options, settings = parse_options(argv, preferences.load()["defaults"])
    sources = images_in(options.input)
    if not sources:
        print(config.BATCH_NOTHING_FOUND.format(input=options.input), file=sys.stderr)
        return 1
    # Imported here: loading torch and the models is only worth it once there is something to upscale
    from upscaler import Upscaler, device_name
    print(config.BATCH_DEVICE_FORMAT.format(device=device_name()), file=sys.stderr, flush=True)
    return run_batch(sources, options.output, settings, options.tile, Upscaler())


if __name__ == "__main__":
    sys.exit(main())
