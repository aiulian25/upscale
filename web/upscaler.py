"""Upscaling models + GFPGAN inference, models loaded on first use and reused across jobs."""
import gc
import math
import os
import traceback

import cv2
import numpy as np
import torch
from basicsr.utils import img2tensor, tensor2img
from realesrgan import RealESRGANer
from spandrel import ModelLoader
from torchvision.transforms.functional import normalize

import config
from custom_models import UnusableModelError, all_models, load_custom_model
from images import UINT16_PER_UINT8, read_image, read_metadata, rotate, write_image, write_result_preview

HAS_GPU = torch.cuda.is_available()
DEVICE = config.DEVICE_GPU if HAS_GPU else config.DEVICE_CPU
# Denoise values are cached per model instance, so round them to keep that cache small
DENOISE_CACHE_STEP = 0.05

if not HAS_GPU:
    # Leave cores free so the desktop stays responsive during long CPU runs
    torch.set_num_threads(max(1, (os.cpu_count() or 1) - config.CPU_CORES_RESERVED))


def device_name():
    if HAS_GPU:
        return f"GPU · {torch.cuda.get_device_name(0)}"
    return f"CPU · {os.cpu_count()} threads"


def gpu_memory():
    """Bytes in use and in total on the GPU, counting every process on the card; (None, None) on CPU or if CUDA fails."""
    if not HAS_GPU:
        return None, None
    try:
        free, total = torch.cuda.mem_get_info()
    except RuntimeError:
        return None, None
    return total - free, total


def _state_dict(url):
    state = torch.load(config.WEIGHTS_DIR / url.rsplit("/", 1)[-1], map_location="cpu", weights_only=True)
    return state.get("params_ema") or state.get("params") or state


def load_model(model_key, model, denoise):
    """Any supported architecture (ESRGAN, RRDB, compact…) via spandrel; two files are blended by denoise."""
    if "file" in model:
        return load_custom_model(model_key, model["file"])
    urls = model["urls"]
    state = _state_dict(urls[0])
    if len(urls) > 1:
        without_denoise = _state_dict(urls[1])
        state = {key: denoise * value + (1 - denoise) * without_denoise[key] for key, value in state.items()}
    return ModelLoader().load_from_state_dict(state)


class TrackedRealESRGANer(RealESRGANer):
    """Tiled upscaler that reports progress, can stop between tiles and resume from a checkpoint.

    The merged output lives in RAM instead of VRAM, so large results no longer run the GPU out of memory.
    `progress` is set before every run.
    """

    progress = None

    def __init__(self, descriptor):
        # RealESRGANer.__init__ loads weights itself and only knows its own architectures; spandrel did that
        half = HAS_GPU and descriptor.supports_half
        self.scale = descriptor.scale
        self.tile_size, self.tile_pad, self.pre_pad = config.TILE, config.TILE_PAD, 0
        self.mod_scale = None
        self.half = half
        self.device = torch.device("cuda" if HAS_GPU else "cpu")
        self.model = descriptor.model.eval().to(self.device)
        if half:
            self.model = self.model.half()
        # Tiles go through spandrel, which pads one to the size some architectures need and crops the result
        self.descriptor = descriptor

    def enhance(self, img, outscale=None, alpha_upsampler="cv2"):
        # cv2 resizes the alpha channel; the default would run a second full model pass for it
        if not outscale or outscale <= self.scale:
            self.progress.span(0.0, 1.0)
            return super().enhance(img, outscale, alpha_upsampler)
        # Past the model's native scale a second model pass adds real detail instead of stretching pixels
        height, width = img.shape[:2]
        second_scale = outscale / self.scale
        first_share = 1 / (1 + second_scale ** 2)
        self.progress.span(0.0, first_share)
        upscaled, _ = super().enhance(img, None, alpha_upsampler)
        intermediate = cv2.resize(upscaled, (round(width * second_scale), round(height * second_scale)),
                                  interpolation=cv2.INTER_AREA)
        self.progress.span(first_share, 1.0)
        output, mode = super().enhance(intermediate, None, alpha_upsampler)
        target_size = (int(width * outscale), int(height * outscale))
        if (output.shape[1], output.shape[0]) != target_size:
            output = cv2.resize(output, target_size, interpolation=cv2.INTER_LANCZOS4)
        return output, mode

    def tile_process(self):
        batch, channel, height, width = self.img.shape
        scale, size, pad = self.scale, self.tile_size, self.tile_pad
        output_shape = (batch, channel, height * scale, width * scale)
        tiles_x = math.ceil(width / size)
        total = tiles_x * math.ceil(height / size)
        next_tile, saved = self.progress.resume(output_shape) or (0, None)
        # A resumed partial result comes back from disk as a numpy array
        output = (torch.zeros(output_shape, dtype=self.img.dtype) if saved is None
                  else torch.from_numpy(saved).to(self.img.dtype))

        for index in range(next_tile, total):
            self.progress.tile(index, total, output)
            row, column = divmod(index, tiles_x)
            left, top = column * size, row * size
            right, bottom = min(left + size, width), min(top + size, height)
            padded_left, padded_top = max(left - pad, 0), max(top - pad, 0)
            padded_right, padded_bottom = min(right + pad, width), min(bottom + pad, height)
            with torch.no_grad():
                upscaled = self.descriptor(self.img[:, :, padded_top:padded_bottom, padded_left:padded_right])
            crop_top, crop_left = (top - padded_top) * scale, (left - padded_left) * scale
            output[:, :, top * scale:bottom * scale, left * scale:right * scale] = upscaled[
                :, :, crop_top:crop_top + (bottom - top) * scale, crop_left:crop_left + (right - left) * scale].cpu()
        self.progress.tile(total, total, output)
        self.output = output


def to_eight_bit(image):
    """The image in 8-bit values, which is all GFPGAN and its paste take; an 8-bit image comes back as it is."""
    if image.dtype != np.uint16:
        return image
    return cv2.convertScaleAbs(image, alpha=1 / UINT16_PER_UINT8)


def detection_short_side(size):
    """facexlib's detector resize: the short side of a copy whose long side is FACE_DETECT_MAX_EDGE, or None."""
    shrink = max(size) / config.FACE_DETECT_MAX_EDGE
    if shrink <= 1:
        return None
    return min(size) / shrink


def restore_face(face_enhancer, cropped_face):
    """GFPGAN on one aligned face, the way GFPGANer.enhance runs it."""
    face = img2tensor(cropped_face / np.iinfo(np.uint8).max, bgr2rgb=True, float32=True)
    normalize(face, config.FACE_TENSOR_MEAN, config.FACE_TENSOR_STD, inplace=True)
    with torch.no_grad():
        restored = face_enhancer.gfpgan(face.unsqueeze(0).to(face_enhancer.device), return_rgb=False)[0]
    return tensor2img(restored.squeeze(0), rgb2bgr=True, min_max=config.FACE_TENSOR_RANGE)


def find_and_restore_faces(face_enhancer, image, upscale_factor):
    """Finds and restores every face in the image; the faces wait in the face helper to be pasted back.

    Detection runs on a copy at most FACE_DETECT_MAX_EDGE px wide, which bounds its VRAM, and the faces are cut from
    the full image. Returns how many were found.
    """
    helper = face_enhancer.face_helper
    helper.clean_all()
    helper.set_upscale_factor(upscale_factor)
    helper.read_image(to_eight_bit(image))
    helper.get_face_landmarks_5(resize=detection_short_side(image.shape[:2]),
                                eye_dist_threshold=config.FACE_MIN_EYE_DISTANCE)
    helper.align_warp_face()
    for cropped_face in helper.cropped_faces:
        helper.add_restored_face(restore_face(face_enhancer, cropped_face))
    return len(helper.cropped_faces)


def paste_onto_eight_bit(face_helper, image):
    """facexlib's paste onto an 8-bit image, grey or colour.

    The paste only takes colour, so a greyscale image goes in as colour and comes back grey.
    """
    if image.ndim == 3:
        return face_helper.paste_faces_to_input_image(upsample_img=image)
    pasted = face_helper.paste_faces_to_input_image(upsample_img=cv2.cvtColor(image, cv2.COLOR_GRAY2BGR))
    return cv2.cvtColor(pasted, cv2.COLOR_BGR2GRAY)


def paste_faces(face_helper, upscaled):
    """Pastes the restored faces onto the upscale, which keeps its bit depth and channels.

    facexlib's paste only takes 8-bit colour, so GFPGAN's 8-bit faces came out black on a 16-bit upscale and a
    greyscale one failed outright. A 16-bit upscale gets the faces pasted onto an 8-bit copy, and only what the paste
    changed is carried back, so every value outside the faces keeps its 16 bits.
    """
    eight_bit = to_eight_bit(upscaled)
    pasted = paste_onto_eight_bit(face_helper, eight_bit)
    if upscaled.dtype != np.uint16:
        return pasted
    change = cv2.subtract(pasted, eight_bit, dtype=cv2.CV_16S)
    return cv2.addWeighted(upscaled, 1, change, UINT16_PER_UINT8, 0, dtype=cv2.CV_16U)


def restore_faces(face_enhancer, image, background, scale, fidelity, face_pass, progress):
    """GFPGAN on every face, pasted onto the model's upscale; fidelity mixes the plain upscale back into the faces.

    Faces are found in the original before upscaling, or in the upscaled result after it, which also finds faces too
    small in the original. Returns the result and how many faces were found.
    """
    if face_pass == config.FACE_PASS_AFTER:
        upscaled, _ = background.enhance(image, outscale=scale)
        progress.stage(config.STAGE_FACES)
        faces = find_and_restore_faces(face_enhancer, upscaled, upscale_factor=1)
    else:
        progress.stage(config.STAGE_FACES)
        faces = find_and_restore_faces(face_enhancer, image, upscale_factor=scale)
        upscaled, _ = background.enhance(image, outscale=scale)
    face_enhancer.face_helper.get_inverse_affine(None)
    restored = paste_faces(face_enhancer.face_helper, upscaled)
    # The paste was the image's last use; after upscaling it is the whole result, kept until the next face job
    face_enhancer.face_helper.input_img = None
    if not fidelity or not faces:
        return restored, faces
    # The two only differ where faces were pasted
    return cv2.addWeighted(upscaled, fidelity, restored, 1 - fidelity, 0), faces


class StripProgress:
    """What a test strip hands the model: nothing to report, stop or resume."""

    def span(self, start, end):
        pass

    def stage(self, name):
        pass

    def resume(self, output_shape):
        return None

    def tile(self, next_tile, total, output):
        pass


def strip_crop(size, x, y, scale):
    """The test strip's crop around the spot (x, y), given as shares of the width and height.

    It is sized for a result about STRIP_OUTPUT_EDGE px wide, at most one tile, and kept inside the image.
    Returns [left, top, width, height].
    """
    height, width = size
    edge = min(config.TILE, round(config.STRIP_OUTPUT_EDGE / scale))
    crop_width, crop_height = min(edge, width), min(edge, height)
    left = min(max(round(x * width - crop_width / 2), 0), width - crop_width)
    top = min(max(round(y * height - crop_height / 2), 0), height - crop_height)
    return [left, top, crop_width, crop_height]


def write_strip(path, image):
    """One test strip image, as a JPEG; a 16-bit crop is brought down to 8 bits, which is all the page shows."""
    write_image(path, to_eight_bit(image), quality=config.STRIP_QUALITY)


class Upscaler:
    device = DEVICE

    def __init__(self):
        self.models = {}
        # A test strip can run between two tiles of a job, so it gets wrappers of its own: a wrapper keeps its run's
        # image and output on itself. Both share the loaded models.
        self.backgrounds = {}
        self.strip_backgrounds = {}
        self.face_enhancer = None
        self._background(config.DEFAULT_MODEL, config.DEFAULT_DENOISE, self.backgrounds)

    def _background(self, model_key, denoise, wrappers):
        model = all_models().get(model_key)
        if model is None:
            raise UnusableModelError(model_key, config.MODEL_GONE)
        has_denoise = len(model["urls"]) > 1
        denoise = round(denoise / DENOISE_CACHE_STEP) * DENOISE_CACHE_STEP if has_denoise else None
        key = (model_key, denoise)
        if key not in self.models:
            self.models[key] = load_model(model_key, model, denoise)
        if key not in wrappers:
            wrappers[key] = TrackedRealESRGANer(self.models[key])
        return wrappers[key]

    def _face_enhancer(self):
        if self.face_enhancer is None:
            from gfpgan import GFPGANer
            self.face_enhancer = GFPGANer(model_path=config.GFPGAN_URL, arch="clean", channel_multiplier=2)
        return self.face_enhancer

    def release_memory(self):
        """Frees what a failed run left on the GPU, so a retry with smaller tiles starts from a clean card."""
        # The wrappers keep the last input image on the GPU until their next run
        for background in (*self.backgrounds.values(), *self.strip_backgrounds.values()):
            background.img = background.output = None
        gc.collect()
        if HAS_GPU:
            torch.cuda.empty_cache()

    def run(self, source_path, target_path, progress, scale, face_enhance, face_fidelity, face_pass, rotation, mirrored,
            model, denoise, quality, tile, preview_path=None, print_dpi=None):
        """Upscales one file; returns the result's width and height, and the faces found (None with faces off)."""
        image = cv2.imread(str(source_path), cv2.IMREAD_UNCHANGED)
        if image is None:
            raise ValueError("Not a readable image")
        image = rotate(image, rotation, mirrored)
        background = self._background(model, denoise, self.backgrounds)
        background.progress = progress
        background.tile_size = tile
        faces_found = None
        if face_enhance:
            output, faces_found = restore_faces(self._face_enhancer(), image, background, scale, face_fidelity,
                                                face_pass, progress)
        else:
            output, _ = background.enhance(image, outscale=scale)
        progress.stage(config.STAGE_SAVING)
        metadata = read_metadata(source_path, scale, print_dpi)
        write_image(target_path, output, metadata, quality)
        # Batch mode has no page to show a preview on
        if preview_path is None:
            return output.shape[1], output.shape[0], faces_found
        # The result is safe on disk; a preview that fails here is made again when a page asks for it
        try:
            write_result_preview(preview_path, output, metadata)
        except Exception:
            traceback.print_exc()
        return output.shape[1], output.shape[0], faces_found

    def run_strip(self, source_path, rotation, mirrored, strip, path_for):
        """Upscales the strip's crop with every model, without face restore, writing each image to path_for(key).

        Returns the crop as [left, top, width, height] and the keys of the images written, the original first.
        """
        image = rotate(read_image(source_path), rotation, mirrored)
        crop_box = strip_crop(image.shape[:2], strip["x"], strip["y"], strip["scale"])
        left, top, width, height = crop_box
        crop = np.ascontiguousarray(image[top:top + height, left:left + width])
        write_strip(path_for(config.STRIP_ORIGINAL_KEY), crop)
        model_keys = list(all_models())
        for model_key in model_keys:
            wrapper = self._background(model_key, strip["denoise"], self.strip_backgrounds)
            wrapper.progress = StripProgress()
            output, _ = wrapper.enhance(crop, outscale=strip["scale"])
            write_strip(path_for(model_key), output)
        return crop_box, [config.STRIP_ORIGINAL_KEY, *model_keys]
