"""HEIC/HEIF photos from phones, turned once, on arrival, into a PNG the models can read.

libheif, a C library, decodes them in a child process: a file that crashes or hangs it then costs that one upload, not
the app (nor, dropped into the inbox, a crash at every start). The app itself never loads it, so libheif only ever sees
files named .heic or .heif.
"""
import subprocess
import sys
import warnings

from PIL import Image

import config


def heif_to_png(source):
    """Converts the file beside itself and removes it; returns the PNG's path. Raises OSError when it can't."""
    target = source.with_suffix(config.HEIF_STORED_AS)
    try:
        subprocess.run([sys.executable, __file__, source, target], check=True, capture_output=True,
                       timeout=config.HEIF_CONVERT_TIMEOUT_SECONDS)
    except subprocess.SubprocessError as error:
        target.unlink(missing_ok=True)
        # The last line the child wrote says what went wrong, without its traceback; a crash or timeout writes none
        reason = (error.stderr or b"").decode(errors="replace").strip().rpartition("\n")[2] or str(error)
        print(config.HEIF_FAILED_LOG.format(name=source.name, reason=reason), flush=True)
        raise OSError(reason) from error
    source.unlink()
    return target


def _convert(source, target):
    """In the child: the decoder has turned the pixels upright and set the EXIF orientation to match."""
    import pillow_heif

    pillow_heif.register_heif_opener(thumbnails=False, depth_images=False, aux_images=False)
    Image.MAX_IMAGE_PIXELS = config.PILLOW_MAX_IMAGE_PIXELS
    warnings.simplefilter("ignore", Image.DecompressionBombWarning)
    with Image.open(source) as image:
        exif = image.getexif()
        image.save(target, compress_level=config.PNG_COMPRESS_LEVEL, icc_profile=image.info.get("icc_profile"),
                   exif=exif.tobytes() if exif else None)


if __name__ == "__main__":
    _convert(*sys.argv[1:])
