"""Image file helpers shared by the job store and the upscaler (no torch here)."""
import hashlib
import math
import shutil
import struct
import uuid
import warnings
import zlib
from datetime import datetime

import cv2
import numpy as np
from PIL import ExifTags, Image

import config

# Big scans open (above this Pillow only warns); anything over MAX_INPUT_MEGAPIXELS is refused with its real size
Image.MAX_IMAGE_PIXELS = config.PILLOW_MAX_IMAGE_PIXELS
warnings.simplefilter("ignore", Image.DecompressionBombWarning)

QUARTER_TURNS = 4
# 65535 / 255: one 8-bit step in 16-bit values
UINT16_PER_UINT8 = 257
EXIF_ORIENTATION_TAG = 0x0112
EXIF_ORIENTATION_UPRIGHT = 1
# What shows a photo upright, by EXIF orientation, as PIL.ImageOps.exif_transpose does: whether to mirror it left to
# right first, then how many quarter turns clockwise
EXIF_ORIENTATION_TRANSFORMS = {2: (True, 0), 3: (False, 2), 4: (True, 2), 5: (True, 3), 6: (False, 1), 7: (True, 1),
                               8: (False, 3)}
UPRIGHT_TRANSFORM = (False, 0)
EXIF_TAG_DATETIME = 0x0132
EXIF_TAG_MAKE = 0x010F
EXIF_TAG_MODEL = 0x0110
EXIF_TAG_EXIF_IFD = 0x8769
EXIF_TAG_DATETIME_ORIGINAL = 0x9003
EXIF_TAG_X_RESOLUTION = 0x011A
EXIF_TAG_Y_RESOLUTION = 0x011B
EXIF_TAG_RESOLUTION_UNIT = 0x0128
EXIF_RESOLUTION_UNIT_INCH = 2
# JFIF density units that give a real DPI: dots per inch and per centimetre (0 only gives the aspect ratio)
JFIF_DPI_UNITS = (1, 2)
JPEG_FORMAT = "JPEG"
TIFF_FORMAT = "TIFF"
# A TIFF's EXIF is its whole image directory: only these tags describe the photo rather than how the file stores it
TIFF_PHOTO_TAGS = {ExifTags.Base.ImageDescription, ExifTags.Base.Make, ExifTags.Base.Model, ExifTags.Base.Orientation,
                   ExifTags.Base.XResolution, ExifTags.Base.YResolution, ExifTags.Base.ResolutionUnit,
                   ExifTags.Base.Software, ExifTags.Base.DateTime, ExifTags.Base.Artist, ExifTags.Base.Copyright,
                   ExifTags.IFD.Exif, ExifTags.IFD.GPSInfo}
EXIF_DATETIME_FORMAT = "%Y:%m:%d %H:%M:%S"
# Real camera names are far shorter; EXIF text is untrusted and can run to kilobytes
CAMERA_NAME_MAX_LENGTH = 80
PIL_FORMATS = {".png": "PNG", ".jpg": "JPEG", ".webp": "WEBP"}
# 16-bit PNG results are written by OpenCV, which adds no metadata: its chunks go in by hand, right after the header
# (the 8-byte signature, then IHDR's length, type, 13 bytes of data and CRC)
PNG_HEADER_BYTES = 33
PNG_ICC_PROFILE_NAME = b"ICC Profile"
PNG_ZLIB_METHOD = b"\x00"
PNG_UNIT_METRE = 1
EXIF_HEADER = b"Exif\x00\x00"
METRES_PER_INCH = 0.0254
PIL_MODES = {2: "L", 3: "RGB", 4: "RGBA"}


def content_hash(path):
    """The file's SHA-256 as hex: two uploads with the same bytes are the same photo."""
    with path.open("rb") as file:
        return hashlib.file_digest(file, config.CONTENT_HASH_ALGORITHM).hexdigest()


def rotate(image, turns, mirrored=False):
    """Mirrors an OpenCV/numpy image left to right when asked, then rotates it clockwise by quarter turns."""
    if mirrored:
        image = image[:, ::-1]
    return np.ascontiguousarray(np.rot90(image, -(turns % QUARTER_TURNS)))


def exif_transform(path):
    """Whether the camera asked via EXIF for the photo to be mirrored, and the clockwise quarter turns after that: the
    job's starting orientation."""
    with Image.open(path) as image:
        orientation = image.getexif().get(EXIF_ORIENTATION_TAG, EXIF_ORIENTATION_UPRIGHT)
    return EXIF_ORIENTATION_TRANSFORMS.get(orientation, UPRIGHT_TRANSFORM)


def _exif_text(value):
    """Untrusted EXIF text as one clean line: control characters become spaces, runs of spaces collapse."""
    if not isinstance(value, str):
        return ""
    return " ".join("".join(character if character.isprintable() else " " for character in value).split())


def _camera_name(make, model):
    """Make and model with the brand said once: SAMSUNG GT-I9152, Canon EOS R5, NIKON D750."""
    brand = make.split(" ", 1)[0]
    if brand and model.lower().startswith(brand.lower()):
        make = ""
    return " ".join(part for part in (make, model) if part)[:CAMERA_NAME_MAX_LENGTH] or None


def _camera_time(value):
    """The camera's own clock as ISO 8601 without a zone: EXIF records none, and guessing one shifts the day."""
    try:
        return datetime.strptime(_exif_text(value), EXIF_DATETIME_FORMAT).isoformat()
    except ValueError:
        return None


def read_photo_info(path):
    """When the photo was taken and with which camera, from EXIF; None for anything missing or unreadable."""
    try:
        with Image.open(path) as image:
            exif = image.getexif()
            # A corrupt pointer makes Pillow return None for this block instead of a dict
            details = exif.get_ifd(EXIF_TAG_EXIF_IFD) or {}
            original, changed = details.get(EXIF_TAG_DATETIME_ORIGINAL), exif.get(EXIF_TAG_DATETIME)
            make, model = exif.get(EXIF_TAG_MAKE), exif.get(EXIF_TAG_MODEL)
    # EXIF is optional, untrusted metadata and Pillow raises many error types on damaged blocks:
    # none of them may block an upload or the start-up backfill
    except Exception:
        return {"taken": None, "camera": None}
    return {"taken": _camera_time(original) or _camera_time(changed),
            "camera": _camera_name(_exif_text(make), _exif_text(model))}


def declared_dpi(image, exif):
    """The DPI the file itself states. Pillow reports 72 for a JPEG that states none, and 1 for such a TIFF: both are
    left out."""
    states_resolution = EXIF_TAG_X_RESOLUTION in exif
    guessed_for_jpeg = image.format == JPEG_FORMAT and image.info.get("jfif_unit") not in JFIF_DPI_UNITS
    guessed_for_tiff = image.format == TIFF_FORMAT
    guessed = (guessed_for_jpeg or guessed_for_tiff) and not states_resolution
    return None if guessed else image.info.get("dpi")


def result_dpi(original_dpi, scale, fixed_dpi=None):
    """The result's DPI: fixed_dpi for a print target, else the original's times the scale, which keeps the photo's
    size on paper. None when the original has no usable DPI."""
    if fixed_dpi:
        return fixed_dpi, fixed_dpi
    usable = bool(original_dpi) and all(value > 0 and math.isfinite(value) for value in original_dpi)
    if not usable:
        return None
    return tuple(round(value * scale) for value in original_dpi)


def _keep_photo_tags(exif):
    """Drops a TIFF's layout (size, strips, compression, its colour profile as a tag): none of it describes a result."""
    for tag in [tag for tag in exif if tag not in TIFF_PHOTO_TAGS]:
        del exif[tag]


def read_metadata(path, scale=1, fixed_dpi=None):
    """Colour profile, EXIF (date, camera…) and DPI to carry over to a result made at this scale.

    The orientation tag is reset because rotation is applied to the pixels, and EXIF's resolution tags follow the DPI.
    """
    with Image.open(path) as image:
        exif = image.getexif()
        icc_profile = image.info.get("icc_profile")
        dpi = result_dpi(declared_dpi(image, exif), scale, fixed_dpi)
        if image.format == TIFF_FORMAT:
            _keep_photo_tags(exif)
        if EXIF_ORIENTATION_TAG in exif:
            exif[EXIF_ORIENTATION_TAG] = EXIF_ORIENTATION_UPRIGHT
        if dpi:
            exif[EXIF_TAG_X_RESOLUTION], exif[EXIF_TAG_Y_RESOLUTION] = dpi
            exif[EXIF_TAG_RESOLUTION_UNIT] = EXIF_RESOLUTION_UNIT_INCH
        # While the file is open: a TIFF's EXIF and GPS blocks are read from it only now
        exif_bytes = exif.tobytes() if exif else None
    metadata = {"icc_profile": icc_profile, "exif": exif_bytes, "dpi": dpi}
    return {key: value for key, value in metadata.items() if value}


def eight_bit_grey(image):
    """A 16-bit greyscale image brought down to 8 bits the way results are; any other image as it is.

    Values outside 16 bits, which a 32-bit TIFF can hold, end at black or white rather than wrapping around.
    """
    if image.mode not in config.SIXTEEN_BIT_GREY_MODES:
        return image
    eight_bit_max = np.iinfo(np.uint8).max
    scaled = np.clip((np.asarray(image) / UINT16_PER_UINT8).round(), 0, eight_bit_max)
    return Image.fromarray(scaled.astype(np.uint8))


def _to_pil(image, suffix):
    channels = 2 if image.ndim == 2 else image.shape[2]
    if channels == 4 and suffix == ".jpg":
        image, channels = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR), 3
    conversions = {3: cv2.COLOR_BGR2RGB, 4: cv2.COLOR_BGRA2RGBA}
    if channels in conversions:
        image = cv2.cvtColor(image, conversions[channels])
    return Image.fromarray(image, PIL_MODES[channels])


def _png_chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))


def add_png_metadata(path, metadata):
    """Writes the colour profile, EXIF and DPI into a PNG that has none, right after its header."""
    chunks = []
    icc_profile, exif, dpi = metadata.get("icc_profile"), metadata.get("exif"), metadata.get("dpi")
    if icc_profile:
        profile = PNG_ICC_PROFILE_NAME + b"\x00" + PNG_ZLIB_METHOD + zlib.compress(icc_profile)
        chunks.append(_png_chunk(b"iCCP", profile))
    if exif:
        chunks.append(_png_chunk(b"eXIf", exif.removeprefix(EXIF_HEADER)))
    if dpi:
        per_metre = [round(value / METRES_PER_INCH) for value in dpi]
        chunks.append(_png_chunk(b"pHYs", struct.pack(">IIB", *per_metre, PNG_UNIT_METRE)))
    if not chunks:
        return
    # Copied through a file beside it rather than read whole: a 16-bit result can run to gigabytes
    temporary = path.with_name(path.name + config.TEMPORARY_SUFFIX)
    with path.open("rb") as original, temporary.open("wb") as copy:
        copy.write(original.read(PNG_HEADER_BYTES))
        copy.writelines(chunks)
        shutil.copyfileobj(original, copy)
    temporary.replace(path)


def write_image(target_path, image, metadata=None, quality=config.DEFAULT_QUALITY):
    suffix = target_path.suffix
    sixteen_bit = image.dtype != np.uint8
    if sixteen_bit and suffix == ".png":
        # Pillow can't write 16-bit colour: OpenCV writes the pixels, and the metadata goes in after
        if not cv2.imwrite(str(target_path), image):
            raise OSError(f"Could not write {suffix}")
        add_png_metadata(target_path, metadata or {})
        return
    # JPG and WebP hold 8 bits: brought down the way previews are, instead of OpenCV clipping everything to white
    if sixteen_bit:
        image = (image / UINT16_PER_UINT8).round().astype(np.uint8)
    options = {
        ".png": {"compress_level": config.PNG_COMPRESS_LEVEL},
        ".jpg": {"quality": quality, "subsampling": config.JPEG_SUBSAMPLING_NONE},
        ".webp": {"quality": quality},
    }[suffix]
    try:
        _to_pil(image, suffix).save(target_path, PIL_FORMATS[suffix], **options, **(metadata or {}))
    except (OSError, ValueError) as error:
        target_path.unlink(missing_ok=True)
        raise OSError(f"Could not write {suffix} (WebP tops out at 16383 px; try PNG)") from error


def read_image(path):
    """Any image OpenCV can read, 16-bit and alpha kept; OpenCV has no decompression-bomb limit for our own results."""
    image = cv2.imread(str(path), cv2.IMREAD_UNCHANGED)
    if image is None:
        raise OSError(f"Could not read {path.name}")
    return image


def rotate_file(path, turns, metadata=None, quality=config.DEFAULT_QUALITY):
    """Turns an image file in place and returns the turned pixels."""
    image = rotate(read_image(path), turns)
    write_image(path, image, metadata, quality)
    return image


def write_result_preview(path, image, metadata=None):
    """A light JPEG of a result for View and thumbnails: at most RESULT_PREVIEW_MAX_EDGE px, 8-bit, colour profile kept."""
    height, width = image.shape[:2]
    shrink = config.RESULT_PREVIEW_MAX_EDGE / max(height, width)
    if shrink < 1:
        image = cv2.resize(image, (round(width * shrink), round(height * shrink)), interpolation=cv2.INTER_AREA)
    if image.dtype != np.uint8:
        image = (image / UINT16_PER_UINT8).round().astype(np.uint8)
    icc_profile = (metadata or {}).get("icc_profile")
    # Written aside and renamed, so a page never reads a half-written preview; the name is swept if a crash leaves it
    temporary = path.with_name(f".{uuid.uuid4().hex}{config.TEMPORARY_SUFFIX}")
    try:
        _to_pil(image, ".jpg").save(temporary, "JPEG", quality=config.PREVIEW_QUALITY,
                                    **({"icc_profile": icc_profile} if icc_profile else {}))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
