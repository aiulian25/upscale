"""Self-check for the job store: python /srv/web/test_jobs.py (inside the container)."""
import contextlib
import hashlib
import io
import json
import tempfile
import os
import shutil
import threading
import zipfile
from pathlib import Path
from types import SimpleNamespace

import cv2
import numpy as np
import pillow_heif
import torch
from PIL import ExifTags, Image, ImageCms, ImageOps, UnidentifiedImageError

import batch
import config
import custom_models
import jobs
import preferences
import upscaler as upscaler_module
from cross_site import is_cross_site
from custom_models import UnusableModelError, all_models
from inbox import InboxWatcher
from images import (EXIF_ORIENTATION_TAG, EXIF_TAG_DATETIME, EXIF_TAG_DATETIME_ORIGINAL, EXIF_TAG_EXIF_IFD,
                    EXIF_TAG_MAKE, EXIF_TAG_MODEL, EXIF_TAG_X_RESOLUTION, UINT16_PER_UINT8, read_metadata,
                    read_photo_info, rotate, write_image, write_result_preview)
from jobs import (JobStore, available_ram_bytes, check_name_template, describe_error, output_name, too_many_pixels,
                  validate_settings, work_megapixels)
from upscaler import detection_short_side, restore_faces, strip_crop


class StoppingUpscaler:
    """Stands in for the model: walks four tiles and asks for a stop after the second one on the first run."""

    TILES = 4
    FACES = 3
    device = config.DEVICE_CPU
    SHAPE = (1, 3, 8, 8)

    def __init__(self, store):
        self.store = store
        self.started_at = []

    def run(self, source_path, target_path, progress, **settings):
        next_tile, output = progress.resume(self.SHAPE) or (0, np.zeros(self.SHAPE))
        self.started_at.append(next_tile)
        for index in range(next_tile, self.TILES):
            progress.tile(index, self.TILES, output)
            if index == 1 and len(self.started_at) == 1:
                self.store.stop(progress.job["id"])
        progress.tile(self.TILES, self.TILES, output)
        Image.new("RGB", (8, 4)).save(target_path)
        Image.new("RGB", (8, 4)).save(settings["preview_path"])
        return 8, 4, self.FACES


class OutOfMemoryUpscaler:
    """Stands in for a GPU that runs out of memory until the tile is small enough."""

    device = config.DEVICE_GPU

    def __init__(self, fits_at):
        self.fits_at = fits_at
        self.tiles = []
        self.releases = 0

    def run(self, source_path, target_path, progress, **settings):
        self.tiles.append(settings["tile"])
        if settings["tile"] > self.fits_at:
            raise RuntimeError("CUDA out of memory. Tried to allocate 2.00 GiB")
        Image.new("RGB", (8, 4)).save(target_path)
        Image.new("RGB", (8, 4)).save(settings["preview_path"])
        return 8, 4, None

    def release_memory(self):
        self.releases += 1


class StripUpscaler:
    """Stands in for the models in a test strip: one small image per key; can ask for another strip meanwhile."""

    device = config.DEVICE_CPU

    def __init__(self, meanwhile=None):
        self.meanwhile = meanwhile

    def run_strip(self, source_path, rotation, mirrored, strip, path_for):
        keys = [config.STRIP_ORIGINAL_KEY, *config.MODELS]
        for key in keys:
            Image.new("RGB", (4, 4)).save(path_for(key), "JPEG")
        meanwhile, self.meanwhile = self.meanwhile, None
        if meanwhile:
            meanwhile()
        return [0, 0, 4, 4], keys


class TwoTileUpscaler(StripUpscaler):
    """Runs a two-tile job and notes whether a test strip asked for before it had run by the second tile."""

    def __init__(self, store, strip_job_id):
        super().__init__()
        self.store, self.strip_job_id, self.strip_ran_mid_job = store, strip_job_id, None

    def run(self, source_path, target_path, progress, **settings):
        progress.tile(1, 2, None)
        self.strip_ran_mid_job = self.store.get(self.strip_job_id)["strip"]["status"] == config.STRIP_STATUS_DONE
        Image.new("RGB", (8, 4)).save(target_path)
        Image.new("RGB", (8, 4)).save(settings["preview_path"])
        return 8, 4, None


def named(name, **fields):
    """The fields of a finished job that its download name is made from."""
    return {"name": name, "format": "png", "scale": 4, "model": "x", "face_enhance": True, "finished": None, "created": 0,
            **fields}


def face_stand_ins(upscaled, paste):
    """GFPGAN's face helper and the upscaling model, as restore_faces uses them."""
    helper = SimpleNamespace(get_inverse_affine=lambda path: None, paste_faces_to_input_image=paste)
    return SimpleNamespace(face_helper=helper), SimpleNamespace(enhance=lambda image, outscale: (upscaled, None))


def paste_face_on_right_half(upsample_img):
    """Pastes a face of 200 the way facexlib's paste does, which only works on 8-bit colour."""
    is_colour = upsample_img.ndim == 3 and upsample_img.shape[2] in (3, 4)
    assert upsample_img.dtype == np.uint8 and is_colour, "facexlib's paste only takes 8-bit colour"
    pasted = upsample_img.copy()
    pasted[:, upsample_img.shape[1] // 2:] = 200
    return pasted


class GoneModelUpscaler:
    """Stands in for the upscaler when a file's custom model has left data/models."""

    device = config.DEVICE_CPU

    def run(self, source_path, target_path, progress, **settings):
        raise UnusableModelError(settings["model"], config.MODEL_GONE)


def check_custom_models():
    """Usable model files in data/models join the list and run; others are left out with the reason, and a .pth that
    holds more than weights never gets to run its code."""
    from safetensors.torch import save_file
    from spandrel.architectures.Compact import Compact

    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folder = root / "models"
        folder.mkdir()
        marker = root / "payload-ran"

        class Payload:
            def __reduce__(self):
                return os.mkdir, (str(marker),)

        def tiny(upscale):
            return Compact(num_in_ch=3, num_out_ch=3, num_feat=8, num_conv=2, upscale=upscale).state_dict()

        save_file(tiny(2), folder / "2xTiny.safetensors")
        torch.save(tiny(1), folder / "1xTiny.pth")
        torch.save({"weight": torch.zeros(1)}, folder / "unknown.pth")
        torch.save({**tiny(4), "extra": Payload()}, folder / "hostile.pth")
        torch.save(tiny(4), folder / f"{config.DEFAULT_MODEL}.pth")
        torch.save(tiny(4), folder / "bad name!.pth")
        (folder / "notes.txt").write_text("not a model")
        (folder / ".hidden.pth").write_text("ignored")
        custom_models.scan(folder)
        assert list(custom_models.found) == ["2xTiny"] and list(all_models())[-1] == "2xTiny", \
            "a usable model follows the built-in ones"
        assert custom_models.skipped == {
            "1xTiny.pth": config.MODEL_NOT_SUPPORTED.format(architecture="RealESRGAN Compact", scale=1,
                                                           purpose="Restoration", input_channels=3, output_channels=3),
            "bad name!.pth": config.MODEL_BAD_NAME,
            "hostile.pth": custom_models.skipped["hostile.pth"],
            f"{config.DEFAULT_MODEL}.pth": config.MODEL_BUILT_IN_NAME,
            "notes.txt": config.MODEL_NOT_A_MODEL_FILE,
            "unknown.pth": config.MODEL_UNKNOWN_ARCHITECTURE}, custom_models.skipped
        assert custom_models.skipped["hostile.pth"].startswith(config.MODEL_NOT_JUST_WEIGHTS.partition("(")[0]) \
            and not marker.exists(), "a .pth that holds more than weights is refused without running its code"
        assert validate_settings(2, False, "png", "2xTiny")["model"] == "2xTiny"

        descriptor = upscaler_module.load_model("2xTiny", custom_models.found["2xTiny"], None)
        wrapper = upscaler_module.TrackedRealESRGANer(descriptor)
        wrapper.progress = upscaler_module.StripProgress()
        output, _ = wrapper.enhance(np.zeros((12, 17, 3), np.uint8), outscale=4)
        assert output.shape == (48, 68, 3), "a 2× model runs twice for 4×"

        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder_path in folders:
            folder_path.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        settings = validate_settings(2, False, "png")
        own = store.add("own.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        store.set_settings(own["id"], validate_settings(2, False, "png", "2xTiny"))
        (folder / "2xTiny.safetensors").unlink()
        try:
            upscaler_module.load_model("2xTiny", custom_models.found["2xTiny"], None)
            raise AssertionError("loaded a model whose file is gone")
        except UnusableModelError as error:
            assert error.reason == config.MODEL_GONE
        custom_models.scan(folder)  # a restart without the file
        gone = config.ERROR_UNUSABLE_MODEL.format(model="2xTiny", reason=config.MODEL_GONE)
        assert "2xTiny" not in all_models() and store.start([own["id"]], settings)[1][0]["problems"] == [gone], \
            "a file whose own model is gone stays Ready with the reason"
        queued = store.add("queued.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        queued.update(model="2xTiny", status=config.STATUS_QUEUED)
        with contextlib.redirect_stderr(io.StringIO()) as log:
            store._process(GoneModelUpscaler(), queued)
        assert queued["status"] == config.STATUS_ERROR and queued["error"] == gone and "Traceback" not in log.getvalue(), \
            "one that was already queued fails with the reason, and no traceback in the log"
        empty = root / "empty"
        empty.mkdir()
        custom_models.scan(empty)
    assert not custom_models.found and not custom_models.skipped, "the rest of the checks see the built-in models only"


def check_orientations():
    """Each of the eight EXIF orientations, mirrored ones included, shows upright as Pillow's exif_transpose shows it:
    in the preview, and in the pixels the upscaler reads."""
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder in folders:
            folder.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        settings = validate_settings(2, False, "png")
        marked = Image.new("RGB", (30, 20), (0, 0, 255))
        marked.paste((255, 0, 0), (0, 0, 10, 10))
        marked.paste((0, 255, 0), (20, 10, 30, 20))
        for orientation in range(1, 9):
            exif = Image.Exif()
            exif[EXIF_ORIENTATION_TAG] = orientation
            path = root / f"orientation {orientation}.png"
            marked.save(path, exif=exif.tobytes())
            with Image.open(path) as source:
                expected = np.asarray(ImageOps.exif_transpose(source).convert("RGB"))
            job = store.add(path.name, settings, write_input=lambda target, path=path: shutil.copyfile(path, target))
            with Image.open(store.preview_path(job)) as preview:
                shown = np.asarray(preview.convert("RGB"))
            assert shown.shape == expected.shape and np.abs(shown.astype(int) - expected).mean() < 12, \
                f"orientation {orientation}: the preview isn't upright"
            engine = rotate(cv2.cvtColor(np.asarray(marked), cv2.COLOR_RGB2BGR), job["rotation"], job["mirrored"])
            assert np.array_equal(cv2.cvtColor(engine, cv2.COLOR_BGR2RGB), expected), \
                f"orientation {orientation}: the upscaler doesn't read it upright"
        mirrored = next(job for job in store.all_jobs() if job["name"] == "orientation 5.png")
        assert mirrored["mirrored"] and store.add("again.png", settings, source_job=store.get(mirrored["id"]))["mirrored"], \
            "a re-run keeps the mirror"


class RecordingUpscaler:
    """Stands in for the engine in batch mode: records what each file ran with and writes a small result."""

    device = config.DEVICE_CPU

    def __init__(self):
        self.runs = []

    def run(self, source_path, target_path, progress, **settings):
        self.runs.append({"source": Path(source_path), "target": target_path, **settings})
        progress.tile(1, 1, None)
        Image.new("RGB", (8, 4)).save(target_path)
        return 8, 4, None

    def release_memory(self):
        pass


def check_batch():
    """Batch mode runs each image of a folder like a started job, goes on past one it can't read, and never overwrites
    a result it wrote earlier in the same run."""
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folder, output = root / "input", root / "output"
        folder.mkdir()
        for name in ("photo.jpg", "photo.png", ".hidden.jpg"):
            Image.new("RGB", (100, 50)).save(folder / name)
        (folder / "broken.jpg").write_text("not an image")
        (folder / "notes.txt").write_text("not an image type")
        pillow_heif.from_pillow(Image.new("RGB", (100, 50))).save(folder / "phone.heic")
        options, settings = batch.parse_options(["--input", str(folder), "--output", str(output), "--long-edge", "300",
                                                 "--format", "png", "--no-faces"], preferences.ENV_DEFAULTS)
        sources = batch.images_in(options.input)
        assert [path.name for path in sources] == ["broken.jpg", "phone.heic", "photo.jpg", "photo.png"]
        engine = RecordingUpscaler()
        with contextlib.redirect_stdout(io.StringIO()) as log, contextlib.redirect_stderr(io.StringIO()):
            exit_code = batch.run_batch(sources, options.output, settings, options.tile, engine)
        assert exit_code == 1 and "skipped broken.jpg" in log.getvalue(), "a file it can't read is reported, the rest run"
        assert sorted(path.name for path in output.iterdir()) == [
            "phone_upscaled.png", "photo_upscaled (2).png", "photo_upscaled.png"], "a name taken earlier gets a counter"
        phone = next(run for run in engine.runs if run["target"].name == "phone_upscaled.png")
        assert phone["source"].suffix == ".png" and phone["scale"] == 3.0 and not phone["face_enhance"], \
            "a HEIC runs from its PNG, fitted to the long edge asked for"
        try:
            with contextlib.redirect_stderr(io.StringIO()):
                batch.parse_options(["--model", "bogus"], preferences.ENV_DEFAULTS)
            raise AssertionError("accepted an unknown model")
        except SystemExit as exit_error:
            assert exit_error.code == 2, "an unknown model is refused like any bad option"


def check_tiff_metadata_and_sixteen_bit_preview():
    """A TIFF's result keeps the photo's EXIF with its EXIF and GPS blocks, but not how the TIFF stores its pixels nor
    a resolution it never stated; a 16-bit greyscale original gets a real preview, not a white one."""
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        details = Image.Exif()
        details[EXIF_TAG_MAKE], details[EXIF_TAG_MODEL] = "Nikon", "Coolscan 5000"
        details[EXIF_TAG_EXIF_IFD] = {EXIF_TAG_DATETIME_ORIGINAL: "2001:02:03 04:05:06"}
        details[ExifTags.IFD.GPSInfo] = {ExifTags.GPS.GPSLatitudeRef: "N"}
        scan = root / "scan.tif"
        Image.new("RGB", (64, 48)).save(scan, "TIFF", exif=details.tobytes(), dpi=(600, 600))
        metadata = read_metadata(scan, 2)
        kept = Image.Exif()
        kept.load(metadata["exif"])
        assert kept.get(EXIF_TAG_MODEL) == "Coolscan 5000" and metadata["dpi"] == (1200, 1200)
        assert kept.get_ifd(EXIF_TAG_EXIF_IFD) == {EXIF_TAG_DATETIME_ORIGINAL: "2001:02:03 04:05:06"} and \
            kept.get_ifd(ExifTags.IFD.GPSInfo) == {ExifTags.GPS.GPSLatitudeRef: "N"}, "its EXIF and GPS blocks are kept"
        layout = {ExifTags.Base.ImageWidth, ExifTags.Base.StripOffsets, ExifTags.Base.Compression}
        assert not layout & set(kept), "a TIFF's layout isn't carried into the result"
        strips = root / "strips.tif"
        Image.new("RGB", (640, 480)).save(strips, "TIFF", compression="tiff_lzw")
        with Image.open(strips) as image:
            assert len(image.tag_v2[ExifTags.Base.StripOffsets]) > 1
        assert read_metadata(strips, 2) == {}, "a TIFF in several strips, stating no resolution, gives no EXIF or DPI"

        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder in folders:
            folder.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        ramp = np.linspace(0, np.iinfo(np.uint16).max, 30 * 20).reshape(20, 30).astype(np.uint16)
        grey = store.add("grey16.png", validate_settings(2, False, "png"),
                         write_input=lambda path: cv2.imwrite(str(path), ramp))
        with Image.open(store.preview_path(grey)) as preview:
            shown = np.asarray(preview.convert("L"), float)
        expected = ramp / UINT16_PER_UINT8
        assert abs(shown.mean() - expected.mean()) < 2 and np.abs(shown - expected).mean() < 3, \
            f"a 16-bit greyscale preview is the original's values / 257, not white: mean {shown.mean():.1f}"
        # A 32-bit TIFF opens in mode "I": 16-bit values in it are scaled too, and anything beyond saturates
        beyond = np.array([[-600] * 8 + [40000] * 8 + [2_000_000] * 8] * 16, np.int32)
        wide = store.add("wide.tif", validate_settings(2, False, "png"),
                         write_input=lambda path: Image.fromarray(beyond).save(path, "TIFF"))
        with Image.open(store.preview_path(wide)) as preview:
            shown = np.asarray(preview.convert("L"))
        assert abs(shown[:, 10:14].mean() - 40000 / UINT16_PER_UINT8) < 4, "16-bit values in a 32-bit TIFF are scaled"
        assert shown[:, :4].max() < 16 and shown[:, -4:].min() > 239, \
            "values beyond 16 bits end at black and white instead of wrapping around"


def inputs_match_jobs(store):
    """Every original in the input folder belongs to a job, and every job has its original."""
    owned = {store.input_path(job).name for job in store.all_jobs()}
    return {path.name for path in store.input_dir.iterdir()} == owned


def check_heif():
    """A phone's HEIC photo is kept as an upright PNG with its camera details and colour profile; libheif runs apart."""
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder in folders:
            folder.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        settings = validate_settings(2, False, "png")
        sideways = Image.new("RGB", (60, 40), "red")
        sideways.paste((0, 0, 255), (30, 0, 60, 40))
        exif = Image.Exif()
        # Stored as phones do: the pixels as the sensor saw them, and a rotation box that turns them a quarter clockwise
        exif[EXIF_TAG_MAKE], exif[EXIF_TAG_MODEL], exif[EXIF_ORIENTATION_TAG] = "Apple", "iPhone Test", 6
        srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
        heic = root / "sideways.heic"
        pillow_heif.from_pillow(sideways).save(heic, exif=exif.tobytes(), icc_profile=srgb)

        def copy_heic(path):
            shutil.copyfile(heic, path)

        phone = store.add("IMG_0001.HEIC", settings, write_input=copy_heic)
        stored = store.input_path(phone)
        assert phone["input_ext"] == config.HEIF_STORED_AS and inputs_match_jobs(store), "kept as a PNG, and only that"
        assert phone["input_size"] == [40, 60] and phone["rotation"] == 0, "upright, and not turned a second time"
        assert phone["camera"] == "Apple iPhone Test", "its camera is read from the PNG"
        with Image.open(stored) as png:
            assert png.format == "PNG" and png.info.get("icc_profile") == srgb, "the colour profile is kept"
            assert png.getexif().get(EXIF_TAG_MODEL) == "iPhone Test" and png.getexif().get(EXIF_ORIENTATION_TAG) == 1
            top, bottom = png.getpixel((0, 0)), png.getpixel((0, 59))
        assert top[0] > top[2] and bottom[2] > bottom[0], "the sensor's left side ends up on top"
        assert phone["content_hash"] == hashlib.sha256(heic.read_bytes()).hexdigest(), "hashed as uploaded, not as PNG"
        again = store.add("IMG_0001 (1).HEIC", settings, write_input=copy_heic)
        shared = os.stat(store.input_path(again)).st_ino == stored.stat().st_ino
        assert again["duplicate_of"] == phone["id"] and shared, "the same photo uploaded again is a duplicate, stored once"

        try:
            Image.open(heic)
            raise AssertionError("libheif was loaded into the app")
        except UnidentifiedImageError:
            pass
        half = heic.read_bytes()[:heic.stat().st_size // 2]

        def refused(name, write_input):
            try:
                store.add(name, settings, write_input=write_input)
            except ValueError:
                return True
            return False

        with contextlib.redirect_stdout(io.StringIO()) as log:
            assert refused("disguised.png", copy_heic), "HEIC named .png never reaches libheif"
            assert refused("broken.heic", lambda path: path.write_bytes(half))
            timeout, config.HEIF_CONVERT_TIMEOUT_SECONDS = config.HEIF_CONVERT_TIMEOUT_SECONDS, 0.001
            try:
                assert refused("slow.heic", copy_heic)
            finally:
                config.HEIF_CONVERT_TIMEOUT_SECONDS = timeout
        assert "cannot identify image file" in log.getvalue() and "timed out" in log.getvalue(), \
            "a HEIC libheif can't read, or not in time, is refused with the reason logged"
        assert inputs_match_jobs(store), "and leaves nothing behind"


def check_inbox():
    """Files dropped into the inbox become Ready files one at a time, once whole; what isn't an image is put aside."""
    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder in folders:
            folder.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        settings = validate_settings(2, False, "jpg")
        inbox = root / "inbox"
        watcher = InboxWatcher(store, lambda: settings, inbox, autostart=False)
        rejected = inbox / config.INBOX_REJECTED_NAME
        assert rejected.is_dir(), "the watcher makes the inbox and its rejected/ folder"

        def picture(path):
            Image.new("RGB", (30, 20)).save(path, "PNG")

        def scan_twice():
            watcher.scan_once()
            watcher.scan_once()

        def taken_names():
            return {job["name"] for job in store.all_jobs() if job["source"] == config.SOURCE_INBOX}

        upload = store.add("upload.png", settings, write_input=picture)
        rerun = store.add("upload.png", settings, source_job=upload)
        assert upload["source"] == config.SOURCE_UPLOAD and rerun["source"] == config.SOURCE_RERUN
        saved = [{key: value for key, value in job.items() if key != "source"}
                 for job in json.loads((root / "jobs.json").read_text())]
        (root / "jobs.json").write_text(json.dumps(saved))
        restarted = JobStore(root / "jobs.json", *folders)
        assert restarted.get(upload["id"])["source"] == config.SOURCE_UPLOAD and \
            restarted.get(rerun["id"])["source"] == config.SOURCE_RERUN, "older jobs get their source on start"

        def cut_short(path):
            path.write_bytes(b"half a file")
            raise OSError("No space left on device")

        try:
            store.add("cut.png", settings, write_input=cut_short)
            raise AssertionError("a copy cut short made a job")
        except OSError:
            assert inputs_match_jobs(store), "and leaves no half-written original behind"

        picture(root / "elsewhere.png")
        (inbox / "link.png").symlink_to(root / "elsewhere.png")
        picture(inbox / ".partial.png")
        (inbox / "notes.txt").write_text("not an image type")
        (inbox / "empty.png").touch()
        left_alone = sorted(path.name for path in inbox.iterdir())
        picture(inbox / "scan.png")
        watcher.scan_once()
        assert taken_names() == set(), "a file seen once may still be copying"
        watcher.scan_once()
        scan = next(job for job in store.all_jobs() if job["source"] == config.SOURCE_INBOX)
        assert scan["name"] == "scan.png" and scan["status"] == config.STATUS_READY, "a whole file becomes Ready"
        assert sorted(path.name for path in inbox.iterdir()) == left_alone, \
            "and leaves the inbox, while links, hidden and empty files and other types stay"

        picture(inbox / "b.png")
        picture(inbox / "a.png")
        os.utime(inbox / "b.png", ns=(1, 1))
        scan_twice()
        assert taken_names() == {"scan.png", "b.png"}, "one file per scan, the oldest first"
        watcher.scan_once()
        assert taken_names() == {"scan.png", "b.png", "a.png"}

        whole = io.BytesIO()
        Image.new("RGB", (30, 20)).save(whole, "PNG")
        (inbox / "growing.png").write_bytes(whole.getvalue()[:40])
        watcher.scan_once()
        (inbox / "growing.png").write_bytes(whole.getvalue())
        watcher.scan_once()
        assert "growing.png" not in taken_names(), "a file that grew since the last scan is still being copied"
        watcher.scan_once()
        assert "growing.png" in taken_names()

        # Not UTF-8 and with a backslash: the page's JSON must still carry the name
        Path(os.fsdecode(os.fsencode(inbox) + b"/caf\xe9\\menu.png")).write_bytes(whole.getvalue())
        scan_twice()
        assert "caf__menu.png" in taken_names(), "a name is made safe to show and save"

        with contextlib.redirect_stdout(io.StringIO()) as log:
            (inbox / "bad.png").write_text("nope")
            scan_twice()
            (inbox / "bad.png").write_text("nope again")
            scan_twice()
        assert (rejected / "bad.png").read_text() == "nope", "a file that isn't an image goes to rejected/"
        assert sorted(path.read_text() for path in rejected.iterdir()) == ["nope", "nope again"], \
            "and one with the same name is kept beside it"
        assert "bad.png" not in taken_names() and inputs_match_jobs(store) and "bad.png" in log.getvalue()

        real_unlink = Path.unlink

        def refuse_in_inbox(path, missing_ok=False):
            if path.parent == inbox:
                raise PermissionError("read-only inbox")
            real_unlink(path, missing_ok=missing_ok)

        picture(inbox / "stuck.png")
        Path.unlink = refuse_in_inbox
        try:
            with contextlib.redirect_stdout(io.StringIO()) as log:
                for _ in range(4):
                    watcher.scan_once()
        finally:
            Path.unlink = real_unlink
        assert "stuck.png" not in taken_names() and inputs_match_jobs(store), \
            "a file that can't leave the inbox isn't taken in, or it would be again after a restart"
        assert log.getvalue().count("stuck.png") == 1, "nor tried again at every scan"
        os.utime(inbox / "stuck.png")
        scan_twice()
        assert "stuck.png" in taken_names() and not (inbox / "stuck.png").exists(), "until it changes"

        starter = InboxWatcher(store, lambda: settings, inbox, autostart=True)
        picture(inbox / "first.png")
        picture(inbox / "second.png")
        os.utime(inbox / "first.png", ns=(1, 1))
        for _ in range(3):
            starter.scan_once()
        first = next(job for job in store.all_jobs() if job["name"] == "first.png")
        assert first["status"] == config.STATUS_QUEUED and first["scale"] == 2.0, "autostart starts it with the defaults"
        assert (inbox / "second.png").exists(), "and the next waits in the inbox while one is in line"
        store._process(OutOfMemoryUpscaler(fits_at=config.TILE), store.get(first["id"]))
        assert store.get(first["id"])["status"] == config.STATUS_DONE
        starter.scan_once()
        second = next(job for job in store.all_jobs() if job["name"] == "second.png")
        assert second["status"] == config.STATUS_QUEUED and not (inbox / "second.png").exists(), \
            "once it has finished, the next is taken in and started"


def main():
    assert output_name(named("scan 01.tif", format="webp")) == "scan 01_upscaled.webp"
    assert work_megapixels([1000, 1000], 8) == 80 and work_megapixels([1000, 1000], 2) == 16, "a 4× pass, then one more"
    assert output_name(named("Trip v1.2")) == "Trip v1.2_upscaled.png", "a renamed file keeps its dots"
    assert output_name(named("IMG_0001.HEIC")) == "IMG_0001_upscaled.png", "a phone photo's name loses .HEIC"
    assert output_name(named("..\\..\\evil\x07.png")) == ".._.._evil__upscaled.png", \
        "an uploaded name can't reach outside the folder a zip is unpacked into"
    default_template = config.OUTPUT_NAME_TEMPLATE
    try:
        config.OUTPUT_NAME_TEMPLATE = "{name}_{scale}_{model}"
        assert output_name(named("scan 01.tif", format="webp")) == "scan 01_4x_x.webp"
        assert output_name(named("scan", scale=1.875)) == "scan_1.88x_x.png", "a fitted scale is shown rounded"
        config.OUTPUT_NAME_TEMPLATE = "{name}_{faces}_{date}"
        assert output_name(named("scan", face_enhance=False, finished=86400)) == "scan_nofaces_1970-01-02.png"
    finally:
        config.OUTPUT_NAME_TEMPLATE = default_template
    here, start = {"host": "127.0.0.1:47291"}, "/api/jobs/start"
    for method, path, headers, refused, why in [
            ("GET", "/api/jobs", {**here, "sec-fetch-site": "cross-site"}, False, "reading is never refused"),
            ("POST", start, here, False, "curl and scripts send no Origin"),
            ("POST", start, {**here, "origin": "https://evil.example"}, True, "another site's page is refused"),
            ("POST", start, {**here, "origin": "http://127.0.0.1:47291"}, False, "the page itself is not"),
            ("POST", start, {**here, "origin": "null"}, True, "nor is a sandboxed page"),
            ("POST", start, {**here, "referer": "https://evil.example/page"}, True, "Referer stands in for Origin"),
            ("POST", start, {**here, "referer": "http://127.0.0.1:47291/#/settings"}, False, "for the page too"),
            ("DELETE", "/api/jobs/x", {**here, "sec-fetch-site": "same-site"}, True, "another app on this machine"),
            ("POST", start, {**here, "sec-fetch-site": "same-origin", "origin": "https://photos.example"}, False,
             "the browser's word comes first, so a proxy that rewrites Host doesn't matter"),
            ("POST", start, {**here, "x-forwarded-host": "Photos.Example, proxy", "origin": "https://photos.example"},
             False, "the host a reverse proxy passes on counts as this one"),
            ("GET", config.ALL_OUTPUTS_ZIP_PATH, {**here, "sec-fetch-site": "cross-site"}, True, "no zip for others"),
            ("GET", config.ALL_OUTPUTS_ZIP_PATH, {**here, "sec-fetch-site": "same-origin"}, False, "but for the page")]:
        assert is_cross_site(method, path, headers) == refused, why
    for bad_template in ["{name.__class__}", "{name[0]}", "{name!r}", "{name:>9}", "{nme}", "{}", "{date}/{name}",
                         "..\\{name}", "{name", " "]:
        try:
            check_name_template(bad_template)
            raise AssertionError(f"accepted the template {bad_template!r}")
        except ValueError:
            pass
    assert describe_error(RuntimeError("CUDA out of memory. Tried"), 200) == config.ERROR_OUT_OF_GPU_MEMORY.format(tile=200)
    lossy = (4, True, "jpg", config.DEFAULT_MODEL, config.DEFAULT_DENOISE)
    fidelity = (*lossy, config.DEFAULT_QUALITY)
    for bad in [(0.5, True, "png"), (9, True, "png"), (4, True, "gif"), (*lossy, 101), (*lossy, 49), (*lossy, 90.5),
                (*fidelity, -0.1), (*fidelity, 1.5), (*fidelity, float("nan")), (*fidelity, 0.0, "sideways"),
                (*fidelity, 0.0, "before", "sideways", 0), (*fidelity, 0.0, "before", "long_edge", 100),
                (*fidelity, 0.0, "before", "long_edge", 3840.5), (*fidelity, 0.0, "before", "print", 70000)]:
        try:
            validate_settings(*bad)
            raise AssertionError(f"accepted {bad}")
        except ValueError:
            pass

    # Stand-ins for GFPGAN and the model: every pixel of the paste is 200, of the plain upscale 100
    upscaled, pasted = np.full((2, 2, 3), 100, np.uint8), np.full((2, 2, 3), 200, np.uint8)
    quiet = SimpleNamespace(stage=lambda name: None)
    real_find_faces = upscaler_module.find_and_restore_faces
    try:
        for faces, fidelity, expected in ((2, 0.0, 200), (2, 0.25, 175), (2, 1.0, 100), (0, 0.5, 200)):
            upscaler_module.find_and_restore_faces = lambda face_enhancer, image, upscale_factor, faces=faces: faces
            enhancer, model = face_stand_ins(upscaled, lambda upsample_img: pasted)
            result, found = restore_faces(enhancer, None, model, 4, fidelity, config.FACE_PASS_BEFORE, quiet)
            assert found == faces and (result == expected).all(), f"fidelity {fidelity} mixes the upscale into faces"
        # Upscales the paste can't take as they are: 16-bit in steps finer than 8 bits allow, and greyscale
        fine_steps = np.arange(40000, 40008, dtype=np.uint16).reshape(2, 4)
        sixteen_bit_face, half_step = 200 * UINT16_PER_UINT8, UINT16_PER_UINT8 // 2
        cases = [("16-bit colour", fine_steps[:, :, None].repeat(3, axis=2), sixteen_bit_face, half_step),
                 ("16-bit greyscale", fine_steps, sixteen_bit_face, half_step),
                 ("8-bit greyscale", np.arange(50, 58, dtype=np.uint8).reshape(2, 4), 200, 0)]
        for kind, upscale, face, tolerance in cases:
            enhancer, model = face_stand_ins(upscale, paste_face_on_right_half)
            result, _ = restore_faces(enhancer, None, model, 4, 0.0, config.FACE_PASS_BEFORE, quiet)
            assert result.dtype == upscale.dtype and result.shape == upscale.shape, f"a {kind} upscale keeps its format"
            assert (result[:, :2] == upscale[:, :2]).all(), f"a {kind} upscale keeps every value outside the faces"
            assert (np.abs(result[:, 2:].astype(int) - face) <= tolerance).all(), f"a {kind} upscale gets its faces"

        steps = []

        def find_faces(face_enhancer, image, upscale_factor):
            steps.append(("faces in", image.shape, upscale_factor))
            return 1

        def upscale(image, outscale):
            steps.append("upscaled")
            return upscaled, None

        upscaler_module.find_and_restore_faces = find_faces
        enhancer, _ = face_stand_ins(upscaled, lambda upsample_img: pasted)
        original, progress = np.zeros((1, 1, 3), np.uint8), SimpleNamespace(stage=steps.append)
        restore_faces(enhancer, original, SimpleNamespace(enhance=upscale), 2, 0.0, config.FACE_PASS_BEFORE, progress)
        assert steps == [config.STAGE_FACES, ("faces in", original.shape, 2), "upscaled"], \
            "before upscaling, faces are found in the original and pasted back at the result's scale"
        steps.clear()
        restore_faces(enhancer, original, SimpleNamespace(enhance=upscale), 2, 0.0, config.FACE_PASS_AFTER, progress)
        assert steps == ["upscaled", config.STAGE_FACES, ("faces in", upscaled.shape, 1)], \
            "after upscaling, faces are found in the result and pasted back at its own size"
    finally:
        upscaler_module.find_and_restore_faces = real_find_faces
    assert detection_short_side((576, 1024)) is None, "faces in a small image are found at full size"
    assert detection_short_side((10928, 16384)) == 2732, "a big one is searched on a copy 4096 px wide"

    with tempfile.TemporaryDirectory() as root:
        root = Path(root)
        folders = [root / name for name in ("input", "output", "preview", "checkpoints")]
        for folder in folders:
            folder.mkdir()
        store = JobStore(root / "jobs.json", *folders)
        settings = validate_settings(2, False, "jpg")

        job = store.add("photo.png", settings, write_input=lambda path: Image.new("RGBA", (30, 20)).save(path))
        assert job["input_size"] == [30, 20] and store.preview_path(job).exists()
        assert job["taken"] is None and job["camera"] is None, "a photo without EXIF has no date taken or camera"
        assert job["status"] == config.STATUS_READY and store.pending.empty(), "adding a file must not start it"
        rerun = store.add("photo.png", settings, source_job=job)
        assert len(job["content_hash"]) == 64 and rerun["content_hash"] == job["content_hash"], "a re-run shares the hash"
        assert rerun["duplicate_of"] is None, "a re-run is a version, not a duplicate"
        assert store.input_path(rerun).exists()
        assert rerun["source_id"] == job["id"] and job["source_id"] is None, "a re-run must remember its source"
        own = validate_settings(8, False, "webp", "4xNomos8kSC", 0.5)
        assert store.set_settings(rerun["id"], own)["custom_settings"]
        global_settings = validate_settings(4, True, "png", "4x-UltraSharp", 0.3)
        started, refused = store.start(store.ready_ids(), global_settings)
        assert len(started) == 2 and not refused and store.pending.qsize() == 2
        places = {item["id"]: item["queue_position"] for item in store.all_jobs()}
        assert places[job["id"]] == 1 and places[rerun["id"]] == 2, "the oldest file is first in line"
        assert store.stop(job["id"]) and store.resume(job["id"])
        assert {item["id"]: item["queue_position"] for item in store.all_jobs()} == places, "stop and resume keep the place"
        assert store.get(job["id"])["model"] == "4x-UltraSharp", "Start applies the global settings at that moment"
        assert store.get(rerun["id"])["model"] == "4xNomos8kSC", "a file with its own settings keeps them"
        assert store.start([job["id"]], global_settings) == ([], []), "a started file can't be started twice"
        assert store.set_settings(job["id"], own) is None, "settings are locked once a file has started"
        assert store.rotate(job["id"], 1) is None, "orientation is locked once a file has started"
        try:
            store.add("fake.png", settings, write_input=lambda path: path.write_text("nope"))
            raise AssertionError("accepted a non-image")
        except ValueError:
            assert len(list((root / "input").glob("*"))) == 2, "rejected upload must be removed"

        (root / "output" / "junk.png").write_text("left behind")
        reloaded = JobStore(root / "jobs.json", *folders)
        assert not (root / "output" / "junk.png").exists(), "orphan files must be swept on start"
        assert reloaded.pending.qsize() == 2, "queued jobs must survive a restart"
        assert reloaded.get(rerun["id"])["source_id"] == job["id"], "the re-run link must survive a restart"
        renamed = reloaded.rename(job["id"], "  Grandpa 1998  ")
        assert renamed["name"] == "Grandpa 1998" and reloaded.input_path(renamed).exists(), "rename keeps the file"
        for bad_name in ["", "a/b", "x" * (config.NAME_MAX_LENGTH + 1)]:
            try:
                reloaded.rename(job["id"], bad_name)
                raise AssertionError(f"accepted name {bad_name!r}")
            except ValueError:
                pass
        assert reloaded.delete(job["id"]) and not store.input_path(job).exists()
        assert reloaded.all_jobs()[0]["status"] == config.STATUS_QUEUED

        queued = reloaded.get(rerun["id"])
        upscaler = StoppingUpscaler(reloaded)
        reloaded._process(upscaler, queued)
        assert queued["status"] == config.STATUS_STOPPED and queued["progress"] > 0
        assert reloaded.checkpoint_path(rerun["id"]).exists(), "Stop must keep the partial result on disk"
        reloaded = JobStore(root / "jobs.json", *folders)  # a container restart
        queued = reloaded.get(rerun["id"])
        assert queued["status"] == config.STATUS_STOPPED and queued["progress"] > 0, "a stopped file keeps its place"
        assert reloaded.resume(rerun["id"])
        reloaded._process(upscaler, queued)
        assert upscaler.started_at == [0, 2], "resume must continue from the stopped tile, also after a restart"
        assert queued["status"] == config.STATUS_DONE and queued["progress"] == 1.0
        assert queued["faces_found"] == StoppingUpscaler.FACES, "a finished run records the faces it found"
        assert not reloaded.checkpoint_path(rerun["id"]).exists(), "finished jobs must drop their checkpoint"
        speed = reloaded.speed_table(config.DEVICE_CPU)
        assert queued["device"] == config.DEVICE_CPU and speed["default"] > 0, "a finished run teaches the estimates"
        assert speed["by_settings"] == [], "one run is too few for a setting of its own"
        assert reloaded.speed_table(config.DEVICE_GPU)["default"] == config.ESTIMATE_FALLBACK_SECONDS_PER_MEGAPIXEL[
            config.DEVICE_GPU], "no runs on a device means the fallback"
        assert reloaded.result_preview_path(queued).exists(), "a finished job gets a light preview of its result"

        reloaded.rotate(rerun["id"], 1)
        assert queued["output_size"] == [4, 8] and queued["rotation"] == 1, "rotating a finished job turns the result"
        with Image.open(reloaded.result_preview_path(queued)) as preview:
            assert preview.size == (4, 8), "and its result preview"
        assert reloaded.clear_finished() == 1 and reloaded.get(rerun["id"])["cleared"]
        assert JobStore(root / "jobs.json", *folders).get(rerun["id"]), "Start new must keep processed files"
        assert reloaded.delete(rerun["id"])
        leftovers = [path for folder in folders for path in folder.iterdir()]
        assert leftovers == [], f"delete must leave nothing behind: {leftovers}"

        def camera_photo(path):
            exif = Image.Exif()
            exif[EXIF_ORIENTATION_TAG] = 6  # camera held sideways: needs one clockwise turn
            exif[EXIF_TAG_MAKE] = "TestCam"
            exif[EXIF_TAG_MODEL] = "TestCam X100"
            exif[EXIF_TAG_DATETIME] = "2014:08:27 11:28:30"  # last changed
            exif[EXIF_TAG_EXIF_IFD] = {EXIF_TAG_DATETIME_ORIGINAL: "2013:01:02 03:04:05"}  # taken
            srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
            Image.new("RGB", (30, 20)).save(path, "JPEG", exif=exif.tobytes(), icc_profile=srgb)

        sideways = store.add("camera.jpg", settings, write_input=camera_photo)
        assert sideways["rotation"] == 1 and sideways["input_size"] == [20, 30], "EXIF orientation must apply"
        assert sideways["taken"] == "2013-01-02T03:04:05", "date taken comes from DateTimeOriginal, as the camera's clock"
        assert sideways["camera"] == "TestCam X100", "make and model, with the brand said once"
        assert store.rotate(sideways["id"], 1)["input_size"] == [30, 20], "rotate must turn the preview"
        store.start([sideways["id"]], settings)
        assert store.stop(sideways["id"]) and store.get(sideways["id"])["status"] == config.STATUS_STOPPED
        restarted = store.set_settings(sideways["id"], validate_settings(3, False, "png"))
        assert restarted["status"] == config.STATUS_READY and restarted["custom_settings"], \
            "changing a stopped file's settings sends it back to Ready to start over"
        metadata = read_metadata(store.input_path(sideways))
        screen_photo = root / "screen.jpg"
        Image.new("RGB", (4, 4)).save(screen_photo, "JPEG", dpi=(72, 72))
        scaled = read_metadata(screen_photo, scale=4)
        assert scaled["dpi"] == (288, 288), "a result keeps the original's size on paper: 72 dpi at 4× is 288"
        for_print = read_metadata(screen_photo, scale=4, fixed_dpi=config.PRINT_DPI)
        assert for_print["dpi"] == (config.PRINT_DPI, config.PRINT_DPI), "a print target writes its own DPI"
        for suffix in (".png", ".jpg"):
            printed = root / f"printed{suffix}"
            write_image(printed, np.zeros((4, 6, 3), np.uint8), for_print)
            with Image.open(printed) as written:
                # PNG stores pixels per metre, so 300 dpi reads back as 299.9994
                assert tuple(round(value) for value in written.info["dpi"]) == (config.PRINT_DPI, config.PRINT_DPI)
                assert written.getexif().get(EXIF_TAG_X_RESOLUTION) == config.PRINT_DPI, "EXIF's resolution follows"
        assert "dpi" not in read_metadata(store.input_path(sideways), 4), "a photo without a DPI gets none"
        result = root / "result.png"
        write_image(result, np.zeros((4, 6, 3), np.uint8), metadata)
        big_preview = root / "big_result.jpg"
        write_result_preview(big_preview, np.full((1000, 3000, 3), 40000, np.uint16), metadata)
        with Image.open(big_preview) as preview:
            assert max(preview.size) == config.RESULT_PREVIEW_MAX_EDGE and preview.mode == "RGB", "previews are small and 8-bit"
            assert preview.info.get("icc_profile") == metadata["icc_profile"], "previews keep the colour profile"
        with Image.open(result) as written:
            assert written.info.get("icc_profile") == metadata["icc_profile"], "colour profile must be kept"
            assert written.getexif().get(EXIF_ORIENTATION_TAG) == 1, "orientation must be reset after rotating"
        printed_16_bit = {**metadata, "dpi": (config.PRINT_DPI, config.PRINT_DPI)}
        for suffix, depth, value in ((".png", np.uint16, 40000), (".jpg", np.uint8, round(40000 / UINT16_PER_UINT8))):
            sixteen_bit = root / f"sixteen_bit{suffix}"
            write_image(sixteen_bit, np.full((4, 6, 3), 40000, np.uint16), printed_16_bit)
            pixels = cv2.imread(str(sixteen_bit), cv2.IMREAD_UNCHANGED)
            assert pixels.dtype == depth and abs(int(pixels[0, 0, 0]) - value) <= 1, \
                f"a 16-bit result as {suffix} holds {pixels.dtype} {pixels[0, 0]}"
            with Image.open(sixteen_bit) as written:
                written.load()
                exif = written.getexif()
                assert written.info.get("icc_profile") == metadata["icc_profile"] and \
                    exif.get(EXIF_TAG_MODEL) == "TestCam X100" and exif.get(EXIF_ORIENTATION_TAG) == 1, \
                    f"a 16-bit result as {suffix} keeps its colour profile and EXIF"
                assert tuple(round(value) for value in written.info["dpi"]) == (config.PRINT_DPI, config.PRINT_DPI), \
                    f"and its DPI as {suffix}"
        noise = np.random.default_rng(0).integers(0, 256, (64, 64, 3), dtype=np.uint8)
        for suffix in (".jpg", ".webp"):
            low, high = root / f"low{suffix}", root / f"high{suffix}"
            write_image(low, noise, quality=config.MIN_QUALITY)
            write_image(high, noise, quality=config.DEFAULT_QUALITY)
            assert low.stat().st_size < high.stat().st_size, f"a lower quality must write a smaller {suffix}"

        odd = root / "odd.jpg"
        odd_exif = Image.Exif()
        odd_exif[EXIF_TAG_MAKE] = " Odd\x07Cam "
        odd_exif[EXIF_TAG_DATETIME] = "2014:08:27 11:28:30"
        odd_exif[EXIF_TAG_EXIF_IFD] = {EXIF_TAG_DATETIME_ORIGINAL: "0000:00:00 00:00:00"}
        Image.new("RGB", (4, 4)).save(odd, "JPEG", exif=odd_exif.tobytes())
        assert read_photo_info(odd) == {"taken": "2014-08-27T11:28:30", "camera": "Odd Cam"}, \
            "EXIF text is cleaned, and a placeholder date taken falls back to the last-changed date"
        odd.write_bytes(b"not an image")
        assert read_photo_info(odd) == {"taken": None, "camera": None}, "an unreadable file has no photo info"

        def red(path):
            Image.new("RGB", (5, 7), "red").save(path)

        first = store.add("dup.png", settings, write_input=red)
        size_before = store.library_bytes()
        again = store.add("dup (1).png", settings, write_input=red)
        assert first["duplicate_of"] is None and again["duplicate_of"] == first["id"], "the same bytes are the same photo"
        assert os.stat(store.input_path(again)).st_ino == os.stat(store.input_path(first)).st_ino, "and stored once"
        assert store.library_bytes() - size_before == store.preview_path(again).stat().st_size, \
            "an original shared by a hardlink counts once in the library's size"
        assert store.delete(first["id"])
        with Image.open(store.input_path(again)) as kept:
            assert kept.size == (5, 7), "removing the first photo keeps the duplicate's original"
        assert store.delete(again["id"])

        jobs_file = root / "jobs.json"
        saved_before_photo_info = [{key: value for key, value in saved.items() if key not in ("taken", "camera", "content_hash")}
                                   for saved in json.loads(jobs_file.read_text())]
        jobs_file.write_text(json.dumps(saved_before_photo_info))
        backfilled = JobStore(jobs_file, *folders).get(sideways["id"])
        assert backfilled["content_hash"] == sideways["content_hash"], "and their content hash"
        assert backfilled["taken"] == "2013-01-02T03:04:05" and backfilled["camera"] == "TestCam X100", \
            "jobs saved before photo info existed must read it from their original on start"
        assert all("taken" in saved for saved in json.loads(jobs_file.read_text())), "the backfill must be saved"

        config.PREFERENCES_FILE = root / "preferences.json"
        assert preferences.load()["defaults"] == preferences.ENV_DEFAULTS, "with nothing saved the env defaults apply"
        shared = validate_settings(2, True, "jpg", "4xNomos8kSC", 0.3, 80, 0.6, config.FACE_PASS_AFTER,
                                   config.TARGET_MODE_PRINT, 3543)
        assert preferences.save(defaults=shared)["defaults"] == shared
        assert preferences.load()["thumbnail_size"] == config.THUMBNAIL_DEFAULT, "saving defaults keeps the thumbnail size"
        assert preferences.save(thumbnail_size=300)["defaults"] == shared, "saving the thumbnail size keeps the defaults"
        stored = json.loads(config.PREFERENCES_FILE.read_text())
        stored["defaults"]["model"] = "a-model-since-removed"
        # As saved before the quality, face fidelity, face pass and fit-to settings existed
        for key in ("quality", "face_fidelity", "face_pass", "target_mode", "target_long_edge"):
            del stored["defaults"][key]
        config.PREFERENCES_FILE.write_text(json.dumps(stored))
        assert preferences.load()["defaults"] == {**shared, "model": config.DEFAULT_MODEL,
                                                  "quality": config.DEFAULT_QUALITY,
                                                  "face_fidelity": config.DEFAULT_FACE_FIDELITY,
                                                  "face_pass": config.DEFAULT_FACE_PASS,
                                                  "target_mode": config.DEFAULT_TARGET_MODE, "target_long_edge": 0}, \
            "a saved value that no longer validates, or is missing, falls back on its own"
        config.PREFERENCES_FILE.write_text("{not json")
        assert preferences.load()["defaults"] == preferences.ENV_DEFAULTS, "an unreadable file falls back to the env"

        assert available_ram_bytes() > 0, "RAM available comes from /proc/meminfo"
        config.MEMINFO_PATH = root / "missing-meminfo"
        assert available_ram_bytes() is None, "without /proc/meminfo, RAM available is unknown"
        assert store.engine_problem() is None, "an engine still loading is no problem"
        store.engine_error = "CUDA failed to start"
        assert store.engine_problem() == "CUDA failed to start", "a failed model load must be reported"
        store.engine_error, store.engine_ready = None, True
        store.worker = threading.Thread(target=lambda: None)
        store.worker.start()
        store.worker.join()
        assert store.engine_problem() == config.ERROR_WORKER_STOPPED, "a worker that died must be reported"

        half = config.TILE // config.TILE_RETRY_DIVISOR
        fits_at_half, never_fits = OutOfMemoryUpscaler(fits_at=half), OutOfMemoryUpscaler(fits_at=0)
        retried = store.add("big.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        hopeless = store.add("huge.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        with contextlib.redirect_stderr(io.StringIO()):  # the expected out-of-memory tracebacks
            store._process(fits_at_half, retried)
            store._process(never_fits, hopeless)
        assert retried["status"] == config.STATUS_DONE and retried["tile"] == half, "out of GPU memory retries at half the tile"
        assert fits_at_half.tiles == [config.TILE, half] and fits_at_half.releases == 1, "the card is freed before a retry"
        assert never_fits.tiles[-1] == config.MIN_TILE and hopeless["status"] == config.STATUS_ERROR
        assert hopeless["error"] == config.ERROR_OUT_OF_GPU_MEMORY.format(tile=config.MIN_TILE), "it gives up at MIN_TILE"

        twin = store.add("big.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        store._process(OutOfMemoryUpscaler(fits_at=config.TILE), twin)
        archive = zipfile.ZipFile(io.BytesIO(b"".join(store.outputs_zip([retried, twin]))))
        clash = f"big_upscaled_{twin['id'][:config.ZIP_ID_SUFFIX_LENGTH]}.jpg"
        assert archive.namelist() == ["big_upscaled.jpg", clash], "a name used twice in one zip gets part of the id"
        assert archive.read("big_upscaled.jpg") == store.output_path(retried).read_bytes(), "results go in as they are"
        twin["cleared"] = True
        assert twin["id"] not in {job["id"] for job in store.finished_jobs()}, "Download all is the queue list's files"
        assert [job["id"] for job in store.finished_jobs({twin["id"], "unknown"})] == [twin["id"]], \
            "a day page's files zip even once cleared, and an unknown id is skipped"

        paused = store.add("paused.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        for drop in (lambda: store.set_settings(paused["id"], settings), lambda: store.rotate(paused["id"], 1)):
            store._process(StoppingUpscaler(store), paused)
            assert store.checkpoint_path(paused["id"]).exists() and paused["progress"] > 0
            drop()
            assert not store.checkpoint_path(paused["id"]).exists(), "new settings or a rotation must drop the checkpoint"
        store.checkpoint_path(paused["id"]).write_bytes(b"not a checkpoint")
        with contextlib.redirect_stderr(io.StringIO()):  # the expected traceback of the damaged file
            assert store._load_checkpoint(paused) is None, "a damaged checkpoint means starting over"
        store.checkpoint_path(paused["id"]).unlink()
        store.checkpoint_dir = root / "missing"  # stands in for a full disk: the checkpoint cannot be written
        store._process(StoppingUpscaler(store), paused)
        assert paused["status"] == config.STATUS_STOPPED and paused["progress"] == 0.0, "an unsaved stop starts over"
        assert paused["error"].startswith(config.ERROR_CHECKPOINT_NOT_SAVED.partition("{")[0]), "and says so"

        store.result_preview_path(retried).unlink()
        assert store.result_preview(retried).exists(), "a missing preview is made from the result on request"
        stray = store.preview_dir / f".{'0' * 32}{config.TEMPORARY_SUFFIX}"
        stray.write_text("half-written")
        JobStore(root / "jobs.json", *folders)  # a restart
        assert store.result_preview_path(retried).exists(), "a restart keeps the result previews"
        assert not stray.exists(), "and sweeps half-written leftovers"

        assert strip_crop((1000, 2000), 0.5, 0.5, 4) == [872, 372, 256, 256], "a strip crop makes a 1024 px result"
        assert strip_crop((1000, 2000), 1.0, 0.0, 8) == [1872, 0, 128, 128], "and stays inside the photo"
        assert strip_crop((100, 50), 0.5, 0.5, 2) == [0, 0, 50, 100], "a photo smaller than the crop is taken whole"
        pictured = store.add("strip.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        for bad in [(1.5, 0.5, 4, 0.5), (0.5, float("nan"), 4, 0.5), (0.5, 0.5, 9, 0.5), (0.5, 0.5, 4, 2)]:
            try:
                store.request_strip(pictured["id"], *bad)
                raise AssertionError(f"accepted strip {bad}")
            except ValueError:
                pass
        asked = store.request_strip(pictured["id"], 0.5, 0.5, 4, 0.5)
        assert asked["strip"]["status"] == config.STRIP_STATUS_PENDING
        assert store.pending.queue[-1] is jobs.STRIP_WAKE_UP, "a strip wakes an idle worker"
        restarted_store = JobStore(root / "jobs.json", *folders)
        assert restarted_store.strips.get_nowait() == pictured["id"], "a strip asked for before a restart still runs"
        store.run_strips(StripUpscaler())
        strip = store.get(pictured["id"])["strip"]
        assert strip["status"] == config.STRIP_STATUS_DONE and strip["keys"][0] == config.STRIP_ORIGINAL_KEY
        assert all(store.strip_path(pictured["id"], key).exists() for key in strip["keys"]), "one image per model"
        JobStore(root / "jobs.json", *folders)  # a restart
        assert store.strip_path(pictured["id"], config.STRIP_ORIGINAL_KEY).exists(), "a restart keeps strip images"
        strip_files = f"{pictured['id']}{config.STRIP_FILE_INFIX}*"
        store.rotate(pictured["id"], 1)
        assert store.get(pictured["id"])["strip"] is None and not list(store.preview_dir.glob(strip_files)), \
            "rotating drops the strip, whose spot no longer matches"
        store.request_strip(pictured["id"], 0.2, 0.2, 4, 0.5)
        store.run_strips(StripUpscaler(meanwhile=lambda: store.request_strip(pictured["id"], 0.8, 0.8, 4, 0.5)))
        strip = store.get(pictured["id"])["strip"]
        assert strip["x"] == 0.8 and strip["status"] == config.STRIP_STATUS_DONE, "a strip asked again runs anew"
        running = store.add("running.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        store.start([running["id"]], settings)
        store.request_strip(pictured["id"], 0.5, 0.5, 4, 0.5)
        two_tiles = TwoTileUpscaler(store, pictured["id"])
        store._process(two_tiles, running)
        assert two_tiles.strip_ran_mid_job and running["status"] == config.STATUS_DONE, \
            "a strip asked for during a job runs between its tiles"
        assert store.delete(pictured["id"]) and not list(store.preview_dir.glob(strip_files)), "Remove drops them"

        small = store.add("small.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        wide = store.add("wide.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
        wide["input_size"] = [2100, 100]  # stands in for a wide scan: 16800 px across at 8×
        started, refused = store.start([small["id"], wide["id"]], validate_settings(8, False, "webp"))
        assert [job["id"] for job in started] == [small["id"]] and wide["status"] == config.STATUS_READY
        assert wide["error"] == config.ERROR_TOO_WIDE_FOR_FORMAT.format(width=16800, height=800, format="WEBP",
                                                                       limit=config.WEBP_MAX_EDGE), "too wide for WebP"
        assert refused == [{"id": wide["id"], "name": "wide.png", "problems": [wide["error"]]}]
        png = validate_settings(8, False, "png")
        assert store.preflight(wide, png) == [], "the same file fits as PNG"
        assert validate_settings(4, True, "png", target_long_edge=999)["target_long_edge"] == 0, \
            "a long edge means nothing while the scale is set directly"
        fit_edge = validate_settings(2, False, "png", target_mode=config.TARGET_MODE_LONG_EDGE, target_long_edge=256)
        photos = {size: store.add(f"{size[0]}px.png", settings, write_input=lambda path, size=size: Image.new(
            "RGB", size).save(path)) for size in ((64, 48), (300, 200), (30, 20))}
        started, refused = store.start([job["id"] for job in photos.values()], fit_edge)
        assert photos[(64, 48)]["scale"] == 4.0, "a 64 px photo gets 4× to reach a 256 px long edge"
        assert photos[(30, 20)]["scale"] == config.MAX_SCALE, "one too small for the target gets the most there is"
        big_enough = photos[(300, 200)]
        assert big_enough["status"] == config.STATUS_READY and big_enough["error"] == \
            config.ERROR_ALREADY_BIG_ENOUGH.format(name="300px.png", edge=300, target=256), "no upscale needed"
        assert [job["id"] for job in refused] == [big_enough["id"]]
        real_ram, real_disk = jobs.available_ram_bytes, jobs.free_disk_bytes
        jobs.available_ram_bytes, jobs.free_disk_bytes = (lambda: config.KIBIBYTE), (lambda path: config.KIBIBYTE)
        try:
            short = store.preflight(wide, png)
        finally:
            jobs.available_ram_bytes, jobs.free_disk_bytes = real_ram, real_disk
        assert len(short) == 2 and short[0].startswith(config.ERROR_NOT_ENOUGH_RAM.partition("{")[0]) \
            and short[1].startswith(config.ERROR_NOT_ENOUGH_DISK.partition("{")[0]), "short of RAM and disk"

        assert Image.MAX_IMAGE_PIXELS * config.PILLOW_BOMB_ERROR_FACTOR == config.MAX_INPUT_MEGAPIXELS * config.PIXELS_PER_MEGAPIXEL
        bomb = Image.DecompressionBombError(
            "Image size (441000000 pixels) exceeds limit of 400000000 pixels, could be decompression bomb DOS attack.")
        assert too_many_pixels("scan.tif", bomb) == "scan.tif is 441 MP; the limit is 400 MP"
        pixel_limit, Image.MAX_IMAGE_PIXELS = Image.MAX_IMAGE_PIXELS, 100  # makes a 30×20 file too big
        try:
            store.add("too-big.png", settings, write_input=lambda path: Image.new("RGB", (30, 20)).save(path))
            raise AssertionError("accepted an image over the pixel limit")
        except ValueError as error:
            assert str(error).endswith(f"the limit is {config.MAX_INPUT_MEGAPIXELS} MP"), "an oversized scan says why"
        finally:
            Image.MAX_IMAGE_PIXELS = pixel_limit
    check_inbox()
    check_heif()
    check_custom_models()
    check_tiff_metadata_and_sixteen_bit_preview()
    check_batch()
    check_orientations()
    print("ok")


if __name__ == "__main__":
    main()
